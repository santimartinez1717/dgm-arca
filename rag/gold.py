"""Gold set annotated by article and literal quote, resolved to chunk ids for any chunking.

Chunk ids (``<doc_id>-<index>``) change with the chunking strategy and its parameters, so
``rag/gold/gold.jsonl`` does not store them. Each question stores *where* the answer is:

    {"id": "lau-01",
     "question": "¿...?",
     "answer": "short reference answer",
     "evidence": [{"source": "boe/lau.md", "section": "Artículo 17", "quote": "..."}],
     "notes": "optional"}

``evidence`` lists the places that answer the question, **each one on its own** (usually
one; two when the same fact is stated in two documents, e.g. the law and the AEAT manual).
``section`` is the heading the quote must live under (``Artículo 17`` matches
``### Artículo 17. Determinación de la renta.``); it can be omitted for documents without
articles. ``quote`` is copied literally from the Markdown in ``rag/corpus`` (whitespace is
normalised before matching).

``resolve`` turns every question into ``relevant_chunk_ids`` for a given list of chunks: the
chunks holding at least half of some quote (with overlap, a short quote is often whole in
two consecutive chunks, and either one answers). A question is answered at k when *any* of
its relevant chunks is in the top k.

    uv run python -m rag.gold          # check every quote and show how it maps to chunks
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from rag.chunking import Chunk
from rag.ingest import Document

GOLD_PATH = Path(__file__).parent / "gold" / "gold.jsonl"
MIN_SHARE = 0.5  # a chunk is relevant if it holds at least this share of a quote


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_gold(path: str | Path = GOLD_PATH) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def section_span(text: str, section: str | None) -> tuple[int, int]:
    """Span of the normalised ``text`` under the heading that starts with ``section``.

    The section ends at the next heading of the same or higher level. Headings are matched
    on the raw Markdown and the span is returned in normalised coordinates.
    """
    if not section:
        return 0, len(normalise(text))
    pattern = re.compile(rf"^(#+) {re.escape(section)}(?=\.|[ \t]*$)", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"section {section!r} found {len(matches)} times")
    level = len(matches[0].group(1))
    start = matches[0].start()
    nxt = re.compile(rf"^#{{1,{level}}} ", re.MULTILINE).search(text, matches[0].end())
    end = nxt.start() if nxt else len(text)
    offset = len(normalise(text[:start])) + (1 if start else 0)
    return offset, offset + len(normalise(text[start:end]))


def locate(evidence: dict, documents: dict[str, Document]) -> tuple[str, int, int]:
    """(doc_id, start, end) of the quote in the normalised document text."""
    doc = documents.get(evidence["source"])
    if doc is None:
        raise ValueError(f"unknown source {evidence['source']!r}")
    text = normalise(doc.text)
    lo, hi = section_span(doc.text, evidence.get("section"))
    quote = normalise(evidence["quote"])
    start = text.find(quote, lo, hi)
    if start < 0:
        where = f" under {evidence['section']!r}" if evidence.get("section") else ""
        raise ValueError(f"quote not found in {evidence['source']}{where}: {quote[:60]!r}")
    if text.find(quote, start + 1, hi) >= 0:
        raise ValueError(f"quote is ambiguous in {evidence['source']}: {quote[:60]!r}")
    return doc.id, start, start + len(quote)


def chunk_spans(doc: Document, chunks: list[Chunk]) -> list[tuple[Chunk, int, int]]:
    """Where each chunk of ``doc`` sits in its normalised text (chunks in document order)."""
    text = normalise(doc.text)
    spans, cursor = [], 0
    for chunk in sorted(chunks, key=lambda c: c.index):
        piece = normalise(chunk.text)
        if not piece:
            continue
        start = text.find(piece, cursor)
        if start < 0:
            start = text.find(piece)  # tolerate chunkers that reorder or repeat text
        if start < 0:
            raise ValueError(f"chunk {chunk.id} is not a substring of {doc.source}")
        spans.append((chunk, start, start + len(piece)))
        cursor = start + 1
    return spans


def resolve(gold: list[dict], documents: list[Document], chunks: list[Chunk]) -> list[dict]:
    """Each gold item plus ``relevant_chunk_ids`` for these chunks."""
    by_source = {d.source: d for d in documents}
    by_doc: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.doc_id, []).append(chunk)
    spans_cache: dict[str, list[tuple[Chunk, int, int]]] = {}
    resolved = []
    for item in gold:
        relevant: list[str] = []
        for evidence in item["evidence"]:
            doc_id, q_start, q_end = locate(evidence, by_source)
            if doc_id not in spans_cache:
                doc = by_source[evidence["source"]]
                spans_cache[doc_id] = chunk_spans(doc, by_doc.get(doc_id, []))
            overlaps = [
                (min(end, q_end) - max(start, q_start), chunk.id)
                for chunk, start, end in spans_cache[doc_id]
                if start < q_end and end > q_start
            ]
            needed = MIN_SHARE * (q_end - q_start)
            keep = [cid for size, cid in overlaps if size >= needed]
            if not keep and overlaps:  # quote spread over many small chunks: the largest share
                keep = [max(overlaps)[1]]
            relevant += [cid for cid in keep if cid not in relevant]
        resolved.append(item | {"relevant_chunk_ids": relevant})
    return resolved


def main() -> None:
    import argparse

    from rag.chunking import describe, recursive_chunks
    from rag.ingest import load_corpus

    parser = argparse.ArgumentParser(description="Check the gold set against the corpus.")
    parser.add_argument("--gold", default=str(GOLD_PATH))
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--chunk-overlap", type=int, default=100)
    parser.add_argument("-v", "--verbose", action="store_true", help="one line per question")
    args = parser.parse_args()

    gold = load_gold(args.gold)
    ids = Counter(item["id"] for item in gold)
    if dupes := [i for i, n in ids.items() if n > 1]:
        raise SystemExit(f"duplicated ids: {dupes}")
    documents = load_corpus()
    chunks = recursive_chunks(documents, args.chunk_size, args.chunk_overlap)
    resolved = resolve(gold, documents, chunks)
    print(f"{len(gold)} questions, all quotes found; recursive chunks: {describe(chunks)}")
    sources = Counter(e["source"].split("/")[0] for item in gold for e in item["evidence"])
    print("evidence per folder:", dict(sources))
    n_relevant = Counter(len(item["relevant_chunk_ids"]) for item in resolved)
    print("relevant chunks per question:", dict(sorted(n_relevant.items())))
    if args.verbose:
        for item in resolved:
            print(f"{item['id']:<12} {len(item['relevant_chunk_ids'])}  {item['question'][:70]}")


if __name__ == "__main__":
    main()
