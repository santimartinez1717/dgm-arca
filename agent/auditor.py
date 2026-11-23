"""The auditor: a deterministic check of the final answer before it reaches the user.

The rule is *grounding*: every figure in the answer must have been seen before, in the
user's task, in a tool observation or in the case file's engine figures. A number the model
worked out in its head (the phase-1 failure mode: arithmetic and remembered rules) is
rejected and goes back to the loop as an observation, so the model has to ask the engine.
Every ``[K3]`` citation must be a key ``search_knowledge_base`` gave to a passage of this
case (the phase-3 citation check). The mandatory disclaimer is appended if the model forgot it:
that needs no model, so it costs no step.

Small bare integers (counts, article numbers, months) and years are not checked: they are
not the figures an investor acts on, and checking them would reject honest answers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel, Field

DISCLAIMER = (
    "Análisis orientativo hecho con datos sintéticos y las reglas vigentes que conoce el "
    "motor; no es asesoramiento. Consulta a un asesor fiscal antes de decidir."
)

DATE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")
NUMBER = re.compile(
    r"(?<![\w.,])(-?\d{1,3}(?:[.   ]\d{3})+(?:,\d+)?|-?\d+(?:[.,]\d+)?)"
    r"(\s*(?:%|€|eur|euros|por ciento|puntos))?",
    re.IGNORECASE,
)
# "Artículo 669", "Ley 12/2023", "artículos 643 a 675", "RDL 29/2026": the number names the
# law, it is not a figure, and a citation must not make the auditor reject an answer.
LEGAL_REF = re.compile(
    r"\b(?:art[íi]culos?|arts?\.|leyes|ley|real decreto(?:[- ]ley| legislativo)?|"
    r"decreto(?: legislativo)?|rdl|rdleg|dleg|rd)\s+\d+(?:/\d{2,4})?"
    r"(?:\s*(?:,|y|a)\s*\d+(?:/\d{2,4})?)*",
    re.IGNORECASE,
)
CITATION = re.compile(r"\[(K\d+(?:\s*,\s*K\d+)*)\]")


class AuditResult(BaseModel):
    ok: bool
    answer: str
    unsupported_numbers: list[str] = Field(default_factory=list)
    unknown_citations: list[str] = Field(default_factory=list)
    disclaimer_added: bool = False

    def feedback(self) -> str:
        """What the loop shows the model when the answer is rejected."""
        parts = ["AUDIT REJECTED the final answer."]
        if self.unsupported_numbers:
            parts.append(
                "These figures do not come from any tool result or from the user: "
                + ", ".join(self.unsupported_numbers)
                + ". Use only numbers that a tool returned (call analyze_property or what_if "
                "to compute what you need), or remove them."
            )
        if self.unknown_citations:
            parts.append(
                "These citations are not keys of passages returned by search_knowledge_base: "
                + ", ".join(self.unknown_citations)
                + "."
            )
        parts.append("Then call final_answer again.")
        return " ".join(parts)


def parse_number(text: str) -> float | None:
    """Spanish or English notation: 275.000 / 275 000 -> 275000, 4,56 / 4.56 -> 4.56."""
    t = text.replace(" ", " ").replace(" ", " ").strip()
    negative = t.startswith("-")
    t = t.lstrip("-")
    if re.fullmatch(r"\d{1,3}(?:[. ]\d{3})+(?:,\d+)?", t):
        t = re.sub(r"[. ]", "", t).replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):  # 275,000.50
        t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        value = float(t)
    except ValueError:
        return None
    return -value if negative else value


def numbers_in(text: str) -> list[tuple[str, float, bool]]:
    """(as written, value, has_unit) for every number in ``text``, dates and law names removed."""
    text = LEGAL_REF.sub(" ", DATE.sub(" ", text))
    out = []
    for match in NUMBER.finditer(text):
        value = parse_number(match.group(1))
        if value is not None:
            out.append((match.group(0).strip(), value, bool(match.group(2))))
    return out


def _decimals(written: str) -> int:
    match = re.search(r"[.,](\d+)\s*\D*$", written)
    if match and not re.fullmatch(r"\d{3}", match.group(1)):
        return len(match.group(1))
    return 0


def needs_check(written: str, value: float, has_unit: bool) -> bool:
    if has_unit or not float(value).is_integer():
        return True
    v = abs(value)
    if 1900 <= v <= 2100:  # a year
        return False
    return v >= 100


def supported(value: float, written: str, known: Iterable[float]) -> bool:
    """True if ``value`` is some known figure, allowing for the rounding the answer shows."""
    target = abs(value)
    tolerance = 0.5 * 10 ** -_decimals(written) + 1e-9
    for k in known:
        k = abs(k)
        if abs(k - target) <= tolerance or (k and abs(k - target) / k < 0.001):
            return True
        if abs(k * 100 - target) <= tolerance or abs(k / 100 - target) <= tolerance:
            return True  # 0.045 written as 4,5 %, or the other way round
    return False


def audit(
    answer: str,
    sources: Iterable[str],
    figures: Iterable[float] = (),
    retrieved_ids: Iterable[str] = (),
) -> AuditResult:
    """Check ``answer`` against the texts the run has seen and the engine's figures."""
    known = list(figures)
    for text in sources:
        known.extend(value for _, value, _ in numbers_in(text))
    unsupported = []
    for written, value, has_unit in numbers_in(CITATION.sub(" ", answer)):
        if needs_check(written, value, has_unit) and not supported(value, written, known):
            if written not in unsupported:
                unsupported.append(written)
    ids = set(retrieved_ids)
    unknown = []
    for group in CITATION.findall(answer):
        for key in re.split(r"\s*,\s*", group):
            if key not in ids and key not in unknown:
                unknown.append(key)
    final = answer.rstrip()
    added = "asesor" not in final.lower()
    if added:
        final = f"{final}\n\n{DISCLAIMER}"
    return AuditResult(
        ok=not unsupported and not unknown,
        answer=final,
        unsupported_numbers=unsupported,
        unknown_citations=unknown,
        disclaimer_added=added,
    )
