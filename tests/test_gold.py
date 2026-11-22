"""The gold set is annotated by section and quote and resolved to chunk ids per chunking."""

import pytest

from rag.chunking import Chunk
from rag.gold import locate, resolve
from rag.ingest import Document

TEXT = """# Ley

### Artículo 9. Plazo mínimo.

1. La duración será de cinco años.

### Artículo 9 bis. Plazo temporal.

1. La duración será de doce meses.

### Artículo 10. Prórroga.

1. La duración será de cinco años.
"""
DOC = Document(id="d", source="boe/ley.md", text=TEXT)


def chunks_of(*pieces: str) -> list[Chunk]:
    return [Chunk(f"d-{i:04d}", "d", DOC.source, p, i) for i, p in enumerate(pieces)]


def test_section_disambiguates_a_repeated_quote():
    docs = {DOC.source: DOC}
    quote = "La duración será de cinco años."
    with pytest.raises(ValueError, match="ambiguous"):
        locate({"source": DOC.source, "quote": quote}, docs)
    _, start_9, _ = locate({"source": DOC.source, "section": "Artículo 9", "quote": quote}, docs)
    _, start_10, _ = locate({"source": DOC.source, "section": "Artículo 10", "quote": quote}, docs)
    assert start_9 < start_10


def test_section_does_not_confuse_article_9_with_9_bis():
    docs = {DOC.source: DOC}
    with pytest.raises(ValueError, match="not found"):
        locate({"source": DOC.source, "section": "Artículo 9", "quote": "doce meses"}, docs)
    assert locate({"source": DOC.source, "section": "Artículo 9 bis", "quote": "doce meses"}, docs)


def test_quote_must_be_literal():
    with pytest.raises(ValueError, match="not found"):
        locate({"source": DOC.source, "quote": "seis años"}, {DOC.source: DOC})


def test_resolve_follows_the_chunking():
    item = {"id": "q", "question": "?", "evidence": [{"source": DOC.source, "quote": "doce meses"}]}
    whole = resolve([item], [DOC], chunks_of(TEXT))
    assert whole[0]["relevant_chunk_ids"] == ["d-0000"]
    articles = TEXT.split("### ")
    split = resolve([item], [DOC], chunks_of(*(a for a in articles if a.strip())))
    assert split[0]["relevant_chunk_ids"] == ["d-0002"]


def test_quote_whole_in_two_overlapping_chunks_counts_both():
    item = {"id": "q", "question": "?", "evidence": [{"source": DOC.source, "quote": "doce meses"}]}
    start = TEXT.index("doce meses")
    left, right = TEXT[: start + 30], TEXT[start - 20 :]
    resolved = resolve([item], [DOC], chunks_of(left, right))
    assert resolved[0]["relevant_chunk_ids"] == ["d-0000", "d-0001"]


def test_quote_split_between_chunks_keeps_the_larger_share():
    quote = "La duración será de doce meses."
    item = {"id": "q", "question": "?", "evidence": [{"source": DOC.source, "quote": quote}]}
    cut = TEXT.index(quote) + 8  # "La durac" | "ión será de doce meses."
    resolved = resolve([item], [DOC], chunks_of(TEXT[:cut], TEXT[cut:]))
    assert resolved[0]["relevant_chunk_ids"] == ["d-0001"]
