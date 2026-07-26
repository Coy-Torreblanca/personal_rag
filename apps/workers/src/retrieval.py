import os
import openai
import cohere
from uuid import UUID
from typing import Sequence, TypedDict
from contextlib import contextmanager
from sqlmodel import select, col, tuple_

from database.models import Document, DocumentChunk
from database.session import get_db

client = openai.Client()
cohere_client = cohere.Client(os.environ["COHERE_API_KEY"])
RERANK_MODEL = "rerank-english-v3.0"


class RerankResult(TypedDict):
    chunk: DocumentChunk
    rank: int
    relevance: float


class QueryDocumentResult(TypedDict):
    document: Document
    relevance: float


def _embed_query(query: str) -> list[float]:
    """Get the embedding vector for a query string."""
    response = client.embeddings.create(input=query, model="text-embedding-3-small")
    return response.data[0].embedding


def rerank_docs(query: str, chunks: Sequence[DocumentChunk]) -> list[RerankResult]:

    rerank_response = cohere_client.rerank(
        model=RERANK_MODEL,
        query=query,
        documents=[chunk.content for chunk in chunks],
    )

    results: list[RerankResult] = []
    for hit in rerank_response.results:
        results.append(
            {
                "chunk": chunks[hit.index],
                "rank": hit.index,
                "relevance": hit.relevance_score,
            }
        )

    return results


def _get_chunks(vector: list[float]) -> list[DocumentChunk]:

    with contextmanager(get_db)() as db:
        embedding_col = col(DocumentChunk.embedding)
        initial_chunks = db.exec(
            select(DocumentChunk)
            .order_by(embedding_col.cosine_distance(vector))  # pyright: ignore[reportAttributeAccessIssue]
            .limit(5)
        ).all()

    # Get docid, target chunkindexes

    target_chunks: list[tuple[UUID, int]] = []
    initial_chunk_map: dict[tuple[UUID, int], DocumentChunk] = {}

    for chunk in initial_chunks:
        target_chunks.append((chunk.document_id, chunk.chunk_index - 1))
        target_chunks.append((chunk.document_id, chunk.chunk_index + 1))
        initial_chunk_map[(chunk.document_id, chunk.chunk_index)] = chunk

    with contextmanager(get_db)() as db:
        # Cast to Any to bypass type checker for pgvector's cosine_distance
        # (not recognized on SQLModel Mapped columns)
        embedding_col = col(DocumentChunk.embedding)
        aux_chunks = db.exec(
            select(DocumentChunk).where(
                tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(
                    target_chunks
                )
            )
        ).all()

    for chunk in aux_chunks:
        key = (chunk.document_id, chunk.chunk_index + 1)
        if key in initial_chunk_map:
            initial_chunk = initial_chunk_map[key]
            initial_chunk.content = initial_chunk.content + chunk.content

        else:
            initial_chunk = initial_chunk_map[
                (chunk.document_id, chunk.chunk_index - 1)
            ]
            initial_chunk.content = chunk.content + initial_chunk.content

    return list(initial_chunk_map.values())


def query_documents(query: str) -> list[QueryDocumentResult]:
    """Find documents whose chunks are most semantically similar to the query."""
    vector = _embed_query(query)

    chunks = _get_chunks(vector)

    rerank_results = rerank_docs(query, chunks)

    # Collect unique document IDs from the top matching chunks
    doc_ids_and_relevance: list[tuple[UUID, float]] = []

    unique_ids: set[UUID] = set()

    for result in rerank_results:
        docid = result["chunk"].document_id
        if docid not in unique_ids:
            doc_ids_and_relevance.append((docid, result["relevance"]))
            unique_ids.add(docid)

    if not doc_ids_and_relevance:
        return []

    with contextmanager(get_db)() as db:
        id_col = col(Document.id)
        documents = db.exec(
            select(Document).where(
                id_col.in_([doc_data[0] for doc_data in doc_ids_and_relevance])
            )
        ).all()

    doc_id_map = {doc.id: doc for doc in documents}

    query_document_results: list[QueryDocumentResult] = []

    for id, relevance in doc_ids_and_relevance:
        query_document_results.append(
            {"document": doc_id_map[id], "relevance": relevance}
        )

    return query_document_results


if __name__ == "__main__":
    print(
        [
            {"key": doc["document"].s3_key, "relevance": doc["relevance"]}
            for doc in query_documents("money")
        ]
    )
