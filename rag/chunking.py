"""Data indexing, step 2: chunking.

Two strategies from class. ``recursive_chunks`` is the default of most RAG systems and is
implemented for you with LangChain's splitter. ``semantic_chunks`` is yours to write: the
algorithm is in the docstring and in the slides. Compare both with ``rag/evaluate.py``:
number of chunks, average length, and Recall@k on your gold set.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rag.ingest import Document


@dataclass
class Chunk:
    id: str
    doc_id: str
    source: str
    text: str
    index: int  # position of the chunk within its document


def recursive_chunks(
    documents: list[Document],
    chunk_size: int = 800,
    chunk_overlap: int = 100,
    separators: tuple[str, ...] = ("\n\n", "\n", ". ", " ", ""),
) -> list[Chunk]:
    """Split by paragraphs, then lines, then sentences... until every chunk fits ``chunk_size``."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        separators=list(separators),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )
    chunks = []
    for doc in documents:
        for i, piece in enumerate(splitter.split_text(doc.text)):
            chunks.append(
                Chunk(id=f"{doc.id}-{i:04d}", doc_id=doc.id, source=doc.source, text=piece, index=i)
            )
    return chunks


def split_sentences(text: str) -> list[str]:
    """Cheap sentence splitter; good enough to feed the semantic chunker."""
    sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
    return [s.strip() for s in sentences if s and s.strip()]


def split_long(sentences: list[str], max_chars: int) -> list[str]:
    """Cut sentences longer than ``max_chars`` at spaces (BOE table rows can be 16k chars)."""
    out = []
    for sentence in sentences:
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            out.append(sentence)
    return out


def consecutive_distances(embeddings) -> np.ndarray:
    """Cosine distance 1 - e_i · e_{i+1} between consecutive L2-normalised rows."""
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if len(embeddings) < 2:
        return np.zeros(0, dtype=np.float32)
    return 1.0 - np.sum(embeddings[:-1] * embeddings[1:], axis=1)


def semantic_chunks(
    documents: list[Document],
    embed_fn,
    distance_threshold: float = 0.25,
    max_chunk_chars: int = 1500,
) -> list[Chunk]:
    """Group consecutive sentences while their embeddings stay close.

    ``embed_fn(list[str]) -> array of shape (n, d)`` with L2-normalised rows (see
    ``rag/embed.py``). The algorithm from the slides:

    1. Split the document into sentences s_1 … s_n.
    2. Embed them: e_1 … e_n.
    3. Start the first chunk with s_1.
    4. For each consecutive pair, compute the cosine distance 1 - e_i · e_{i+1}.
    5. If the distance is <= threshold, append s_{i+1} to the current chunk.
    6. Otherwise close the chunk and start a new one at s_{i+1}.
    7. Also close a chunk when it would exceed ``max_chunk_chars``.

    One addition: sentences longer than ``max_chunk_chars`` (rows of the BOE tables) are cut
    at spaces first, so that no chunk exceeds the limit.
    """
    chunks = []
    for doc in documents:
        sentences = split_long(split_sentences(doc.text), max_chunk_chars)
        if not sentences:
            continue
        distances = consecutive_distances(embed_fn(sentences))
        groups, current, size = [], [sentences[0]], len(sentences[0])
        for sentence, distance in zip(sentences[1:], distances, strict=True):
            if distance > distance_threshold or size + 1 + len(sentence) > max_chunk_chars:
                groups.append(current)
                current, size = [sentence], len(sentence)
            else:
                current.append(sentence)
                size += 1 + len(sentence)
        groups.append(current)
        for i, group in enumerate(groups):
            chunks.append(
                Chunk(
                    id=f"{doc.id}-{i:04d}",
                    doc_id=doc.id,
                    source=doc.source,
                    text=" ".join(group),
                    index=i,
                )
            )
    return chunks


class SentenceCache:
    """Embeds every sentence of the corpus once, cached on disk, and serves as ``embed_fn``.

    Semantic chunking needs one embedding per sentence (~12k in our corpus): without the
    cache, every start of the API and every threshold tried would embed them again.
    """

    def __init__(self, documents, embedder, max_chars: int, index_dir: str | Path):
        self.per_doc = {d.id: split_long(split_sentences(d.text), max_chars) for d in documents}
        unique = sorted({s for sentences in self.per_doc.values() for s in sentences})
        key = hashlib.sha1((embedder.model_id + "\0" + "\0".join(unique)).encode()).hexdigest()
        path = Path(index_dir) / f"sentences-{len(unique)}-{key[:12]}.npy"
        if path.exists():
            matrix = np.load(path)
        else:
            print(f"embedding {len(unique):,} sentences...", flush=True)
            matrix = np.asarray(embedder.embed_passages(unique), dtype=np.float32)
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, matrix)
        self.row = {s: i for i, s in enumerate(unique)}
        self.matrix = matrix

    def __call__(self, sentences: list[str]) -> np.ndarray:
        return self.matrix[[self.row[s] for s in sentences]]

    def all_distances(self) -> np.ndarray:
        parts = [consecutive_distances(self(s)) for s in self.per_doc.values() if len(s) > 1]
        return np.concatenate(parts)


def describe(chunks: list[Chunk]) -> dict[str, float]:
    """Numbers for your chunking comparison table."""
    lengths = [len(c.text) for c in chunks]
    return {
        "n_chunks": len(chunks),
        "mean_chars": sum(lengths) / max(len(lengths), 1),
        "min_chars": min(lengths, default=0),
        "max_chars": max(lengths, default=0),
    }
