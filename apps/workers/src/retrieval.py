import os
import openai
import cohere
from uuid import UUID
from collections.abc import Sequence
from typing import Any, TypedDict, cast
from contextlib import contextmanager
from sqlmodel import select, tuple_

from logutil import get_logger
from database.models import Document, DocumentChunk
from database.session import get_db

logger = get_logger(__name__)

client = openai.Client()
cohere_client = cohere.Client(os.environ["COHERE_API_KEY"])
RERANK_MODEL = "rerank-english-v3.0"


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
    response = client.embeddings.create(input=query, model="text-embedding-3-small")

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

    rerank_response = cohere_client.rerank(
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
    Fetch the top-5 most semantically similar chunks to *vector*, together
    with their immediate predecessor/successor neighbours and the parent
    ``Document`` records — all in a single database session.

    Adjacent chunks are *merged* (prepended / appended) to their parent
    initial chunk so that the downstream re-ranker sees a wider window of
    context around each hit.

    Parameters
    ----------
    vector : list[float]
        Query embedding vector (1536 floats for ``text-embedding-3-small``).

    Returns
    -------
    list[ParentChunk]
        Up to 5 ``ParentChunk`` entries (one per vector-similarity hit),
        each containing the parent ``Document`` and the chunk text with
        adjacent neighbours merged in.
    """
    with contextmanager(get_db)() as db:
        # Cast to ``Any`` to satisfy the type checker — SQLModel / SQLAlchemy
        # column attributes don't natively expose ``cosine_distance``.
        embedding_col = cast(Any, DocumentChunk.embedding)

        # 1. Top-5 most similar chunks (ANN / exact nearest-neighbour)
        initial_chunks = db.exec(
            select(DocumentChunk)
            .order_by(embedding_col.cosine_distance(vector))
            .limit(5)
        ).all()

        logger.debug("Vector search: initial_chunks=%d", len(initial_chunks))

        if not initial_chunks:
            logger.info("No chunks found for the given query vector")
            return []

        # 2. Pre-fetch documents for all initial chunks so that we don't
        #    need a second DB round-trip later in ``query_documents``.
        doc_ids = {c.document_id for c in initial_chunks}
        id_col = cast(Any, Document.id)
        doc_map = {
            d.id: d for d in db.exec(select(Document).where(id_col.in_(doc_ids))).all()
        }
        logger.debug("Pre-fetched %d documents for chunk parents", len(doc_map))

        # 3. Build a map of ``(doc_id, chunk_index) -> ParentChunk`` and
        #    collect the neighbour positions we need to fetch.
        target_pairs: list[tuple[UUID, int]] = []
        initial_chunk_map: dict[tuple[UUID, int], ParentChunk] = {}

        for chunk in initial_chunks:
            # Request the immediate predecessor and successor
            target_pairs.append((chunk.document_id, chunk.chunk_index - 1))
            target_pairs.append((chunk.document_id, chunk.chunk_index + 1))
            initial_chunk_map[(chunk.document_id, chunk.chunk_index)] = {
                "document": doc_map[chunk.document_id],
                "chunk_content": chunk.content,
            }

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
    # This is an edge case that should be vanishingly rare in practice.
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
    print(
        [
            {"key": doc["document"].s3_key, "relevance": doc["relevance"]}
            for doc in query_documents("money")
        ]
    )
