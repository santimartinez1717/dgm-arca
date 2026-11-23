"""The law that applied on a date: every version of every article, and retrieval filtered by date.

A plain RAG answers with today's text. But which rule applies depends on *when*: a rental
contract signed in 2017 had a three-year minimum term, one signed in 2020 has five; the IRPF
reduction of a contract depends on the year. The BOE consolidated XML keeps every version of
every block (``<version fecha_vigencia=...>``), so we index all of them with the dates they
were in force and, at question time, keep only the versions in force on the question's date.

Version in force on a date ``d`` (the rule ``download_corpus`` already uses for ``--as-of``):
the *last* version, in document order, whose ``fecha_vigencia`` is ``<= d``. Document order
matters: the BOE lists amendments in the order they were made, and a later amendment can
restore an earlier text with an earlier date (a decree-law that Congress repealed) or carry a
date in the future (an IRPF change in force from 2027). Versions without a date are skipped.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from rag.chunking import Chunk

VERSIONS_DIR = Path(__file__).parent / "corpus" / "versions"
FAR_FUTURE = "9999-12-31"


@dataclass
class ArticleVersion:
    law: str  # file name of the law in rag/corpus/boe, e.g. "lau"
    law_title: str
    block_id: str  # BOE block id, e.g. "a17"
    heading: str  # "Artículo 17. Determinación de la renta."
    index: int  # position of this version among the block's versions
    amended_by: str  # BOE id of the norm that wrote this version
    text: str
    valid: list[tuple[str, str]] = field(default_factory=list)  # [from, to) ISO dates

    @property
    def id(self) -> str:
        return f"{self.law}-{self.block_id}-v{self.index}"

    def in_force(self, on: str) -> bool:
        return any(start <= on < end for start, end in self.valid)


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def validity(dates: list[str]) -> list[list[tuple[str, str]]]:
    """For each version (``fecha_vigencia`` as YYYYMMDD, '' if missing), its [from, to) spans.

    On each date the version in force is the last one in list order whose date is <= that
    date; spans are computed over the change points.
    """
    known = sorted({d for d in dates if d})
    spans: list[list[tuple[str, str]]] = [[] for _ in dates]
    for i, start in enumerate(known):
        end = known[i + 1] if i + 1 < len(known) else None
        active = max(j for j, d in enumerate(dates) if d and d <= start)
        span = (_iso(start), _iso(end) if end else FAR_FUTURE)
        current = spans[active]
        if current and current[-1][1] == span[0]:
            current[-1] = (current[-1][0], span[1])  # merge with the previous span
        else:
            current.append(span)
    return spans


def article_versions(xml_text: str, law: str, law_title: str) -> list[ArticleVersion]:
    """Every version of every article (``precepto``) of a consolidated BOE law."""
    from rag.download_corpus import _paragraphs, _render_xml_blocks

    root = ET.fromstring(xml_text)
    out = []
    for block in root.iter("bloque"):
        if block.get("tipo") != "precepto":
            continue
        versions = block.findall("version")
        spans = validity([v.get("fecha_vigencia", "") for v in versions])
        for i, (version, valid) in enumerate(zip(versions, spans, strict=True)):
            lines = _render_xml_blocks(version)
            if not lines or not valid:
                continue  # empty text, or never in force (no date / superseded the same day)
            first = version.find("p")
            is_heading = first is not None and first.get("class") == "articulo"
            heading = lines.pop(0) if is_heading else block.get("titulo", block.get("id"))
            body = "\n".join(_paragraphs(lines)).strip()
            out.append(
                ArticleVersion(
                    law=law,
                    law_title=law_title,
                    block_id=block.get("id", ""),
                    heading=heading,
                    index=i,
                    amended_by=version.get("id_norma", ""),
                    text=f"### {heading}\n\n{body}",
                    valid=valid,
                )
            )
    return out


def save_versions(versions: list[ArticleVersion], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(asdict(v), ensure_ascii=False) for v in versions]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_versions(directory: Path = VERSIONS_DIR) -> list[ArticleVersion]:
    versions = []
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                record["valid"] = [tuple(span) for span in record["valid"]]
                versions.append(ArticleVersion(**record))
    return versions


# ----------------------------------------------------------------------------- chunks


@dataclass
class VersionedChunk(Chunk):
    valid: list[tuple[str, str]] = field(default_factory=list)

    def in_force(self, on: str) -> bool:
        return any(start <= on < end for start, end in self.valid)


def version_chunks(
    versions: list[ArticleVersion], chunk_size: int = 1200, chunk_overlap: int = 150
) -> list[VersionedChunk]:
    """Each version split recursively; every piece carries the version's validity.

    The text starts with the law title and the article heading, so a piece cut from the
    middle of an article still says what it belongs to.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=["\n\n", "\n", ". ", " "]
    )
    chunks = []
    for v in versions:
        header = f"{v.law_title} — {v.heading}"
        body = v.text.split("\n", 2)[-1].strip()  # without the "### heading" line
        for i, piece in enumerate(splitter.split_text(body) or [""]):
            chunks.append(
                VersionedChunk(
                    id=f"{v.id}-{i:02d}",
                    doc_id=v.id,
                    source=f"boe/{v.law}.md#{v.block_id}@{v.valid[0][0]}",
                    text=f"{header}\n{piece}",
                    index=i,
                    valid=v.valid,
                )
            )
    return chunks


# ----------------------------------------------------------------------------- dates

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}  # fmt: skip
_MONTH = "|".join(MONTHS)
FULL_DATE = re.compile(rf"\b(\d{{1,2}}) de ({_MONTH}) (?:de|del) (\d{{4}})\b", re.I)
NUMERIC_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
MONTH_YEAR = re.compile(rf"\b({_MONTH}) (?:de|del) (\d{{4}})\b", re.I)
YEAR = re.compile(r"\b(?:en|el año|del año|año|de|desde|durante) (19[89]\d|20[0-4]\d)\b", re.I)
BEFORE = re.compile(r"\bantes (?:de|del)\s*$", re.I)


def question_date(question: str) -> str | None:
    """ISO date the question is about, or None (then: today).

    "el 3 de marzo de 2022" and "3/3/2022" are exact; "marzo de 2022" is the 15th; a bare
    year ("en 2017") is 1 July. "antes de ..." moves to the day before the date (the 1st of
    the month for "antes de mayo de 2023"). With several dates, the first one mentioned.
    """
    found: list[tuple[int, int, date]] = []  # (start, end, date)
    for m in FULL_DATE.finditer(question):
        found.append((m.start(), m.end(), date(int(m[3]), MONTHS[m[2].lower()], int(m[1]))))
    for m in NUMERIC_DATE.finditer(question):
        found.append((m.start(), m.end(), date(int(m[3]), int(m[2]), int(m[1]))))
    for m in MONTH_YEAR.finditer(question):
        if any(s <= m.start() < e for s, e, _ in found):
            continue  # the month of a full date already found
        day = 1 if BEFORE.search(question[: m.start()]) else 15
        found.append((m.start(), m.end(), date(int(m[2]), MONTHS[m[1].lower()], day)))
    if not found:
        for m in YEAR.finditer(question):
            found.append((m.start(1), m.end(1), date(int(m[1]), 7, 1)))
    if not found:
        return None
    start, _, when = min(found)
    if BEFORE.search(question[:start]):
        when = date.fromordinal(when.toordinal() - 1)
    return when.isoformat()


# ----------------------------------------------------------------------------- gold


def resolve_temporal(gold: list[dict], chunks: list[VersionedChunk], today: str) -> list[dict]:
    """Each dated gold item plus ``relevant_chunk_ids``: the chunks that give the rule that
    applied on the item's date (``today`` if it has none).

    Relevance is by content, not by version id: a chunk of the same article, of any version,
    whose version holds the whole quote and none of the ``absent`` phrases, and that holds
    the quote itself (or one half of it, 20+ characters, when the quote is split between two
    chunks). The paragraph that answers often survives unchanged through
    amendments to other paragraphs, and a version with the same text gives the same answer.
    The quote must be in the version in force on the date: otherwise the item is wrong.
    """
    from rag.gold import normalise

    texts = {c.doc_id: "" for c in chunks}
    for c in chunks:
        texts[c.doc_id] += " " + c.text
    resolved = []
    for item in gold:
        on = item.get("date") or today
        relevant = []
        for evidence in item["evidence"]:
            prefix = f"{evidence['law']}-{evidence['block_id']}-v"
            quote = normalise(evidence["quote"])
            halves = tuple(
                h for h in (quote[: len(quote) // 2], quote[len(quote) // 2 :]) if len(h) >= 20
            )
            absent = [normalise(a) for a in evidence.get("absent", [])]
            article = [c for c in chunks if c.doc_id.startswith(prefix)]
            in_force = [c for c in article if c.in_force(on)]
            if not in_force:
                raise ValueError(f"{item['id']}: no version of {prefix[:-2]} in force on {on}")

            def gives_rule(c: VersionedChunk, quote=quote, halves=halves, absent=absent) -> bool:
                version = normalise(texts[c.doc_id])
                if quote not in version or any(a in version for a in absent):
                    return False  # this version does not state the rule
                text = normalise(c.text)  # the quote may be split between two chunks
                return quote in text or any(h in text for h in halves)

            if not any(gives_rule(c) for c in in_force):
                raise ValueError(f"{item['id']}: quote not in the version in force on {on}")
            relevant += [c.id for c in article if gives_rule(c)]
        resolved.append(item | {"relevant_chunk_ids": relevant, "on": on})
    return resolved


# ----------------------------------------------------------------------------- retrieval


class DateFilteredRetriever:
    """BM25, dense or hybrid over: the non-BOE chunks of the normal index (AEAT, resolutions,
    PDFs) plus the article versions in force on the question's date.

    ``search(question, top_k, mode)`` reads the date from the question (``question_date``);
    without one it uses ``today``. The date used is kept in ``last_date`` for the response.
    """

    def __init__(self, static_chunks, static_dense, versions_dense, today: str, weight_bm25: float):
        import numpy as np

        self.static = [c for c in static_chunks if not c.source.startswith("boe/")]
        rows = [i for i, c in enumerate(static_chunks) if not c.source.startswith("boe/")]
        self.static_matrix = static_dense.matrix[rows]
        self.versions = versions_dense.chunks
        self.versions_matrix = versions_dense.matrix
        self.embedder, self.instruction = static_dense.embedder, static_dense.instruction
        self.today, self.weight_bm25 = today, weight_bm25
        self._bm25: dict[str, object] = {}
        self._np = np
        self.last_date = today

    def candidates(self, on: str) -> tuple[list[Chunk], object]:
        np = self._np
        mask = [c.in_force(on) for c in self.versions]
        chunks = self.static + [c for c, keep in zip(self.versions, mask, strict=True) if keep]
        matrix = np.vstack([self.static_matrix, self.versions_matrix[np.array(mask)]])
        return chunks, matrix

    def search(self, query: str, top_k: int = 5, mode: str = "hybrid", on: str | None = None):
        from rag.retriever import BM25Retriever, Hit, fuse

        np = self._np
        on = on or question_date(query) or self.today
        self.last_date = on
        chunks, matrix = self.candidates(on)
        pool = max(20, top_k)
        hits = {}
        if mode in ("dense", "hybrid"):
            q = np.asarray(self.embedder.embed_queries([query], self.instruction))[0]
            scores = matrix @ q
            order = np.argsort(-scores)[:pool]
            hits["dense"] = [Hit(chunks[i], float(scores[i])) for i in order]
        if mode in ("bm25", "hybrid"):
            if on not in self._bm25:
                self._bm25[on] = BM25Retriever(chunks)
            hits["bm25"] = self._bm25[on].search(query, pool)
        if mode == "hybrid":
            return fuse(hits["bm25"], hits["dense"], self.weight_bm25, top_k)
        return hits[mode][:top_k]
