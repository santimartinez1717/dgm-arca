"""The training-task generator of issue 18: reproducible, checkable and disjoint from the bench."""

from __future__ import annotations

import json
import re

from agent.bench.generate_tasks import bench_numbers, generate
from agent.bench.schema import BENCH
from agent.evaluate import check_answer


def test_same_seed_same_tasks_and_different_seed_different_tasks():
    assert generate(30, seed=0) == generate(30, seed=0)
    assert generate(30, seed=0) != generate(30, seed=1)


def test_every_category_appears_and_ids_are_unique():
    tasks = generate(200, seed=0)
    assert {t["category"] for t in tasks} == {
        "yield",
        "cost",
        "legal_rent",
        "inconsistent",
        "impossible",
    }
    assert len({t["id"] for t in tasks}) == len({t["task"] for t in tasks}) == 200


def test_no_task_reuses_a_flat_of_the_bench():
    bench = [json.loads(line)["task"] for line in BENCH.read_text(encoding="utf-8").splitlines()]
    taken = bench_numbers()
    for task in generate(300, seed=0):
        assert task["task"] not in bench
        price = re.search(r"por (\d[\d.]*) €", task["task"])  # the purchase price comes first
        if price:
            assert int(price.group(1).replace(".", "")) not in taken, task["task"]


def test_the_check_accepts_the_engine_answer_and_rejects_a_wrong_one():
    for task in generate(60, seed=0):
        check = task["check"]
        if check["type"] == "number":
            right = f"El resultado es {check['value']:.2f}".replace(".", ",")
            assert check_answer(task, right)
            assert not check_answer(task, "El resultado es 1,23")
        elif check["type"] == "all":
            values = [c["value"] for c in check["checks"]]
            both = " y ".join(f"{v:.2f} %".replace(".", ",") for v in values)
            assert check_answer(task, f"Según el valor de referencia, {both}.")
            assert not check_answer(task, f"Sería {values[0]:.2f} %".replace(".", ","))
        else:
            assert check_answer(task, "No puedo predecir los precios futuros.")
            assert not check_answer(task, "Valdrá 250.000 €.")
