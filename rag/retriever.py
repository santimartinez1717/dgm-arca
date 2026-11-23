"""Retrieval: similarity search, keyword search (BM25) and the hybrid of both.

``BM25Retriever`` is complete: it is the keyword baseline you compare against.
``DenseRetriever`` and ``HybridRetriever`` are yours. All three return the same ``Hit``
objects so that ``rag/generate.py`` and ``rag/evaluate.py`` do not care which one is used.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rag.chunking import Chunk
from rag.embed import DEFAULT_QUERY_INSTRUCTION


@dataclass
class Hit:
    chunk: Chunk
    score: float


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


class BM25Retriever:
    """Keyword ranking: term frequency, inverse document frequency, length normalisation."""

    name = "bm25"

    def __init__(self, chunks: list[Chunk]):
        from rank_bm25 import BM25Okapi

        self.chunks = chunks
        self.index = BM25Okapi([tokenize(c.text) for c in chunks])

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        scores = self.index.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [Hit(self.chunks[i], float(scores[i])) for i in order]


class DenseRetriever:
    """Cosine similarity between the query (with instruction) and every chunk embedding.

    The chunk matrix is a plain NumPy array saved under ``persist_dir`` with a name that
    depends on the embedding model and on every chunk id and text: a new chunking gets its
    own file, and the same chunking is never embedded twice.
    """

    name = "dense"

    def __init__(
        self,
        chunks: list[Chunk],
        embedder,
        persist_dir: str | Path = "rag/index",
        instruction: str | None = DEFAULT_QUERY_INSTRUCTION,
    ):
        self.chunks, self.embedder, self.instruction = chunks, embedder, instruction
        self.path = Path(persist_dir) / f"{index_key(chunks, embedder.model_id)}.npy"
        if self.path.exists():
            self.matrix = np.load(self.path)
        else:
            self.matrix = np.asarray(
                embedder.embed_passages([c.text for c in chunks]), dtype=np.float32
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            np.save(self.path, self.matrix)
        if len(self.matrix) != len(chunks):
            raise ValueError(f"{self.path} has {len(self.matrix)} rows for {len(chunks)} chunks")

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        return self.search_many([query], top_k)[0]

    def search_many(self, queries: list[str], top_k: int = 5) -> list[list[Hit]]:
        """One batched embedding call for many queries (the evaluation uses it)."""
        vectors = np.asarray(self.embedder.embed_queries(queries, self.instruction))
        scores = vectors @ self.matrix.T
        results = []
        for row in scores:
            order = np.argsort(-row)[:top_k]
            results.append([Hit(self.chunks[i], float(row[i])) for i in order])
        return results


def index_key(chunks: list[Chunk], model_id: str) -> str:
    digest = hashlib.sha1(model_id.encode())
    for chunk in chunks:
        digest.update(f"\0{chunk.id}\0{chunk.text}".encode())
    return f"{model_id.split('/')[-1]}-{len(chunks)}-{digest.hexdigest()[:12]}"


def minmax(hits: list[Hit]) -> dict[str, float]:
    """Scores rescaled to [0, 1] within the list (all 1.0 if they are equal)."""
    if not hits:
        return {}
    scores = [h.score for h in hits]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    return {h.chunk.id: (h.score - lo) / span if span else 1.0 for h in hits}


def fuse(bm25_hits: list[Hit], dense_hits: list[Hit], weight_bm25: float, top_k: int) -> list[Hit]:
    """λ · s_bm25 + (1 - λ) · s_dense on min-max scores; a chunk missing from a list scores 0."""
    s_bm25, s_dense = minmax(bm25_hits), minmax(dense_hits)
    chunks = {h.chunk.id: h.chunk for h in [*bm25_hits, *dense_hits]}
    fused = {
        cid: weight_bm25 * s_bm25.get(cid, 0.0) + (1 - weight_bm25) * s_dense.get(cid, 0.0)
        for cid in chunks
    }
    order = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:top_k]
    return [Hit(chunks[cid], fused[cid]) for cid in order]


class HybridRetriever:
    """s_hybrid = λ · s_bm25 + (1 - λ) · s_dense, on scores rescaled to [0, 1].

    Takes the top ``pool`` hits from each retriever, min-max normalises each list, merges
    by chunk id and returns the top ``top_k``. λ (``weight_bm25``) is chosen with
    ``rag/evaluate.py`` on the gold set.
    """

    name = "hybrid"

    def __init__(
        self, bm25: BM25Retriever, dense: DenseRetriever, weight_bm25: float = 0.5, pool: int = 20
    ):
        self.bm25, self.dense, self.weight_bm25, self.pool = bm25, dense, weight_bm25, pool

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        pool = max(self.pool, top_k)
        return fuse(
            self.bm25.search(query, pool), self.dense.search(query, pool), self.weight_bm25, top_k
        )
