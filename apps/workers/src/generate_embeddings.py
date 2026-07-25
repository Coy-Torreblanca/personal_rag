from contextlib import contextmanager
import os
import requests
import openai
from langchain_text_splitters import RecursiveCharacterTextSplitter
from uuid import UUID
from sqlmodel import col, delete

from database.models import DocumentChunk
from database.session import get_db

client = openai.Client()


def upload_embeddings(
    file_chunks: list[str],
    embeddings: list[list[float]],
    document_id: str,
    organization_id: str,
) -> None:

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


def generate_embeddings(
    markdown_download_url: str, document_id: str, organization_id: str
) -> None:

    response = requests.get(markdown_download_url)
    response.raise_for_status()
    file_text = response.text

    file_chunks = chunk_document(file_text)

    response = client.embeddings.create(
        input=file_chunks, model="text-embedding-3-small"
    )

    embeddings = [item.embedding for item in response.data]

    upload_embeddings(file_chunks, embeddings, document_id, organization_id)


def chunk_document(text: str) -> list[str]:

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
