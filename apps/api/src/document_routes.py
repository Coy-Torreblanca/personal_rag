"""Document and processing-job management routes.

Endpoints prefixed with ``/api`` and tagged ``documents``:

- ``GET /api/documents`` — List all documents.
- ``GET /api/documents/search?query=...`` — Semantic search over document content.
- ``GET /api/documents/{document_id}`` — Fetch a document's metadata, LLM summary, and markdown content.
- ``GET /api/documents/upload-url/{file_path:path}`` — Generate a presigned S3/R2 URL for uploading.
- ``POST /api/documents/{job_id}/process`` — Trigger document processing via Celery.
- ``GET /api/documents/{document_id}/download`` — Generate a presigned GET URL for downloading a document.
- ``DELETE /api/documents/{document_id}`` — Delete a document and its artifacts
  (processing jobs, indexed chunks, and the files in object storage).
- ``GET /api/processing-jobs`` — List all processing jobs.
- ``GET /api/processing-jobs/{job_id}`` — Fetch a single processing job.

All endpoints depend on a SQLModel database session injected via FastAPI's
``Depends`` mechanism.
"""

import os
from datetime import datetime
from uuid import UUID

from botocore.exceptions import ClientError
from database.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    ProcessingJob,
    ProcessingJobStatus,
)
from database.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from logutil import get_logger
from pydantic import BaseModel
from s3.client import R2Client
from s3.exceptions import S3Error
from s3.models import FileType, get_file_type_from_extension
from sqlmodel import Session, delete, func, select

from .celery_client import celery
from .document_search import query_documents

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/documents", response_model=list[Document])
def get_documents(db: Session = Depends(get_db)) -> list[Document]:
    """Retrieve all documents.

    Args:
        db: Injected database session.

    Returns:
        List of all ``Document`` records.
    """
    documents = db.exec(select(Document)).all()
    logger.info("Retrieved %d documents", len(documents))
    return documents


@router.get("/documents/upload-url/{file_path:path}")
async def get_upload_s3_url(
    file_path: str,
    organization_id: UUID = Query(...),
    user_id: UUID = Query(...),
    content_type: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    """Generate a presigned URL for uploading a document to S3/R2 storage.

    The endpoint creates a ``Document`` record (status ``UPLOADING``) and a
    ``ProcessingJob`` record (status ``PENDING``) before returning a
    time-limited presigned URL that the client can use to upload the file
    directly to object storage.

    Existing documents that reference the same S3 key are transitioned to
    ``STALE`` once the new presigned URL has been generated, because the
    upload overwrites the object they point at. ``ERROR`` documents are
    left untouched so the failure stays visible for debugging. The
    transition is committed atomically with the new ``Document`` record and
    never happens if presigning fails.

    Args:
        file_path: The object key path (supports nested paths via ``/``).
        organization_id: UUID of the owning organisation.
        user_id: UUID of the uploading user.
        content_type: MIME type of the file being uploaded (e.g. ``application/pdf``).
        db: Injected database session.

    Returns:
        dict containing:
            - ``success``: Always ``True`` when no error occurs.
            - ``url``: Presigned URL for a PUT request.
            - ``bucket``: Target S3/R2 bucket name.
            - ``key``: Full object key (``{organization_id}/{file_path}``).
            - ``method``: HTTP method (``PUT``).
            - ``expires_in``: URL validity duration in seconds.
            - ``message``: Human-readable success message.
            - ``job_id``: UUID of the newly created processing job.

    Raises:
        HTTPException 400: If the S3 operation fails, or if a document with
            this S3 key already has an active (non-failed, non-completed)
            processing job.
        HTTPException 500: If ``BUCKET_NAME`` is not configured or an
            unexpected error occurs.
    """
    bucket_name = os.environ.get("BUCKET_NAME")

    if not bucket_name:
        logger.error("No BUCKET_NAME environment variable configured")
        raise HTTPException(status_code=500, detail="No bucket name configured")

    # Build the object key with an organisation-level prefix for multi-tenancy.
    key = f"{organization_id}/{file_path}"

    # ------------------------------------------------------------------
    # Step 1 — Guard clause: refuse to overwrite a key that is still being
    # processed. Documents that pass the guard are collected into
    # ``stale_docs`` because their S3 object is about to be overwritten.
    # ------------------------------------------------------------------
    statement = select(Document).where(Document.s3_key == key)
    existing_docs = db.exec(statement)

    # Documents whose object is about to be overwritten by this upload.
    # They are only mutated AFTER presigning succeeds (see step 2), so a
    # failed presign leaves the database completely untouched.
    stale_docs: list[Document] = []

    for doc in existing_docs:
        # Access the column directly so the SQL NOT IN clause works correctly.
        # Pyright doesn't recognise column operators on SQLModel fields, so
        # we cast via ``__table__.c`` (runtime-valid) and suppress the type
        # checker warning.
        status_col = ProcessingJob.__table__.c.status  # pyright: ignore[reportAttributeAccessIssue]
        statement = (
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.document_id == doc.id,
                status_col.notin_(
                    [ProcessingJobStatus.FAILED, ProcessingJobStatus.COMPLETED]
                ),
            )
        )

        if db.scalar(statement) != 0:
            logger.warning(
                "Upload blocked for key %s — active processing job found for document %s",
                key,
                doc.id,
            )
            raise HTTPException(
                status_code=400,
                detail=f"A document with this S3 key is already being processed: {key!r}",
            )

        # The document's S3 object will be overwritten by this upload, so
        # the record no longer describes the content at ``key``. Any
        # non-ERROR document is a candidate for the STALE transition.
        # ``ERROR`` documents are deliberately left untouched: the status
        # is the only record of the failure and should remain visible for
        # debugging. Already-stale documents are skipped to avoid pointless
        # UPDATE statements.
        if doc.status not in (DocumentStatus.ERROR, DocumentStatus.STALE):
            stale_docs.append(doc)

    logger.debug("No active jobs for key %s — proceeding with upload", key)

    expiration = 3600  # TODO: Make expiration configurable per request.

    # Generate the presigned URL BEFORE persisting anything. If presigning
    # fails we return a 500 with no side effects: the key is not left locked
    # by an orphaned Document/ProcessingJob pair, and the client can simply
    # retry. Only ``S3Error`` (and its subclasses) is converted to a 500;
    # anything else propagates so real bugs surface in the logs.
    try:
        client = R2Client(bucket_name=bucket_name)
        response = client.generate_presigned_url(
            key=key,
            expiration=expiration,
            method="PUT",
            inline=False,
            content_type=content_type,
        )
    except S3Error as e:
        logger.exception("Failed to generate presigned upload URL for key %s", key)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate upload URL. Please try again.",
        ) from e

    logger.info(
        "Generated presigned upload URL for document with key %s",
        key,
    )

    # ------------------------------------------------------------------
    # Step 2 — Mark superseded documents as STALE (only after presigning)
    # ------------------------------------------------------------------
    # The S3 object referenced by every document in ``stale_docs`` is about
    # to be overwritten by this upload, so those records no longer describe
    # the content at ``key``. Transition them to ``STALE`` so clients can
    # distinguish superseded records from current ones.
    #
    # This is intentionally deferred until AFTER the presigned URL has been
    # generated: the "presign before persist" invariant guarantees a failed
    # presign leaves the database completely untouched (no orphaned jobs,
    # no committed status transitions). The transition is committed
    # atomically with the new ``Document`` record below — a single
    # transaction, so a crash mid-request cannot leave a half-updated state.
    for doc in stale_docs:
        doc.status = DocumentStatus.STALE

    if stale_docs:
        logger.info(
            "Marked %d superseded document(s) stale for key %s",
            len(stale_docs),
            key,
        )

    # Persist a Document record so the client can track upload progress.
    doc = Document(
        organization_id=organization_id,
        user_id=user_id,
        filename=file_path,
        s3_key=key,
        status=DocumentStatus.UPLOADING,
        file_type=content_type,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    logger.info("Created document %s with key %s", doc.id, key)

    # Create a pending processing job that a worker will pick up later.
    job = ProcessingJob(
        document_id=doc.id,
        job_type="Upload+Embedding",
        status=ProcessingJobStatus.PENDING,
    )
    db.add(job)
    db.commit()

    job_id = job.id

    logger.debug("Created processing job %s for document %s", job_id, doc.id)

    return {
        "success": True,
        "url": response.url,
        "bucket": response.bucket,
        "key": response.key,
        "method": response.method,
        "expires_in": response.expires_in,
        "message": response.message,
        "job_id": job_id,
    }


@router.post("/documents/{job_id}/process")
def process_document(job_id: UUID, db: Session = Depends(get_db)) -> dict:
    """Trigger asynchronous document processing via Celery.

    Validates the job and its associated document, generates presigned URLs
    for downloading the source and uploading the processed result (Markdown),
    then dispatches a ``process_document`` Celery task to the worker pool.

    Args:
        job_id: UUID of the ``ProcessingJob`` to execute.
        db: Injected database session.

    Returns:
        dict containing:
            - ``message``: Confirmation text.
            - ``document_id``: UUID of the document being processed.
            - ``task_id``: Celery task ID (same as ``job_id``).
            - ``status``: Always ``"processing"``.

    Raises:
        HTTPException 400: If the document is already processing, the job is
            not pending, the source file has not been uploaded to R2 yet, or
            validation fails.
        HTTPException 404: If the job or its document is not found.
        HTTPException 500: If ``BUCKET_NAME`` is unconfigured or any
            unexpected error occurs.
    """
    job = db.get(ProcessingJob, job_id)

    if not job:
        logger.warning("Job not found: %s", job_id)
        raise HTTPException(
            status_code=404,
            detail="Job id provided does not correspond with any known jobs.",
        )

    document = db.get(Document, job.document_id)

    if not document:
        logger.warning("Document not found for job %s, marking job as failed", job_id)
        job.status = ProcessingJobStatus.FAILED
        db.add(job)
        db.commit()
        raise HTTPException(
            status_code=404, detail="Document associated with job not found"
        )

    if document.status == DocumentStatus.PROCESSING:
        logger.warning("Document %s is already processing", document.id)
        raise HTTPException(status_code=400, detail=f"Document is already processing.")

    if not document.s3_key:
        logger.error("Document %s has no S3 key", document.id)
        raise HTTPException(
            status_code=500,
            detail=f"Could not find s3 key for document: {document.id}",
        )

    if job.status != ProcessingJobStatus.PENDING:
        logger.warning("Job %s is not pending (status=%s)", job_id, job.status.value)
        raise HTTPException(
            status_code=400,
            detail=f"Job is not in pending status: {job.status.value}",
        )

    bucket_name = os.environ.get("BUCKET_NAME")
    if not bucket_name:
        raise HTTPException(status_code=500, detail="No bucket name configured")

    try:
        client = R2Client(bucket_name=bucket_name)

        # Validate that the file actually exists in R2 before proceeding.
        # NOTE: this HTTPException(400) is intentionally NOT an ``S3Error``,
        # so it passes straight through the ``except S3Error`` below — a
        # missing file is a client error, not an infrastructure failure.
        if not client.file_exists(key=document.s3_key):
            logger.warning(
                "Document %s key %s not found in R2", document.id, document.s3_key
            )
            raise HTTPException(
                status_code=400,
                detail="The document file has not been uploaded yet. Please upload the file before processing.",
            )

        expiration = 3600  # TODO: Make expiration configurable.

        # Presigned URL for downloading the original document.
        download_response = client.generate_presigned_url(
            key=document.s3_key,
            expiration=expiration,
            method="GET",
            inline=False,
        )
        download_url = download_response.url

        # Presigned URL for uploading the processed Markdown output.
        upload_response = client.generate_presigned_url(
            key=document.s3_key + ".md",
            expiration=expiration,
            method="PUT",
            inline=False,
        )
        upload_url = upload_response.url
    # Any S3/R2 infrastructure failure (config, connectivity, signing) is
    # mapped to a clean 500 BEFORE any status transitions happen, so a
    # transient error cannot leave the job half-transitioned. Note: the
    # s3 package's ``file_exists`` can re-raise a raw botocore ``ClientError``
    # for non-404 failures; that would escape this handler and surface as a
    # generic 500 — acceptable, since it is logged upstream.
    except (S3Error, ClientError) as e:
        logger.exception("Failed to prepare S3 URLs for document %s", document.id)
        raise HTTPException(
            status_code=500,
            detail="Failed to prepare document processing. Please try again.",
        ) from e

    # Transition statuses.
    document.status = DocumentStatus.PROCESSING
    db.add(document)

    job.celery_task_id = str(job_id)
    job.status = ProcessingJobStatus.PROCESSING
    db.add(job)

    document_id = document.id
    organization_id = document.organization_id
    s3_key = document.s3_key

    try:
        db.flush()

        # Dispatch the long-running processing task to Celery workers.
        result = celery.send_task(
            "process_document",
            args=[
                str(document_id),
                str(organization_id),
                s3_key,
                download_url,
                upload_url,
            ],
            task_id=str(job_id),
        )
        db.commit()

        logger.info(
            "Dispatched document %s processing to Celery (task %s)",
            document_id,
            result.id,
        )

    except Exception as e:
        db.rollback()
        logger.exception("Failed to dispatch Celery task for document %s", document_id)
        raise e

    return {
        "message": "Document processing started",
        "document_id": str(document_id),
        "task_id": result.id,
        "status": "processing",
    }


@router.get("/documents/{document_id}/download")
def download_document(document_id: UUID, db: Session = Depends(get_db)) -> dict:
    """Generate a presigned URL for downloading a document.

    Looks up the document, verifies the object exists in object storage,
    then produces a time-limited presigned GET URL the client can use to
    download the original file directly from R2.

    .. note::

       **Authentication / scoping** — This endpoint currently returns a
       presigned URL for **any** document id without checking that the
       caller belongs to the document's organisation. A future iteration
       should inject a ``current_user`` dependency and verify
       ``document.organization_id`` matches the caller.

    Args:
        document_id: UUID of the document to download.
        db: Injected database session.

    Returns:
        dict containing:
            - ``success``: Always ``True`` on success.
            - ``url``: Presigned URL for a GET request.
            - ``filename``: Original filename for the client's download.
            - ``key``: Full object key.
            - ``method``: HTTP method (``GET``).
            - ``expires_in``: URL validity duration in seconds.
            - ``message``: Human-readable success message.

    Raises:
        HTTPException 404: If the document does not exist, or if the
            underlying object has not been uploaded to R2 yet.
        HTTPException 500: If ``BUCKET_NAME`` is unconfigured, the
            document has no S3 key, or presigning fails.
    """
    logger.info("Generating download URL for document %s", document_id)
    document = db.get(Document, document_id)
    if not document:
        logger.warning("Document not found for download: %s", document_id)
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.s3_key:
        logger.error("Document %s has no S3 key", document_id)
        raise HTTPException(
            status_code=500,
            detail=f"Could not find s3 key for document: {document_id}",
        )

    bucket_name = os.environ.get("BUCKET_NAME")
    if not bucket_name:
        logger.error("No BUCKET_NAME environment variable configured")
        raise HTTPException(status_code=500, detail="No bucket name configured")

    expiration = 3600  # TODO: Make expiration configurable.

    try:
        client = R2Client(bucket_name=bucket_name)

        # Refuse to sign a URL for an object that was never uploaded.
        # Signing would "succeed" and hand the client a URL that 404s on
        # first use — an explicit error here is far clearer. As in
        # ``process_document``, the HTTPException raised below passes
        # straight through ``except S3Error``.
        if not client.file_exists(key=document.s3_key):
            logger.warning(
                "Document %s key %s not found in R2 — refusing to sign download URL",
                document_id,
                document.s3_key,
            )
            raise HTTPException(
                status_code=404,
                detail="The document file has not been uploaded yet.",
            )

        response = client.generate_presigned_url(
            key=document.s3_key,
            expiration=expiration,
            method="GET",
            inline=False,
        )
    except S3Error as e:
        logger.exception("Failed to generate download URL for document %s", document_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate download URL. Please try again.",
        ) from e

    logger.info(
        "Generated download URL for document %s (expires in %ds)",
        document_id,
        expiration,
    )

    return {
        "success": True,
        "url": response.url,
        "filename": document.filename,
        "key": response.key,
        "method": response.method,
        "expires_in": response.expires_in,
        "message": response.message,
    }


@router.delete("/documents/{document_id}", status_code=200)
def delete_document(document_id: UUID, db: Session = Depends(get_db)) -> dict:
    """Delete a document and all associated artefacts.

    Removes the document record, its processing jobs, its indexed chunks,
    and both the original file and processed ``.md`` output from S3/R2
    storage. The database deletes run in a single transaction and are
    committed atomically.

    Args:
        document_id: UUID of the document to delete.
        db: Injected database session.

    Returns:
        dict containing:
            - ``success``: Always ``True`` on success.
            - ``message``: Human-readable confirmation.
            - ``document_id``: The deleted document's UUID.

    Raises:
        HTTPException 404: If the document does not exist.
        HTTPException 500: If ``BUCKET_NAME`` is unconfigured, the S3
            deletion fails, or an unexpected error occurs.
    """
    logger.info("Deleting document %s", document_id)
    document = db.get(Document, document_id)
    if not document:
        logger.warning("Document not found for deletion: %s", document_id)
        raise HTTPException(status_code=404, detail="Document not found")

    bucket_name = os.environ.get("BUCKET_NAME")
    if not bucket_name:
        logger.error("No BUCKET_NAME environment variable configured")
        raise HTTPException(status_code=500, detail="No bucket name configured")

    try:
        # Remove the file from object storage if it exists.
        if document.s3_key:
            try:
                client = R2Client(bucket_name=bucket_name)
                client.delete_file(key=document.s3_key)
                logger.debug(
                    "Deleted S3 file %s for document %s", document.s3_key, document_id
                )

                processed_document = f"{document.s3_key}.md"
                try:
                    client.delete_file(key=processed_document)
                    logger.debug(
                        "Deleted processed S3 file %s for document %s",
                        processed_document,
                        document_id,
                    )
                except S3Error:
                    logger.debug(
                        "Processed S3 file %s not found for document %s, skipping",
                        processed_document,
                        document_id,
                    )

            except S3Error as e:
                logger.error("Failed to delete S3 file %s: %s", document.s3_key, e)
                raise HTTPException(
                    status_code=500, detail="Error deleting the target file."
                ) from e

        # Cascade-delete all associated processing jobs and indexed chunks.
        #
        # Bulk ``DELETE`` statements are used instead of loading each row and
        # calling ``db.delete()`` — one statement per table instead of N+1
        # round trips. Order matters: child rows (jobs/chunks, which hold
        # foreign keys to ``documents.id``) must be removed before the parent
        # ``documents`` row is deleted by the ORM at flush time, or the FK
        # constraints would fail. All statements run inside the request's
        # transaction and are committed atomically below; any failure rolls
        # the whole batch back in the ``except`` handler.
        jobs_result = db.exec(
            delete(ProcessingJob).where(ProcessingJob.document_id == document_id)
        )
        chunks_result = db.exec(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        logger.debug(
            "Deleted %d processing job(s) and %d chunk(s) for document %s",
            jobs_result.rowcount,
            chunks_result.rowcount,
            document_id,
        )

        db.delete(document)
        db.commit()

        logger.info("Document %s deleted successfully", document_id)

        return {
            "success": True,
            "message": f"Document '{document.filename}' deleted successfully",
            "document_id": str(document_id),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Document deletion failed for %s", document_id)
        raise HTTPException(
            status_code=500,
            detail=f"Document deletion failed: {str(e)}",
        ) from e


@router.get("/processing-jobs", response_model=list[ProcessingJob])
def get_processing_jobs(db: Session = Depends(get_db)) -> list[ProcessingJob]:
    """Retrieve all processing jobs.

    Args:
        db: Injected database session.

    Returns:
        List of all ``ProcessingJob`` records.
    """
    jobs = db.exec(select(ProcessingJob)).all()
    logger.info("Retrieved %d processing jobs", len(jobs))
    return jobs


class DocumentSearchResult(BaseModel):
    """A single document returned by the semantic search endpoint.

    Includes only the fields that are useful for displaying search results
    together with the relevance score assigned by the Cohere re-ranker.

    The ``relevance`` field is a float in ``[0, 1]`` produced by the
    Cohere cross-encoder (``rerank-english-v3.0``).  It represents the
    semantic similarity between the query and the chunk text after
    re-ranking.
    """

    id: UUID
    organization_id: UUID
    user_id: UUID
    filename: str
    s3_key: str | None
    file_type: str
    file_size: int | None
    status: DocumentStatus
    created_at: datetime | None
    updated_at: datetime | None
    relevance: float


@router.get("/documents/search", response_model=list[DocumentSearchResult])
def search_documents(
    query: str = Query(..., min_length=1, max_length=500),
) -> list[DocumentSearchResult]:
    """Semantic search over document content.

    Accepts a natural-language query, embeds it with OpenAI
    ``text-embedding-3-small``, retrieves the most similar chunks from
    the vector store (with adjacent neighbour context), re-ranks them
    using Cohere's cross-encoder, and returns unique documents ordered
    by descending relevance.

    .. note::

       **Authentication / scoping** — This endpoint currently returns
       results across **all** documents in the system.  A future
       iteration should inject a ``current_user`` dependency to scope
       results to the calling user's organisation.

    .. todo::

       - Add pagination (``limit`` / ``offset``) to prevent unbounded
         response sizes.
       - Add a database session dependency if the search layer needs to
         access document metadata beyond what the vector store provides.

    Args:
        query: The search query (1-500 characters).

    Returns:
        A list of unique ``DocumentSearchResult`` items, sorted by
        descending relevance. Each item contains the document metadata
        and a ``relevance`` score in ``[0, 1]`` from the Cohere
        cross-encoder re-ranker.

    Raises:
        HTTPException 422: If ``query`` is empty or too long (handled
            by FastAPI's built-in validation).
        HTTPException 503: If the search backend (OpenAI embeddings,
            vector store, or Cohere re-ranker) is unreachable or returns
            an error.
    """
    logger.info("Search endpoint called: query_len=%d", len(query))

    # ------------------------------------------------------------------
    # NOTE: query_documents() returns a list[QueryDocumentResult] where
    # each dict has:
    #   "document"  — a SQLModel Document ORM instance
    #   "relevance" — a float from the Cohere re-ranker (typically in
    #                  [0, 1], but we clamp to be safe)
    # ------------------------------------------------------------------
    try:
        results = query_documents(query)
        logger.info(
            "Search completed: query_len=%d, results=%d",
            len(query),
            len(results),
        )
    except Exception:
        logger.exception("Search failed for query_len=%d", len(query))
        raise HTTPException(
            status_code=503,
            detail="Search service is currently unavailable. Please try again later.",
        )

    # Clamp relevance to [0, 1] to guard against edge-case scores from
    # the Cohere API that may fall slightly outside this range.
    clamped_results = []
    for result in results:
        relevance = result.get("relevance", 0.0)
        clamped_relevance = max(0.0, min(1.0, relevance))

        clamped_results.append(
            DocumentSearchResult(
                id=result["document"].id,
                organization_id=result["document"].organization_id,
                user_id=result["document"].user_id,
                filename=result["document"].filename,
                s3_key=result["document"].s3_key,
                file_type=result["document"].file_type,
                file_size=result["document"].file_size,
                status=result["document"].status,
                created_at=result["document"].created_at,
                updated_at=result["document"].updated_at,
                relevance=clamped_relevance,
            )
        )

    return clamped_results


class DocumentDetail(BaseModel):
    """Full document metadata plus its processed markdown content.

    Mirrors the ``Document`` model — including the LLM-generated
    ``summary`` written by the DeepSeek worker stage — and adds
    ``markdown_content`` fetched from object storage so a single request
    can power a document detail view in the UI.

    ``summary`` and ``markdown_content`` are nullable: documents are
    processed asynchronously after upload, so a freshly uploaded file may
    not have a summary or converted content yet.
    """

    id: UUID
    organization_id: UUID
    user_id: UUID
    filename: str
    file_type: str
    file_size: int | None
    s3_key: str | None
    status: DocumentStatus
    summary: str | None
    meta_data: dict[str, object]
    markdown_content: str | None
    created_at: datetime | None
    updated_at: datetime | None


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: UUID,
    db: Session = Depends(get_db),
) -> DocumentDetail:
    """Fetch a single document with its summary and markdown content.

    Returns the document's metadata (including the LLM-generated
    ``summary`` stored on the record) together with the processed
    markdown content read from object storage, so the UI can render a
    full detail view in one request.

    The markdown object key is resolved the same way the processing
    pipeline stores it: plain-text sources (``.txt``, ``.md``, ...) are
    already markdown and are read from the original key; every other
    file type is read from ``<s3_key>.md``.

    Missing markdown (document not processed yet, or the object was
    deleted) is reported as ``markdown_content: null`` rather than a 500
    — the metadata and summary are still valuable on their own, and the
    client can show a friendly "not available yet" state.

    .. note::

       **Authentication / scoping** — Like the other document endpoints,
       this returns details for **any** document id without verifying
       the caller belongs to the document's organisation. A future
       iteration should inject a ``current_user`` dependency and check
       ``document.organization_id``.

    Args:
        document_id: UUID of the document to fetch.
        db: Injected database session.

    Returns:
        The document's metadata, ``summary``, and ``markdown_content``.

    Raises:
        HTTPException 404: If no document with the given ID exists.
    """
    logger.info("Fetching document %s", document_id)
    document = db.get(Document, document_id)
    if not document:
        logger.warning("Document not found: %s", document_id)
        raise HTTPException(status_code=404, detail="Document not found")

    # Resolve the markdown object key exactly like the processing
    # pipeline: plain-text files are already markdown (read from the
    # original key), everything else is read from ``<s3_key>.md``.
    markdown_content: str | None = None
    if document.s3_key:
        try:
            if get_file_type_from_extension(document.s3_key) == FileType.TXT:
                markdown_key = document.s3_key
            else:
                markdown_key = f"{document.s3_key}.md"

            bucket_name = os.environ.get("BUCKET_NAME")
            if not bucket_name:
                logger.warning(
                    "No BUCKET_NAME configured — skipping markdown fetch for document %s",
                    document_id,
                )
            else:
                client = R2Client(bucket_name=bucket_name)
                response = client.download_bytes(key=markdown_key)
                markdown_content = response.content.decode(
                    "utf-8", errors="replace"
                )
                logger.debug(
                    "Fetched markdown for document %s (%d chars)",
                    document_id,
                    len(markdown_content),
                )
        except S3Error as e:
            # The markdown object may not exist yet (document still
            # processing) or may have been cleaned up — degrade gracefully
            # instead of failing the whole request.
            logger.warning(
                "Markdown content unavailable for document %s: %s",
                document_id,
                e,
            )
            markdown_content = None

    logger.info("Retrieved document %s", document_id)
    return DocumentDetail(
        id=document.id,
        organization_id=document.organization_id,
        user_id=document.user_id,
        filename=document.filename,
        file_type=document.file_type,
        file_size=document.file_size,
        s3_key=document.s3_key,
        status=document.status,
        summary=document.summary,
        meta_data=document.meta_data,
        markdown_content=markdown_content,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.get("/processing-jobs/{job_id}", response_model=ProcessingJob)
def get_processing_job(job_id: UUID, db: Session = Depends(get_db)) -> ProcessingJob:
    """Retrieve a single processing job by its UUID.

    Args:
        job_id: UUID of the processing job.
        db: Injected database session.

    Returns:
        The matching ``ProcessingJob`` record.

    Raises:
        HTTPException 404: If no job with the given ID exists.
    """
    job = db.get(ProcessingJob, job_id)
    if not job:
        logger.warning("Processing job not found: %s", job_id)
        raise HTTPException(status_code=404, detail="Processing job not found")
    logger.debug("Retrieved processing job %s", job_id)
    return job
