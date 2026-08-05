import os
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any, TypedDict, cast
from uuid import UUID

import cohere
import openai
from database.models import Document, DocumentChunk, DocumentStatus
from database.session import get_db
from logutil import get_logger
from sqlmodel import select, tuple_

logger = get_logger(__name__)

# ── Lazy client initialisation ───────────────────────────────────────
# The OpenAI and Cohere clients are created on first use rather than at
# import time so that:
# 1. The module can be imported without ``OPENAI_API_KEY`` or
#    ``COHERE_API_KEY`` set (e.g. during documentation generation or
#    when only certain routes are loaded).
# 2. Unit tests can set environment variables or patch the clients
#    before they are ever instantiated.

_client: openai.Client | None = None
_cohere_client: cohere.Client | None = None
RERANK_MODEL = "rerank-english-v3.0"

# Number of candidate chunks pulled from the vector store (nearest
# neighbours) before the expensive cross-encoder re-ranker runs.
#
# This is the *recall* gate of the pipeline: the vector search is cheap,
# while the Cohere re-ranker is the quality bottleneck, so we deliberately
# fetch more candidates than we surface and let the re-ranker decide.
# Truncating early (as with the old limit of 5) starves the re-ranker of
# relevant-but-lower-ranked chunks.
#
# Costs / trade-offs of a wider window:
#   * Cohere ``rerank`` is priced per document — 30 is 6× the spend of 5;
#     the API accepts up to 1000 documents, so 30 is well within limits.
#   * The neighbour-merge fan-out is 2 × N aux rows (≤ 60 for N = 30),
#     a single indexed ``tuple_ IN`` query — negligible.
#   * ``query_documents`` deduplicates by document after re-ranking, so a
#     wide window mostly adds *document* diversity, not just chunk hits.
VECTOR_SEARCH_CANDIDATE_LIMIT = os.environ.get("VECTOR_SEARCH_CANDIDATE_LIMIT", 30)


def _get_openai_client() -> openai.Client:
    """Return the singleton OpenAI client, creating it if necessary."""
    global _client
    if _client is None:
        _client = openai.Client()
    return _client


def _get_cohere_client() -> cohere.Client:
    """Return the singleton Cohere client, creating it if necessary."""
    global _cohere_client
    if _cohere_client is None:
        _cohere_client = cohere.Client(os.environ["COHERE_API_KEY"])
    return _cohere_client


class QueryDocumentResult(TypedDict):
    document: Document
    relevance: float


class ParentChunk(TypedDict):
    document: Document
    chunk_content: str


class RerankResult(TypedDict):
    chunk: ParentChunk
    rank: int
    relevance: float


def _embed_query(query: str) -> list[float]:
    """
    Embed a natural-language query into a dense vector using OpenAI's
    ``text-embedding-3-small`` model.

    Parameters
    ----------
    query : str
        The user's search query (plain text).

    Returns
    -------
    list[float]
        1536-dimensional embedding vector.
    """
    logger.info("Embedding query: query_len=%d", len(query))
    openai_client = _get_openai_client()
    response = openai_client.embeddings.create(
        input=query, model="text-embedding-3-small"
    )

    embedding = response.data[0].embedding
    logger.debug(
        "Embedding generated: dim=%d, first_5=%s", len(embedding), embedding[:5]
    )
    return embedding


def rerank_docs(query: str, chunks: Sequence[ParentChunk]) -> list[RerankResult]:
    """
    Re-rank an already-ordered list of chunks using Cohere's cross-encoder
    reranking model.

    The input ``chunks`` are typically the result of vector similarity search;
    this function re-scores them with a more expensive (but more accurate)
    cross-encoder and returns them in the new relevance order together with
    a ``relevance`` score in ``[0, 1]``.

    Parameters
    ----------
    query : str
        The original search query.
    chunks : Sequence[ParentChunk]
        Candidate chunks (each containing document metadata and chunk text).

    Returns
    -------
    list[RerankResult]
        Re-ranked results, sorted by descending relevance.
    """
    logger.info("Re-ranking %d chunks for query: query_len=%d", len(chunks), len(query))

    cohere_api_client = _get_cohere_client()
    rerank_response = cohere_api_client.rerank(
        model=RERANK_MODEL,
        query=query,
        documents=[chunk["chunk_content"] for chunk in chunks],
    )

    results: list[RerankResult] = []
    for rank, hit in enumerate(rerank_response.results):
        results.append(
            {
                "chunk": chunks[hit.index],
                "rank": rank,
                "relevance": hit.relevance_score,
            }
        )

    logger.info(
        "Re-ranking complete: top_score=%.4f, results=%d",
        results[0]["relevance"] if results else 0.0,
        len(results),
    )
    return results


def _get_chunks(
    vector: list[float],
) -> list[ParentChunk]:
    """
    Fetch the top-``VECTOR_SEARCH_CANDIDATE_LIMIT`` most semantically
    similar chunks to *vector*, together with their immediate
    predecessor/successor neighbours and the parent ``Document`` records —
    all in a single database session.

    Adjacent chunks are *merged* (prepended / appended) to their parent
    initial chunk so that the downstream re-ranker sees a wider window of
    context around each hit.

    Only chunks whose parent ``Document`` has status ``PROCESSED`` are
    returned; chunks referencing missing, unprocessed, errored, or stale
    documents ("dangling chunks") are dropped with a warning.  This means
    the returned list may contain fewer than ``VECTOR_SEARCH_CANDIDATE_LIMIT``
    entries, or be empty even when the vector store has hits.

    Parameters
    ----------
    vector : list[float]
        Query embedding vector (1536 floats for ``text-embedding-3-small``).

    Returns
    -------
    list[ParentChunk]
        Up to ``VECTOR_SEARCH_CANDIDATE_LIMIT`` ``ParentChunk`` entries
        (one per vector-similarity hit), each containing the parent
        ``Document`` and the chunk text with adjacent neighbours merged in.
    """
    with contextmanager(get_db)() as db:
        # Cast to ``Any`` to satisfy the type checker — SQLModel / SQLAlchemy
        # column attributes don't natively expose ``cosine_distance``.
        embedding_col = cast(Any, DocumentChunk.embedding)

        # 1. Top-N most similar chunks (ANN / exact nearest-neighbour),
        #    where N == VECTOR_SEARCH_CANDIDATE_LIMIT.  Fetching a wide
        #    candidate window here is deliberate: the vector score is only
        #    a rough cut, and the Cohere re-ranker downstream is the real
        #    quality gate.  See the constant definition for the reasoning.
        initial_chunks = db.exec(
            select(DocumentChunk)
            .order_by(embedding_col.cosine_distance(vector))
            .limit(VECTOR_SEARCH_CANDIDATE_LIMIT)
        ).all()

        logger.debug(
            "Vector search: initial_chunks=%d (candidate_limit=%d)",
            len(initial_chunks),
            VECTOR_SEARCH_CANDIDATE_LIMIT,
        )

        if len(initial_chunks) >= VECTOR_SEARCH_CANDIDATE_LIMIT:
            # The window is completely full — the true nearest neighbours
            # may extend past the limit, so recall may be truncated here.
            # Log at DEBUG so operators can spot when the limit needs
            # raising (e.g. as the corpus grows).
            #
            # ``>=`` (not ``==``) is deliberate: a corpus with *exactly* N
            # chunks false-positives (nothing was actually truncated), but
            # adding a ``COUNT(*)`` probe per search to disambiguate is not
            # worth a DB round-trip for a DEBUG-only heuristic signal.
            logger.warning("Candidate window is full; recall may be truncated")

        if not initial_chunks:
            logger.info("No chunks found for the given query vector")
            return []

        # 2. Pre-fetch documents for all initial chunks so that we don't
        #    need a second DB round-trip later in ``query_documents``.
        #
        #    We only load documents whose status is ``PROCESSED``: chunks are
        #    written while a document is still ``PROCESSING`` (see
        #    ``generate_embeddings.upload_embeddings``), and only after the
        #    full pipeline completes is the status flipped to ``PROCESSED``.
        #    Serving search results from partially-processed documents would
        #    leak incomplete or superseded content, so anything else —
        #    ``UPLOADING``, ``PROCESSING``, ``ERROR``, ``STALE``, or a
        #    document that was deleted outright — is excluded here.  The
        #    trade-off is a short visibility window (chunks written, status
        #    not yet flipped) which is preferable to serving stale data.
        #
        #    NOTE: this also acts as the *only* guard against dangling
        #    chunks: a chunk whose parent document is gone (e.g. deleted
        #    after a re-upload) will never match this query and is filtered
        #    out in step 3 below.
        doc_ids = {c.document_id for c in initial_chunks}
        logger.debug(
            "Searching for parent documents (PROCESSED only): ids=%s",
            sorted(map(str, doc_ids)),
        )
        id_col = cast(Any, Document.id)
        doc_map = {
            d.id: d
            for d in db.exec(
                select(Document).where(
                    id_col.in_(doc_ids), Document.status == DocumentStatus.PROCESSED
                )
            ).all()
        }
        logger.info(
            "Pre-fetched %d/%d parent documents (PROCESSED only)",
            len(doc_map),
            len(doc_ids),
        )

        # 3. Build a map of ``(doc_id, chunk_index) -> ParentChunk`` and
        #    collect the neighbour positions we need to fetch.
        #
        #    A chunk whose parent document is not in ``doc_map`` is a
        #    *dangling chunk*: the document is either not ``PROCESSED`` yet
        #    or has been deleted (leaving orphaned rows behind).  Such chunks
        #    must never surface in search results, so we skip them entirely
        #    — including their neighbours, which keeps the aux-chunk query
        #    below free of dead documents.
        target_pairs: list[tuple[UUID, int]] = []
        initial_chunk_map: dict[tuple[UUID, int], ParentChunk] = {}

        for chunk in initial_chunks:
            if chunk.document_id not in doc_map:
                # Data-integrity signal: the vector store still references a
                # document that is missing or not fully processed.  Log it
                # (rather than failing the whole search) so that orphaned
                # chunks can be detected and cleaned up.
                logger.warning(
                    "Dropping dangling chunk: chunk_id=%s index=%d "
                    "document_id=%s (parent missing or not PROCESSED)",
                    chunk.id,
                    chunk.chunk_index,
                    chunk.document_id,
                )
                continue

            # Request the immediate predecessor and successor
            target_pairs.append((chunk.document_id, chunk.chunk_index - 1))
            target_pairs.append((chunk.document_id, chunk.chunk_index + 1))
            initial_chunk_map[(chunk.document_id, chunk.chunk_index)] = {
                "document": doc_map[chunk.document_id],
                "chunk_content": chunk.content,
            }

        # Every initial chunk was dangling — nothing left to search for.
        # Short-circuit so we don't waste a DB round-trip on neighbours.
        if not initial_chunk_map:
            logger.warning(
                "All %d initial chunks are dangling; returning empty result",
                len(initial_chunks),
            )
            return []

        # 4. Fetch neighbour chunks in the same session
        aux_chunks = db.exec(
            select(DocumentChunk).where(
                tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(
                    target_pairs
                )
            )
        ).all()

        logger.debug("Fetched %d adjacent neighbour chunks", len(aux_chunks))

    # ── Merge adjacent chunks into their "parent" initial chunk ──
    #
    # For each neighbour chunk we figure out whether it sits immediately
    # before or after an initial chunk and merge accordingly.
    #
    # NOTE(@coscan): If two different initial chunks are only 2 positions
    # apart (e.g. indexes 10 and 12) a single aux chunk at index 11 would
    # be merged into *both* parents, effectively duplicating its content.
    # This is an edge case that should be vanishingly rare in practice —
    # although note that with a wider candidate window
    # (``VECTOR_SEARCH_CANDIDATE_LIMIT`` = 30) *adjacent* initial chunks
    # are common, so overlapping neighbour windows (the same passage
    # appearing inside two merged contexts) are expected and acceptable:
    # the re-ranker down-weights redundant passages and the final
    # document-level dedup in ``query_documents`` hides the overlap.
    for aux_chunk in aux_chunks:
        # Is this aux chunk the predecessor of an initial chunk?
        # i.e. initial_chunk_index == aux_chunk.chunk_index + 1
        key = (aux_chunk.document_id, aux_chunk.chunk_index + 1)
        if key in initial_chunk_map:
            initial_chunk = initial_chunk_map[key]
            initial_chunk["chunk_content"] = (
                aux_chunk.content + initial_chunk["chunk_content"]
            )

        # Is this aux chunk the successor of an initial chunk?
        # i.e. initial_chunk_index == aux_chunk.chunk_index - 1
        key = (aux_chunk.document_id, aux_chunk.chunk_index - 1)
        if key in initial_chunk_map:
            initial_chunk = initial_chunk_map[key]
            initial_chunk["chunk_content"] = (
                initial_chunk["chunk_content"] + aux_chunk.content
            )

    # Merge pass complete.  Log the final funnel size (N initial candidates
    # → M surviving parents) at DEBUG so the recall behaviour of the
    # pipeline can be observed when tuning ``VECTOR_SEARCH_CANDIDATE_LIMIT``:
    # a large gap between N and M means many dangling chunks, while a
    # persistent "window full" signal (see above) means the limit itself is
    # the bottleneck.
    logger.info("Neighbour merge complete: parent_chunks=%d", len(initial_chunk_map))

    return list(initial_chunk_map.values())


def query_documents(query: str) -> list[QueryDocumentResult]:
    """
    End-to-end retrieval: embed the query, perform vector similarity search
    (with neighbour merging), re-rank with Cohere, and return unique
    ``Document`` records ordered by descending relevance.

    Parameters
    ----------
    query : str
        The user's search query.

    Returns
    -------
    list[QueryDocumentResult]
        Unique documents sorted by descending relevance, each with its
        relevance score from the Cohere re-ranker.
    """
    logger.info("Querying documents: query=%r", query[:120])

    vector = _embed_query(query)
    chunks = _get_chunks(vector)

    if not chunks:
        logger.info("No chunks found — returning empty result")
        return []

    rerank_results = rerank_docs(query, chunks)

    # ── Deduplicate by document ID, preserving the reranker's order ──
    # The same document may appear multiple times in ``rerank_results``
    # (different chunks belonging to the same parent); we keep only the
    # first (highest-ranked) occurrence.
    seen: set[UUID] = set()
    final_results: list[QueryDocumentResult] = []
    for result in rerank_results:
        doc = result["chunk"]["document"]
        if doc.id not in seen:
            final_results.append({"document": doc, "relevance": result["relevance"]})
            seen.add(doc.id)

    logger.info(
        "Query complete: unique_documents=%d, top_relevance=%.4f",
        len(final_results),
        final_results[0]["relevance"] if final_results else 0.0,
    )
    return final_results


if __name__ == "__main__":
    # Manual smoke test — runs the full retrieval pipeline for a fixed query.
    # Requires OPENAI_API_KEY, COHERE_API_KEY and a reachable DATABASE_URL.
    import json

    print(
        json.dumps(
            [
                {
                    "document_id": str(result["document"].id),
                    "filename": result["document"].filename,
                    "s3_key": result["document"].s3_key,
                    "relevance": result["relevance"],
                }
                for result in query_documents("money")
            ],
            indent=2,
        )
    )
