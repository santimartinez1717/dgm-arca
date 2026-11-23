"""The phase 4 benchmark: its lines validate, its checks work and its figures are the engine's."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from agent.bench.build_bench import build, render
from agent.bench.schema import BENCH, BenchTask, load_bench
from agent.evaluate import abstains, check_answer, parse_numbers, run_check

SPECS = build()
TASKS = load_bench()

EXPECTED_CATEGORIES = {
    "screening": 3,
    "lever": 5,
    "inconsistent": 3,
    "large_holder": 2,
    "law_on_date": 2,
    "kb_plus_tool": 3,
    "grey_or_illegal": 2,
    "impossible": 2,
    "broken_tool": 2,
}


# --------------------------------------------------------------------------- the bench file


def test_bench_has_24_tasks_per_category():
    assert len(TASKS) == 24
    assert Counter(t.category for t in TASKS) == EXPECTED_CATEGORIES
    assert len({t.id for t in TASKS}) == len(TASKS)


def test_every_task_needs_two_tools_and_has_notes():
    for t in TASKS:
        assert t.notes, t.id
        if t.category != "impossible":
            assert len(t.required_tools) >= 2, t.id


def test_bench_matches_the_engine():
    """tasks.jsonl is exactly what build_bench.py writes: no figure was edited by hand."""
    assert BENCH.read_text(encoding="utf-8") == render(SPECS)


def test_flats_match_the_agent_analysis():
    """The screening figures are what the agent's analyze_property computes for each flat."""
    from agent.analysis import analyze
    from agent.bench.build_bench import FLATS
    from agent.case_file import InvestorProfile, Property

    for f in FLATS:
        prop = Property(
            id=f.id,
            municipality=f.municipality,
            price=f.price,
            monthly_rent=f.asking_rent,
            previous_rent=f.previous_rent,
            area_m2=f.area_m2,
            ibi=f.ibi,
            community_monthly=f.community,
            insurance=f.insurance,
        )
        figures = analyze(prop, InvestorProfile()).figures
        assert figures["effective_rent"] == f.legal_rent, f.id
        assert figures["net_yield_pct"] == f.net_yield, f.id


def test_course_examples_still_validate():
    path = Path(__file__).parents[1] / "agent/bench/example_tasks.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        BenchTask.model_validate(json.loads(line))


def test_broken_tool_tasks_name_a_required_tool():
    broken = [t for t in TASKS if t.category == "broken_tool"]
    assert {t.break_mode for t in broken} == {"error", "timeout"}
    with pytest.raises(ValueError):
        BenchTask.model_validate(
            {
                "category": "broken_tool",
                "task": "una tarea cualquiera",
                "required_tools": ["get_portfolio", "legal_rent_cap"],
                "check": {"type": "contains", "value": "x"},
                "break_tool": "get_rent_reference",
                "break_mode": "error",
            }
        )


def test_large_holder_tasks_seed_a_portfolio():
    for t in TASKS:
        if t.category == "large_holder":
            assert t.setup is not None and len(t.setup.portfolio) == 4


# --------------------------------------------------------------------------- the checks


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_check_accepts_correct_and_rejects_wrong_answer(spec):
    task = {"check": spec.check}
    assert check_answer(task, spec.good), spec.good
    assert not check_answer(task, spec.bad), spec.bad


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("el neto es 4,62 %", 4.62),
        ("necesitas 180.000 €", 180000),
        ("tributas 1.234,56 €", 1234.56),
        ("total 1,234.56 EUR", 1234.56),
        ("yield 4.62%", 4.62),
        ("flujo de caja −1.250 € al año", -1250),
        ("12.000.000 de euros", 12_000_000),
        ("una reducción del 60 %.", 60),
    ],
)
def test_parse_numbers_reads_spanish_and_english(text, value):
    assert any(abs(n - value) < 1e-9 for n in parse_numbers(text))


def test_parse_numbers_ignores_ids_and_keeps_ambiguous_readings():
    assert 7 not in parse_numbers("el piso P07")
    assert {1234.0, 1.234} <= set(parse_numbers("1.234"))


def test_number_check_on_spanish_formats():
    """The original check dropped the comma: '4,62' became 462."""
    task = {"check": {"type": "number", "value": 4.62, "tolerance": 0.01}}
    assert check_answer(task, "La rentabilidad neta es del 4,62 %.")
    assert not check_answer(task, "La rentabilidad neta es del 462 %.")
    task = {"check": {"type": "number", "value": 180000}}
    assert check_answer(task, "El valor de referencia es 180.000 €.")


def test_combinators_and_not_contains():
    check = {
        "type": "all",
        "checks": [
            {"type": "contains", "value": "Asesor"},
            {
                "type": "any",
                "checks": [{"type": "regex", "value": "fraude"}, {"type": "number", "value": 3}],
            },
            {"type": "not_contains", "value": ["te recomiendo"]},
        ],
    }
    assert run_check(check, "Es un fraude; consúltalo con un asesor.")
    assert not run_check(check, "Te recomiendo hacerlo, es un fraude menor. Pregunta a un asesor.")
    assert not run_check(check, "Consúltalo con un asesor.")


def test_contains_ignores_case_and_accents():
    assert run_check({"type": "contains", "value": "tributación"}, "TRIBUTACION del alquiler")


def test_abstains():
    assert abstains("No puedo predecir los precios de 2027.")
    assert abstains("Nadie sabe qué Euríbor habrá en 2030.")
    assert not abstains("Los precios bajarán un 5 % en 2027.")
    assert not abstains("No puedo saberlo, pero bajarán un 5 %.", no_figures=True)


def test_unknown_check_fails_closed():
    assert not check_answer({"check": {"type": "magic"}}, "anything")
    assert not check_answer({}, "anything")
