"""Rewards of the real-estate domain for GRPO.

Same signature as ``rlm/rewards.py``: ``reward_fn(prompts, completions, **kwargs)``, where
``kwargs`` holds the extra columns of the dataset (``answer``, ``unit``, ``tolerance_abs``,
``tolerance_rel``, ``checkpoints``), one value per completion.

* ``euro_accuracy_reward`` replaces the generic accuracy reward: the generic one reads
  ``208.850,00`` as 208.85 and ``1.050`` as 1.05, which in Spanish are wrong.
* ``breakdown_reward`` is our third, domain-specific reward ("desglose trazable"), justified
  in ``docs/propuesta.md``: half a point for answering with the right unit, half a point for
  the share of intermediate values (tax base, depreciation, rent cap…) that appear in the
  reasoning, only when the final answer is correct.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from rlm.rewards import _completion_text, extract_answer, numbers_match
from rlm.verifier import EuroVerifier, amounts_in

THINK_BLOCK = re.compile(r"<think>(?P<think>.*?)</think>", re.DOTALL)
EURO_UNIT = re.compile(r"€|\beur(?:o|os)?\b", re.IGNORECASE)
PCT_UNIT = re.compile(r"%|\bpor ?ciento\b", re.IGNORECASE)
# The student reasons in English and writes "240,700 €" or "17,164.80": ``amounts_in`` follows
# the Spanish convention and reads those as 240.7 and 17.1648. Both readings are kept.
ENGLISH_GROUPED = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
AMOUNT_WITH_UNIT = re.compile(
    r"(?P<num>-?\d[\d.,]*\d|\d)\s*(?P<unit>€|%|eur(?:o|os)?\b|por ?ciento)", re.IGNORECASE
)


def _column(kwargs: dict, name: str, n: int, default):
    values = kwargs.get(name)
    return list(values) if values is not None else [default] * n


def is_correct(completion_text: str, expected: str, tol_abs: float, tol_rel: float) -> bool:
    """Verdict of the domain verifier on a full completion."""
    predicted = extract_answer(completion_text)
    return EuroVerifier(tol_abs, tol_rel).is_correct(predicted, expected)


def euro_accuracy_reward(
    prompts: Sequence, completions: Sequence, answer: Sequence[str], **kwargs
) -> list[float]:
    """1.0 when the ``<answer>`` block holds the right amount within the row's tolerance.

    Rows without ``unit`` are the GSM8K control group, written in English convention
    ("1,234" is one thousand two hundred thirty-four there): they use the generic check.
    """
    n = len(completions)
    units = _column(kwargs, "unit", n, None)
    tol_abs = _column(kwargs, "tolerance_abs", n, 0.01)
    tol_rel = _column(kwargs, "tolerance_rel", n, 0.0)
    rewards = []
    for c, expected, unit, ta, tr in zip(completions, answer, units, tol_abs, tol_rel, strict=True):
        text = _completion_text(c)
        if unit is None:
            ok = numbers_match(extract_answer(text), expected)
        else:
            ok = is_correct(text, expected, ta, tr)
        rewards.append(1.0 if ok else 0.0)
    return rewards


def unit_ok(answer_text: str | None, unit: str) -> bool:
    """The answer states the unit the question asked for, and not the other one."""
    if not answer_text:
        return False
    has_eur = EURO_UNIT.search(answer_text) is not None
    has_pct = PCT_UNIT.search(answer_text) is not None
    return (has_eur and not has_pct) if unit == "eur" else (has_pct and not has_eur)


def readings(text: str) -> list[float]:
    """Every number in the text, in Spanish convention plus the English one for "1,234.5"."""
    english = [float(token.replace(",", "")) for token in ENGLISH_GROUPED.findall(text)]
    return amounts_in(text) + english


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.011, 0.0005 * abs(b))


def unit_stated(text: str, answer_text: str | None, unit: str) -> bool:
    """The final figure is given with the unit the question asked for, and not the other one.

    Either inside ``<answer>`` or next to that same figure anywhere in the completion. The
    distilled traces put a bare number in ``<answer>`` and close the reasoning with "The
    answer is 17,164.80 €", so the answer block alone never carried a unit after SFT.
    """
    if unit_ok(answer_text, unit):
        return True
    targets = readings(answer_text or "")
    if not targets:
        return False
    for match in AMOUNT_WITH_UNIT.finditer(text):
        if any(_close(v, t) for v in readings(match.group("num")) for t in targets):
            stated = "eur" if EURO_UNIT.fullmatch(match.group("unit")) else "pct"
            if stated == unit:
                return True
    return False


def checkpoint_coverage(thinking: str, checkpoints: Sequence[float], tol: float = 0.01) -> float:
    """Share of intermediate values that appear (to the cent) somewhere in the reasoning."""
    if not checkpoints:
        return 0.0
    seen = readings(thinking)
    hits = sum(1 for target in checkpoints if any(abs(v - target) <= tol for v in seen))
    return hits / len(checkpoints)


EQUALS_BEFORE = re.compile(r"(=|≈)\s*\S{0,3}\s*$")
# "0.03 × 293,000 gives 4,274.35" computes; "the depreciation is 4,274.35" only quotes.
VERB_BEFORE = re.compile(r"\b(gives?|is|are|equals?|makes|comes to|results? in)\s*\S{0,3}\s*$")
OPERATION = re.compile(
    r"\d\s*(×|\*|/|÷|\+|-|−|x)\s*\(?\d"
    r"|\b(multiplied by|times|divided by|minus|plus|subtracting|adding)\s+\(?\d",
    re.IGNORECASE,
)
NUMBER = re.compile(r"[-−]?\d[\d.,]*")


def derived_share(thinking: str, row: dict) -> float:
    """Share of the key's intermediate values that the reasoning *computes*, not just quotes.

    A value counts when it appears right after an "=" or "≈", or after "gives", "is"… preceded
    by an arithmetic operation, somewhere in the reasoning, within
    0.5 % (computed by hand, a mortgage payment can be off by a few cents and still lead to
    the right answer). Values already in the statement (a tax base equal to the price) are
    skipped. Calibrated on the unprivileged verified traces: 77-99 % of them pass, by family.
    """
    targets = [
        v
        for v in row.get("checkpoints") or []
        if not any(abs(r - v) <= 0.01 for r in readings(row["question"]))
    ]
    if not targets:
        return 1.0
    derived = set()
    for match in NUMBER.finditer(thinking):
        before = thinking[max(0, match.start() - 60) : match.start()]
        computed = EQUALS_BEFORE.search(before[-14:]) or (
            VERB_BEFORE.search(before) and OPERATION.search(before)
        )
        if not computed:
            continue
        for value in readings(match.group(0).replace("−", "-")):
            derived.update(
                i for i, t in enumerate(targets) if abs(value - t) <= max(0.01, 0.005 * abs(t))
            )
    return len(derived) / len(targets)


def breakdown_reward(
    prompts: Sequence,
    completions: Sequence,
    answer: Sequence[str],
    gate_on_correct: bool = True,
    **kwargs,
) -> list[float]:
    """0.5 · unit of the final figure + 0.5 · checkpoint coverage (gated on a correct answer).

    With ``gate_on_correct=False`` the checkpoint part gives partial credit to wrong answers
    that got the intermediate steps right: a process reward. Comparing both is one of our
    ablations. Rows without ``unit`` (e.g. the GSM8K control group) get 0.0.
    """
    n = len(completions)
    units = _column(kwargs, "unit", n, None)
    checkpoints = _column(kwargs, "checkpoints", n, [])
    tol_abs = _column(kwargs, "tolerance_abs", n, 0.01)
    tol_rel = _column(kwargs, "tolerance_rel", n, 0.0)
    rewards = []
    for c, expected, unit, cps, ta, tr in zip(
        completions, answer, units, checkpoints, tol_abs, tol_rel, strict=True
    ):
        if unit is None:
            rewards.append(0.0)
            continue
        text = _completion_text(c)
        match = THINK_BLOCK.search(text)
        thinking = match.group("think") if match else ""
        score = 0.5 if unit_stated(text, extract_answer(text), unit) else 0.0
        if not gate_on_correct or is_correct(text, expected, ta, tr):
            score += 0.5 * checkpoint_coverage(thinking, cps or [])
        rewards.append(score)
    return rewards


def _prompt_text(prompt) -> str:
    """The user's question in a prompt that is a string or a list of chat messages."""
    if isinstance(prompt, str):
        return prompt
    users = [m.get("content", "") for m in prompt or [] if m.get("role") == "user"]
    return users[-1] if users else ""


def process_reward(
    prompts: Sequence, completions: Sequence, answer: Sequence[str], **kwargs
) -> list[float]:
    """Share of the reference solution's intermediate values that the reasoning computes.

    Step-level credit from the rule engine, given whether the final answer is right or not:
    when all 8 completions of a group are wrong, the one that got the depreciation right still
    scores above the one that skipped it, so GRPO has something to learn from. Three guards
    against gaming it: values already in the statement do not count, a value only counts when
    it follows an "=" or an arithmetic operation (``derived_share``), and an unfinished
    completion (no ``<answer>``) scores 0, so that long reasoning that never ends is not paid.
    Rows without ``unit`` (GSM8K control) get 0.0.
    """
    n = len(completions)
    units = _column(kwargs, "unit", n, None)
    checkpoints = _column(kwargs, "checkpoints", n, [])
    rewards = []
    for prompt, c, unit, cps in zip(prompts, completions, units, checkpoints, strict=True):
        text = _completion_text(c)
        match = THINK_BLOCK.search(text)
        if unit is None or not cps or match is None or extract_answer(text) is None:
            rewards.append(0.0)
            continue
        row = {"checkpoints": list(cps), "question": _prompt_text(prompt)}
        rewards.append(derived_share(match.group("think"), row))
    return rewards


def verify_row(completion_text: str, row: dict) -> tuple[bool, str | None]:
    """Verdict for one dataset row, choosing the right check for domain or control rows."""
    predicted = extract_answer(completion_text)
    if row.get("unit") is None:
        return numbers_match(predicted, str(row["answer"])), predicted
    verifier = EuroVerifier(row.get("tolerance_abs", 0.01), row.get("tolerance_rel", 0.0))
    return verifier.is_correct(predicted, str(row["answer"])), predicted
