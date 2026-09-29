"""Verifier interface for reinforcement learning with verifiable rewards.

A verifier answers one question deterministically: *is this answer correct for
this problem?* Everything in phase 1 hangs on it. If the verifier is sloppy, the
model will learn to exploit the sloppiness instead of learning to reason.

We ship two verifiers:

* ``NumericVerifier`` compares numbers after normalisation. It is what GSM8K needs
  and what the smoke test uses.
* ``ExactMatchVerifier`` compares normalised strings. Useful for multiple-choice
  or short factual answers.

Your domain verifier goes in this module too. Subclass ``Verifier``, implement
``is_correct`` and add a test for it in ``tests/test_verifier.py``. Common shapes:
run unit tests on generated code, execute a SQL query and compare result sets,
validate a JSON document against a schema, check that a date falls in a range.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from rlm.rewards import extract_answer, normalize_number


@dataclass(frozen=True)
class VerificationResult:
    """What a verifier reports back. ``detail`` is free text for logging and debugging."""

    is_correct: bool
    predicted: str | None
    expected: str
    detail: str = ""


class Verifier(ABC):
    """Base class for all verifiers."""

    name: str = "verifier"

    @abstractmethod
    def is_correct(self, predicted: str | None, expected: str) -> bool:
        """Return True when ``predicted`` should be accepted as a correct answer."""

    def verify(self, completion: str, expected: str) -> VerificationResult:
        """Extract the final answer from a full completion and check it."""
        predicted = extract_answer(completion)
        ok = self.is_correct(predicted, expected)
        detail = "no <answer> block found" if predicted is None else ""
        return VerificationResult(ok, predicted, expected, detail)


class NumericVerifier(Verifier):
    """Numeric comparison with an optional absolute tolerance."""

    name = "numeric"

    def __init__(self, tolerance: float = 0.0):
        self.tolerance = tolerance

    def is_correct(self, predicted: str | None, expected: str) -> bool:
        if predicted is None:
            return False
        p, e = normalize_number(predicted), normalize_number(expected)
        if p is None or e is None:
            return False
        if self.tolerance == 0.0:
            return p == e
        return abs(float(p) - float(e)) <= self.tolerance


class ExactMatchVerifier(Verifier):
    """Case- and whitespace-insensitive string comparison."""

    name = "exact_match"

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().lower()

    def is_correct(self, predicted: str | None, expected: str) -> bool:
        if predicted is None:
            return False
        return self._normalize(predicted) == self._normalize(expected)


# --------------------------------------------------------------------------- domain verifier

# A number as people write it in Spanish or English: 1.234,56 · 1,234.56 · 1234,5 · -654.
_AMOUNT = re.compile(r"-?\d[\d.,]*")
_THOUSANDS_DOT = re.compile(r"^[1-9]\d{0,2}(\.\d{3})+$")
_THOUSANDS_COMMA = re.compile(r"^[1-9]\d{0,2}(,\d{3}){2,}$")


def parse_amount(token: str) -> float | None:
    """Parse one number written in Spanish or English convention.

    * Both separators present: the last one is the decimal mark
      (``208.850,00`` and ``208,850.00`` are both 208850).
    * Only dots: thousands if the groups are exactly three digits after a non-zero lead
      (``1.050`` is one thousand fifty, as in Spanish), decimal otherwise (``4.37``, ``0.375``).
    * Only commas: decimal (``4,37``), unless there are two or more groups of three
      (``1,050,000``).
    """
    token = token.strip().rstrip(".,")
    negative = token.startswith("-")
    token = token.lstrip("-")
    if not token or not token[0].isdigit():
        return None
    if "." in token and "," in token:
        decimal = "," if token.rfind(",") > token.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        token = token.replace(thousands, "").replace(decimal, ".")
    elif "." in token:
        if _THOUSANDS_DOT.match(token):
            token = token.replace(".", "")
        elif token.count(".") > 1:
            return None
    elif "," in token:
        if _THOUSANDS_COMMA.match(token):
            token = token.replace(",", "")
        elif token.count(",") > 1:
            return None
        else:
            token = token.replace(",", ".")
    try:
        value = float(token)
    except ValueError:
        return None
    return -value if negative else value


def amounts_in(text: str) -> list[float]:
    """Every number in a piece of text, parsed with ``parse_amount``."""
    values = []
    for token in _AMOUNT.findall(text):
        value = parse_amount(token)
        if value is not None:
            values.append(value)
    return values


class EuroVerifier(Verifier):
    """Money and percentage answers of the real-estate domain.

    Accepts Spanish and English number formats, units and words around the figure
    (``"208.850,00 €"``, ``"Necesitas 208850 euros"``, ``"4,37 %"``). The answer must contain
    exactly one *distinct* number: two different candidates ("entre 4,2 y 4,4 %") are
    rejected, so hedging never pays. Tolerance is absolute plus relative, to forgive the
    cent-level drift of rounding intermediate steps.
    """

    name = "euro"

    def __init__(self, tolerance_abs: float = 0.01, tolerance_rel: float = 0.0005):
        self.tolerance_abs = tolerance_abs
        self.tolerance_rel = tolerance_rel

    def is_correct(self, predicted: str | None, expected: str) -> bool:
        if predicted is None:
            return False
        candidates = {round(v, 6) for v in amounts_in(predicted)}
        target = parse_amount(expected)
        if len(candidates) != 1 or target is None:
            return False
        value = candidates.pop()
        return abs(value - target) <= self.tolerance_abs + self.tolerance_rel * abs(target)
