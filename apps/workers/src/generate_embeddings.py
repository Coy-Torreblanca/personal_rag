import logging
from contextlib import contextmanager
import openai
from langchain_text_splitters import RecursiveCharacterTextSplitter
from uuid import UUID
from sqlmodel import delete

from database.models import DocumentChunk
from database.session import get_db

logger = logging.getLogger(__name__)

client = openai.Client()


def upload_embeddings(
    file_chunks: list[str],
    embeddings: list[list[float]],
    document_id: str,
    organization_id: str,
) -> None:
    """
    Upload document chunks with their embeddings to the database.

    Deletes any existing chunks for the given document, then inserts
    new chunks with their corresponding vector embeddings.

    Args:
        file_chunks: List of text chunks from the document.
        embeddings: List of embedding vectors corresponding to each chunk.
        document_id: UUID string of the document to associate chunks with.
        organization_id: UUID string of the organization owning the chunks.
    """
    logger.info(
        "Uploading %d embeddings for document %s",
        len(file_chunks),
        document_id,
    )
    with contextmanager(get_db)() as db:
        sql_statement = delete(DocumentChunk).where(
            DocumentChunk.document_id == UUID(document_id)
        )

        db.exec(sql_statement)

        for i in range(len(embeddings)):
            doc_chunk = DocumentChunk(
                document_id=UUID(document_id),
                organization_id=UUID(organization_id),
                chunk_index=i,
                content=file_chunks[i],
                embedding=embeddings[i],
            )

            db.add(doc_chunk)

        db.commit()
        logger.debug(
            "Successfully uploaded %d chunks for document %s",
            len(file_chunks),
            document_id,
        )


def generate_embeddings(
    file_text: str, document_id: str, organization_id: str, document_summary: str
) -> None:
    """
    Chunk document text together with its LLM summary, generate embeddings,
    and store them.

    The ``document_summary`` is joined to ``file_text`` on its own line and
    the combined text is split into overlapping chunks, so the summary is
    embedded within the same context windows as the content it describes
    (a short summary merges into the final chunk; a long one spans several
    chunks). OpenAI embeddings are generated for every chunk, and the
    chunks are persisted to the database.

    Args:
        file_text: The full markdown text of the processed document.
        document_id: UUID string of the document being processed.
        organization_id: UUID string of the owning organization.
        document_summary: Non-empty LLM summary of the document; joined to
            ``file_text`` and chunked together with the content so it is
            embedded and searchable like any other content.

    Raises:
        ValueError: If the embedding API returns a number of vectors that
            does not match the number of input chunks.
        openai.OpenAIError: If the upstream embeddings call fails.
    """
    logger.info("Generating embeddings for document %s", document_id)

    # Fold the summary into the chunking input instead of embedding it as a
    # detached top-level vector: joining it to the document text (on its own
    # line) keeps the summary inside the same 500-char context windows as the
    # surrounding content, so whole-document intent stays tied to the content
    # it describes. ``generate_llm_summary`` upstream guarantees a non-empty
    # summary, so this input is always meaningful.
    file_chunks = chunk_document(file_text + "\n" + document_summary)
    logger.debug(
        "Split document %s and its %d-char summary into %d chunks",
        document_id,
        len(document_summary),
        len(file_chunks),
    )

    response = client.embeddings.create(
        input=file_chunks, model="text-embedding-3-small"
    )

    embeddings = [item.embedding for item in response.data]

    # The API returns exactly one vector per input, in order. A count
    # mismatch means the response is truncated or corrupt — fail loudly with
    # a clear message instead of letting ``upload_embeddings`` crash on an
    # ``IndexError`` deep in the persistence loop.
    if len(embeddings) != len(file_chunks):
        raise ValueError(
            f"Embedding count mismatch: expected {len(file_chunks)} embeddings "
            f"for document {document_id}, got {len(embeddings)}."
        )

    logger.debug(
        "Generated %d embeddings for document %s",
        len(embeddings),
        document_id,
    )

    upload_embeddings(file_chunks, embeddings, document_id, organization_id)
    logger.info("Finished generating embeddings for document %s", document_id)


def chunk_document(text: str) -> list[str]:
    """
    Split a document text into overlapping chunks for embedding.

    Uses RecursiveCharacterTextSplitter with separators for paragraphs,
    lines, words, and characters. Each chunk is at most 500 characters
    with a 50-character overlap between consecutive chunks.

    Args:
        text: The full document text to split.

    Returns:
        A list of text chunks ready for embedding.
    """
    text_splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", " ", ""], chunk_size=500, chunk_overlap=50
    )

    return text_splitter.split_text(text)


if __name__ == "__main__":
    upload_embeddings(
        ["asdf"],
        [[0.1] * 1536],
        "4f225ee2-e003-4820-93de-c5de4b2bd2a4",
        "70885aed-0503-4656-bb72-368a26758575",
    )
