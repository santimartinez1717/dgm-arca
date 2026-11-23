"""Does the rule engine still match the law? An audit of ``rlm/realestate_rules.py`` with the BOE.

The engine (the ground truth of phase 1 and the calculators of phase 2) hard-codes rules
taken from the law in September 2026. Laws change: the RDL 29/2026 rewrote the IRPF rental
reduction a few weeks later, and nobody told the engine. With every version of every article
(``rag/temporal.py``) this script checks, for each rule the engine relies on:

1. whether the article changed between the engine's reference date and today, and by which
   norm;
2. whether the exact text the rule rests on is still in the version in force today;
3. whether a change with a future date is already published (e.g. LIRPF art. 85 in 2027).

    uv run python -m rag.audit_rules            # Markdown table; exit code 1 if a rule broke
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from rag.gold import normalise
from rag.temporal import ArticleVersion, load_versions

ENGINE_DATE = "2026-09-15"  # "Sources, consulted in September 2026" (rlm/realestate_rules.py)


@dataclass(frozen=True)
class Rule:
    name: str  # what the engine does, as in rlm/realestate_rules.py
    law: str
    block_id: str
    quotes: tuple[str, ...]  # text the rule rests on, from the version in force at ENGINE_DATE


RULES = [
    Rule(
        "rental_income_tax: amortización 3 % del mayor de coste y catastral, sin suelo",
        "lirpf",
        "a23",
        ("el 3 por ciento sobre el mayor de los siguientes valores: el coste de adquisición",),
    ),
    Rule(
        "rental_income_tax: amortización (reglamento)",
        "rirpf",
        "a14",
        ("no excedan del resultado de aplicar el 3 por ciento sobre el mayor",),
    ),
    Rule(
        "rental_reduction_pct: 90 % nuevo contrato en zona tensionada con rebaja > 5 %",
        "lirpf",
        "a23",
        (
            "En un 90 por ciento cuando se hubiera formalizado por el mismo arrendador un nuevo "
            "contrato de arrendamiento sobre una vivienda situada en una zona de mercado "
            "residencial tensionado",
        ),
    ),
    Rule(
        "rental_reduction_pct: 70 % primer alquiler en zona tensionada, 18-35 años",
        "lirpf",
        "a23",
        ("En un 70 por ciento cuando no cumpliéndose los requisitos señalados en la letra a)",
         "hubiera alquilado por primera vez la vivienda, siempre que ésta se encuentre situada en "
         "una zona de mercado residencial tensionado"),
    ),
    Rule(
        "rental_reduction_pct: 60 % rehabilitación en los dos años anteriores",
        "lirpf",
        "a23",
        ("En un 60 por ciento cuando, no cumpliéndose los requisitos de las letras anteriores, la "
         "vivienda hubiera sido objeto de una actuación de rehabilitación",),
    ),
    Rule(
        "rental_reduction_pct: 50 % en el resto de casos",
        "lirpf",
        "a23",
        ("En un 50 por ciento, en cualquier otro caso",),
    ),
    Rule(
        "is_large_holder: más de 10 viviendas o 1.500 m²; 5 en zona tensionada",
        "ley-vivienda",
        "a3",
        ("titular de más de diez inmuebles urbanos de uso residencial o una superficie construida "
         "de más de 1.500",
         "hasta aquellos titulares de cinco o más inmuebles"),
    ),
    Rule(
        "legal_rent_cap: +10 % sobre la renta anterior por obras o contrato largo",
        "lau",
        "a17",
        ("en un máximo del 10 por ciento sobre la última renta",),
    ),
    Rule(
        "legal_rent_cap: tope del índice de referencia para grandes tenedores",
        "lau",
        "a17",
        ("no podrá exceder del límite máximo del precio aplicable conforme al sistema de "
         "índices de precios de referencia",),
    ),
    Rule(
        "acquisition_cost: base del ITP = mayor de precio y valor de referencia",
        "trlitpajd",
        "a10",
        ("su valor será el valor de referencia previsto en la normativa reguladora del "
         "catastro inmobiliario",),
    ),
    Rule(
        "acquisition_cost: IVA del 10 % en obra nueva",
        "liva-vivienda",
        "a91",
        ("Se aplicará el tipo del 10 por ciento",
         "Los edificios o partes de los mismos aptos para su utilización como viviendas"),
    ),
]  # fmt: skip


def in_force(versions: list[ArticleVersion], law: str, block: str, on: str):
    return next(
        (v for v in versions if v.law == law and v.block_id == block and v.in_force(on)), None
    )


def audit(versions: list[ArticleVersion], today: str, engine_date: str = ENGINE_DATE) -> list[dict]:
    rows = []
    for rule in RULES:
        then = in_force(versions, rule.law, rule.block_id, engine_date)
        now = in_force(versions, rule.law, rule.block_id, today)
        if then is None or now is None:
            raise ValueError(f"{rule.law} {rule.block_id}: no version in force")
        missing_then = [q for q in rule.quotes if normalise(q) not in normalise(then.text)]
        if missing_then:
            raise ValueError(f"{rule.name}: quote not in the {engine_date} text: {missing_then}")
        missing_now = [q for q in rule.quotes if normalise(q) not in normalise(now.text)]
        future = sorted(
            {
                (span[0], v.amended_by)
                for v in versions
                if v.law == rule.law and v.block_id == rule.block_id
                for span in v.valid
                if span[0] > today
            }
        )
        rows.append(
            {
                "rule": rule.name,
                "article": f"{rule.law} {now.heading.split('.')[0]}",
                "changed": then.id != now.id and then.text != now.text,
                "changed_by": now.amended_by if then.text != now.text else None,
                "changed_on": now.valid[0][0] if then.text != now.text else None,
                "missing_now": missing_now,
                "future_changes": future,
                "status": "ROTA" if missing_now else ("revisar" if then.text != now.text else "ok"),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    from rag.download_corpus import AS_OF

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--today", default=AS_OF)
    parser.add_argument("--engine-date", default=ENGINE_DATE)
    args = parser.parse_args(argv)
    rows = audit(load_versions(), args.today, args.engine_date)
    print(f"Motor de reglas ({args.engine_date}) frente a la ley vigente el {args.today}\n")
    print("| Estado | Regla del motor | Artículo | Cambio desde el motor | Texto que ya no está |")
    print("|---|---|---|---|---|")
    for r in rows:
        change = f"{r['changed_by']} ({r['changed_on']})" if r["changed_by"] else "—"
        if r["future_changes"]:
            change += "; futuro: " + ", ".join(f"{n} ({d})" for d, n in r["future_changes"])
        missing = "; ".join(f"«{q[:60]}…»" for q in r["missing_now"]) or "—"
        print(f"| {r['status']} | {r['rule']} | {r['article']} | {change} | {missing} |")
    broken = sum(r["status"] == "ROTA" for r in rows)
    print(f"\n{broken} reglas rotas, {sum(r['status'] == 'revisar' for r in rows)} por revisar")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
