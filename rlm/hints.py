"""Hints for GRPO on the families where the SFT model never gets a right answer.

GRPO learns only from groups with some right and some wrong answers. After SFT 2, sampling
8 answers on 8 irpf_rental and 8 cash_on_cash problems gave 0 right answers out of 64 for each
family (``reports/sample_check_sft2.json``): no signal. Following hint-scaffolded GRPO
(Scaf-GRPO, Guide-GRPO), part of those problems are shown with a hint appended to the
question, so the group has some right answers to learn from; the plain versions stay in the
dataset, and a second stage without hints checks that the model no longer needs them.

Level 1 states the method (the rules the model gets wrong); level 2 also gives the first
intermediate value computed by the rule engine and, for irpf_rental, the reduction that
applies. In the SFT 3 evaluation (2026-11-18), irpf_rental answers that finished picked the
wrong reduction in 15 of 28 cases and miscomputed the depreciation in 19 of 28 (mostly the
land share: 1 - 114,500 / 201,000 written as 0.463 instead of 0.430). The hints are in
Spanish, like the questions.
"""

from __future__ import annotations

import random

METHOD = {
    "irpf_rental": (
        "Pista: antes de aplicar la reducción hay que restar a los ingresos todos los gastos "
        "deducibles, incluida la amortización del inmueble: el 3 % del mayor entre el coste "
        "total de adquisición y el valor catastral, aplicado solo a la parte de construcción "
        "(sin el suelo, según el reparto del valor catastral). Los intereses más las "
        "reparaciones no pueden superar los ingresos. La reducción solo se aplica si el "
        "rendimiento neto es positivo, y es la primera que se cumpla: 90 % si está en zona "
        "tensionada, ya estuvo alquilada y la renta bajó más de un 5 %; 70 % si es el primer "
        "alquiler en zona tensionada a un inquilino de 18 a 35 años, o si el inquilino es una "
        "administración o entidad sin ánimo de lucro para alquiler social; 60 % si se terminó "
        "una rehabilitación en los dos años anteriores; 50 % en los demás casos."
    ),
    "cash_on_cash": (
        "Pista: la cuota mensual de la hipoteca sigue el sistema francés, "
        "cuota = P·i / (1 − (1 + i)^(−n)), con i = tipo anual / 12 y n = años · 12; "
        "redondéala a céntimos. El flujo de caja anual es el resultado neto de explotación "
        "menos 12 cuotas, y se divide entre el dinero propio aportado (inversión total menos "
        "el préstamo)."
    ),
}
FIRST_VALUE = {
    "irpf_rental": "La amortización del inmueble sale {value} €.",
    "cash_on_cash": "La cuota mensual de la hipoteca sale {value} €.",
}


def spanish_amount(value: float) -> str:
    """1234.5 -> '1.234,50', the format the questions use."""
    return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def hint_text(row: dict, level: int) -> str:
    """The hint for one problem, or '' if its family has none."""
    family = row.get("family")
    if family not in METHOD or level < 1:
        return ""
    text = METHOD[family]
    if level >= 2 and row.get("checkpoints"):
        text += " " + FIRST_VALUE[family].format(value=spanish_amount(row["checkpoints"][0]))
        reduction = (row.get("branches") or {}).get("reduction")
        if family == "irpf_rental" and reduction and reduction != "0":
            text += f" La reducción que corresponde es del {reduction} %."
    return text


def add_hints(
    rows: list[dict], families: list[str], share: float, level: int, seed: int = 0
) -> list[dict]:
    """Return ``rows`` plus a hinted copy of a ``share`` of the problems of ``families``.

    The plain problems are kept: the model must also see them without help. Hinted copies get
    ``hint_level`` so the training log can tell them apart.
    """
    rng = random.Random(seed)
    out = [dict(r, hint_level=0) for r in rows]
    for row in rows:
        if row.get("family") in families and rng.random() < share:
            hinted = dict(row, hint_level=level)
            hinted["question"] = f"{row['question']}\n\n{hint_text(row, level)}"
            out.append(hinted)
    return out
