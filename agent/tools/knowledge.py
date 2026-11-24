"""``search_knowledge_base``: the phase-3 retriever as a tool of the agent.

Same configuration as ``POST /rag`` (semantic chunks p90, hybrid with λ = 0.2, chosen on the
gold set) and the same pipeline object, so the API loads the embedder and the index once.
With a date, the BOE articles in force on that day answer (phase-3 option 1): the agent uses
it when the user's contract was signed under an older version of the law.

Each passage gets a short key ("K1") stored in the case file: a 1.7B model copies "[K2]"
far more reliably than a chunk id (phase 3), and the auditor checks the keys it cites.
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Annotated

from pydantic import Field

from agent.case_file import current
from tool_use.registry import tool

MAX_PASSAGE_CHARS = 900  # a semantic chunk is up to 1500; the head carries the rule


_LOADING = threading.Lock()


def _pipeline():
    # The agent runs each tool in a thread with a timeout. A search that times out while the
    # index is being built keeps building in the background; without the lock every retry
    # started another build of the same index.
    from rag.generate import build_pipeline

    with _LOADING:
        return build_pipeline()


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_PASSAGE_CHARS else text[:MAX_PASSAGE_CHARS] + " […]"


@tool
def search_knowledge_base(
    query: Annotated[str, Field(min_length=3, max_length=300)],
    on_date: date | None = None,
    top_k: Annotated[int, Field(ge=1, le=6)] = 3,
) -> str:
    """Search Spanish housing and tax law (BOE laws, AEAT manual, SERPAVI, stressed zones).

    Use it to justify a rule or a lever with the text of the law, or to answer a legal
    question. Cite the passages you use with their key, e.g. [K2]. It does not compute
    figures: use the calculation tools for numbers.

    Args:
        query: What to look for, as a question in Spanish.
        on_date: Only for a contract signed in the past: the date (YYYY-MM-DD) whose law
            applies. Leave it out for today's law.
        top_k: How many passages to return.
    """
    pipeline = _pipeline()
    if on_date is not None and pipeline.temporal is not None:
        hits = pipeline.temporal.search(query, top_k, mode="hybrid", on=on_date.isoformat())
        header = f"Law in force on {on_date.isoformat()}."
    else:
        hits, on = pipeline.retrieve_dated(query, top_k, "hybrid")
        header = f"Law in force on {on}." if on else "Law in force today."
    if not hits:
        return "No passages found. Say that the knowledge base does not cover it."
    case = current()
    blocks = [header]
    for hit in hits:
        key = case.cite(f"{hit.chunk.source} · {hit.chunk.id}")
        blocks.append(f"[{key}] ({hit.chunk.source})\n{_excerpt(hit.chunk.text)}")
    return "\n\n".join(blocks)
