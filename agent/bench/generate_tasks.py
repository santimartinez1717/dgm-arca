"""Synthetic training tasks for the agent, with the expected answer from the engine (issue 18).

The bench (``agent/bench/tasks.jsonl``) is the test set and is never reused: every task here
is drawn from templates with a fixed seed, and a candidate whose price appears anywhere in
the bench is redrawn (``tests/test_generate_tasks.py`` checks it). Expected figures come
from ``agent.analysis.analyze``, the engine behind ``analyze_property`` and ``what_if``, so an
agent that uses its tools reaches the same number.

Five categories with an automatic ``check`` (the format of ``agent/evaluate.py``):

* ``yield``: one flat, the net yield;
* ``cost``: what buying costs with taxes;
* ``legal_rent``: the legal maximum rent in a stressed zone with a previous contract;
* ``inconsistent``: two reference values from two websites, both net yields;
* ``impossible``: a forecast no tool can make, which must be declined without figures.

Run::

    uv run python -m agent.bench.generate_tasks --n 300 --seed 0 --out agent/bench/train_tasks.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any

from agent.analysis import analyze
from agent.bench.build_bench import es, eur
from agent.bench.schema import BENCH
from agent.case_file import InvestorProfile, Property

# Municipalities the engine resolves; the stressed ones keep their declaration past 2028.
TOWNS = ("Valencia", "Sevilla", "Zaragoza", "Málaga", "Murcia", "Alicante", "Valladolid", "Granada")
STRESSED = ("A Coruña", "Pamplona", "Santiago de Compostela")
CATEGORIES = {"yield": 0.3, "cost": 0.2, "legal_rent": 0.2, "inconsistent": 0.2, "impossible": 0.1}

FORECASTS = (
    "¿Cuánto valdrá un piso en {town} en {year}?",
    "¿Va a bajar el alquiler en {town} el año que viene? Dame una cifra.",
    "¿Qué rentabilidad tendrá un piso en {town} dentro de diez años?",
    "¿Subirá el Euríbor en {year}? Necesito saber cuánto pagaré de hipoteca.",
)


def bench_numbers(path: Path = BENCH) -> set[int]:
    """Every integer of three digits or more written in the bench tasks (prices, rents...)."""
    numbers: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        task = json.loads(line)["task"]
        for raw in re.findall(r"\d[\d.]*", task):
            digits = raw.replace(".", "")
            if len(digits) >= 3:
                numbers.add(int(digits))
    return numbers


def _flat(rng: random.Random, taken: set[int], town: str) -> dict[str, Any]:
    while True:
        price = rng.randrange(90_000, 320_000, 500)
        if price not in taken:
            break
    rent = round(price * rng.uniform(0.0042, 0.0062) / 5) * 5
    return {
        "municipality": town,
        "price": float(price),
        "monthly_rent": float(rent),
        "area_m2": float(rng.randrange(45, 110)),
        "ibi": float(rng.randrange(220, 520, 10)),
        "community_monthly": float(rng.randrange(25, 90, 5)),
        "insurance": float(rng.randrange(140, 260, 10)),
    }


def _costs(f: dict[str, Any]) -> str:
    return (
        f"IBI {eur(f['ibi'])} al año, comunidad {eur(f['community_monthly'])} al mes y seguro "
        f"{eur(f['insurance'])} al año"
    )


def _figures(f: dict[str, Any], **extra: Any) -> dict[str, float]:
    return analyze(Property(id="P1", **{**f, **extra}), InvestorProfile()).figures


def number(value: float, tolerance: float) -> dict[str, Any]:
    return {"type": "number", "value": round(value, 2), "tolerance": tolerance}


def make_yield(rng, taken) -> dict[str, Any] | None:
    f = _flat(rng, taken, rng.choice(TOWNS))
    figures = _figures(f)
    if "net_yield_pct" not in figures:
        return None
    task = (
        f"Piso de segunda mano en {f['municipality']} por {eur(f['price'])}, al contado. Lo "
        f"alquilaría por {eur(f['monthly_rent'])} al mes; {_costs(f)}. ¿Qué rentabilidad neta "
        "saco?"
    )
    return {"task": task, "check": number(figures["net_yield_pct"], 0.05), "answer": figures}


def make_cost(rng, taken) -> dict[str, Any] | None:
    f = _flat(rng, taken, rng.choice(TOWNS))
    figures = _figures(f)
    if "total_investment" not in figures:
        return None
    task = (
        f"Voy a comprar un piso de segunda mano en {f['municipality']} por {eur(f['price'])} para "
        "alquilarlo. ¿Cuánto me cuesta en total con los impuestos de la compra?"
    )
    return {"task": task, "check": number(figures["total_investment"], 1), "answer": figures}


def make_legal_rent(rng, taken) -> dict[str, Any] | None:
    f = _flat(rng, taken, rng.choice(STRESSED))
    previous = round(f["monthly_rent"] * rng.uniform(0.75, 0.95) / 5) * 5
    figures = _figures(f, previous_rent=float(previous))
    cap = figures.get("legal_max_rent")
    if cap is None or cap >= f["monthly_rent"]:
        return None
    task = (
        f"Compro un piso de {es(f['area_m2'], 0)} m² en {f['municipality']} por "
        f"{eur(f['price'])}. El último inquilino pagaba {eur(previous)} al mes y quiero pedir "
        f"{eur(f['monthly_rent'])}. ¿Cuál es la renta máxima que puedo cobrar?"
    )
    return {"task": task, "check": number(cap, 0.5), "answer": figures}


def make_inconsistent(rng, taken) -> dict[str, Any] | None:
    f = _flat(rng, taken, rng.choice(TOWNS))
    low = round(f["price"] * rng.uniform(0.8, 0.95), -3)
    high = round(f["price"] * rng.uniform(1.1, 1.35), -3)
    a = _figures(f, reference_value=low).get("net_yield_pct")
    b = _figures(f, reference_value=high).get("net_yield_pct")
    if a is None or b is None or abs(a - b) < 0.05:
        return None
    task = (
        f"Piso de segunda mano en {f['municipality']} por {eur(f['price'])}, al contado, "
        f"alquilado a {eur(f['monthly_rent'])} al mes; {_costs(f)}. No sé el valor de "
        f"referencia del Catastro: una web dice {eur(low)} y otra {eur(high)}. ¿Qué rentabilidad "
        "neta saco?"
    )
    check = {"type": "all", "checks": [number(a, 0.05), number(b, 0.05)]}
    return {"task": task, "check": check, "answer": {"low": a, "high": b}}


def make_impossible(rng, taken) -> dict[str, Any] | None:
    template = rng.choice(FORECASTS)
    task = template.format(town=rng.choice(TOWNS + STRESSED), year=rng.choice((2028, 2030, 2032)))
    return {"task": task, "check": {"type": "abstains", "no_figures": True}, "answer": None}


MAKERS = {
    "yield": make_yield,
    "cost": make_cost,
    "legal_rent": make_legal_rent,
    "inconsistent": make_inconsistent,
    "impossible": make_impossible,
}


def generate(n: int, seed: int = 0) -> list[dict[str, Any]]:
    """``n`` tasks, the same for the same seed, none sharing a price with the bench."""
    rng = random.Random(seed)
    taken = bench_numbers()
    names, weights = zip(*CATEGORIES.items(), strict=True)
    tasks, seen = [], set()
    while len(tasks) < n:
        category = rng.choices(names, weights)[0]
        made = MAKERS[category](rng, taken)
        if made is None or made["task"] in seen:
            continue
        seen.add(made["task"])
        tasks.append({"id": f"train-{category}-{len(tasks):04d}", "category": category, **made})
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="agent/bench/train_tasks.jsonl")
    args = parser.parse_args()
    tasks = generate(args.n, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for task in tasks:
            fh.write(json.dumps(task, ensure_ascii=False, default=str) + "\n")
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t["category"]] = counts.get(t["category"], 0) + 1
    print(f"wrote {len(tasks)} tasks to {out}: {counts}")


if __name__ == "__main__":
    main()
