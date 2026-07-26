import logging
from contextlib import contextmanager
import requests
import openai
from langchain_text_splitters import RecursiveCharacterTextSplitter
from uuid import UUID
from sqlmodel import col, delete

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
    markdown_download_url: str, document_id: str, organization_id: str
) -> None:
    """
    Download markdown content, chunk it, generate embeddings, and store them.

    Fetches the markdown file from the given presigned URL, splits it into
    chunks using RecursiveCharacterTextSplitter, generates OpenAI embeddings
    for each chunk, and persists everything to the database.

    Args:
        markdown_download_url: Presigned S3 URL to download the markdown file.
        document_id: UUID string of the document being processed.
        organization_id: UUID string of the owning organization.
    """
    logger.info("Generating embeddings for document %s", document_id)

    response = requests.get(markdown_download_url)
    response.raise_for_status()
    file_text = response.text
    logger.debug(
        "Downloaded markdown content (%d chars) for document %s",
        len(file_text),
        document_id,
    )

    file_chunks = chunk_document(file_text)
    logger.debug("Split document %s into %d chunks", document_id, len(file_chunks))

    response = client.embeddings.create(
        input=file_chunks, model="text-embedding-3-small"
    )

    embeddings = [item.embedding for item in response.data]
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
        [["asdf"]],
        [[123]],
        "4f225ee2-e003-4820-93de-c5de4b2bd2a4",
        "70885aed-0503-4656-bb72-368a26758575",
    )
