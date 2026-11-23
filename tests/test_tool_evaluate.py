"""The phase 2 benchmark and its scorer."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from tool_use.evaluate import (
    arguments_match,
    expected_calls,
    load_bench,
    score_case,
    summarise,
    tool_defaults,
    values_match,
)
from tool_use.tools import default_registry

BENCH = Path(__file__).parents[1] / "tool_use" / "bench" / "cases.jsonl"


@pytest.fixture(scope="module")
def defaults():
    return tool_defaults(default_registry())


def call(name, ok=True, **arguments):
    return {"name": name, "arguments": arguments, "ok": ok}


def test_the_bench_is_well_formed():
    cases = load_bench(BENCH)
    registry = default_registry()
    assert len(cases) >= 30 and len({c["id"] for c in cases}) == len(cases)
    categories = Counter(c["category"] for c in cases)
    assert categories["no_tool"] >= 6 and categories["chain"] >= 4 and categories["parallel"] >= 3
    assert {c["expected_tool"] for c in cases if c["needs_tool"]} == set(registry.tools)
    for case in cases:
        for want in expected_calls(case):
            tool = registry.tools[want["tool"]]
            args = {k: v for k, v in want["arguments"].items() if v != "*"}
            assert set(want["arguments"]) <= set(tool.args_model.model_fields), case["id"]
            if len(args) == len(want["arguments"]):  # wildcards may hide required fields
                tool.validate(args)


def test_values_match_is_tolerant_where_it_should_be():
    assert values_match(185000, 185000.0) and values_match(185000, "185000")
    assert values_match(246728.97, 246800) and not values_match(246728.97, 250000)
    assert values_match("Sant Cugat del Vallès", "sant cugat del valles")
    assert values_match("2", "02") and values_match("*", "anything")
    assert not values_match(True, 1) and not values_match(0.75, 75)


def test_extra_arguments_must_be_defaults(defaults):
    d = defaults["acquisition_cost"]
    assert arguments_match({"price": 1}, {"price": 1, "new_build": False}, d)
    assert arguments_match({"price": 1}, {"price": 1, "reference_value": None}, d)
    assert not arguments_match({"price": 1}, {"price": 1, "renovation": 5000}, d)
    loan = defaults["rental_returns"]
    assert arguments_match({"loan": 0}, {"loan": 0, "loan_years": 0, "interest_rate_pct": 0}, loan)


def test_region_is_compared_by_community(defaults):
    d = defaults["acquisition_cost"]
    assert arguments_match({"region": "andalucia"}, {"region": "Sevilla"}, d)
    assert not arguments_match({"region": "andalucia"}, {"region": "extremadura"}, d)
    assert not arguments_match({"region": "andalucia"}, {"region": "Narnia"}, d)


def test_arguments_that_failed_validation_are_not_right(defaults):
    case = {"needs_tool": True, "expected_tool": "get_market_rates", "expected_arguments": {}}
    bad = call("get_market_rates", ok=False)
    assert not score_case(case, [bad], defaults=defaults)["arguments_ok"]


def test_single_and_no_tool_cases(defaults):
    single = {"needs_tool": True, "expected_tool": "get_market_rates", "expected_arguments": {}}
    assert score_case(single, [call("get_market_rates")], defaults=defaults)["arguments_ok"]
    assert not score_case(single, [], defaults=defaults)["selection_ok"]
    none = {"needs_tool": False}
    assert score_case(none, [], defaults=defaults)["selection_ok"]
    assert not score_case(none, [call("get_market_rates")], defaults=defaults)["selection_ok"]


def test_chain_needs_the_calls_in_order(defaults):
    case = {
        "needs_tool": True,
        "expected_tool": "get_market_rates",
        "expected_calls": [
            {"tool": "get_market_rates", "arguments": {}},
            {"tool": "get_rent_reference", "arguments": {"municipality": "Bilbao"}},
        ],
    }
    good = [call("get_market_rates"), call("get_rent_reference", municipality="bilbao")]
    assert score_case(case, good, defaults=defaults)["sequence_ok"]
    assert not score_case(case, good[::-1], defaults=defaults)["sequence_ok"]
    failed = [call("get_market_rates"), call("get_rent_reference", ok=False, municipality="Bilbao")]
    assert not score_case(case, failed, defaults=defaults)["sequence_ok"]


def test_parallel_needs_the_same_turn_in_any_order(defaults):
    case = {
        "needs_tool": True,
        "expected_tool": "get_rent_reference",
        "expected_arguments": {"municipality": "Barcelona"},
        "expected_calls": [
            {"tool": "get_rent_reference", "arguments": {"municipality": "Barcelona"}, "turn": 1},
            {"tool": "get_rent_reference", "arguments": {"municipality": "Bilbao"}, "turn": 1},
        ],
    }
    calls = [
        call("get_rent_reference", municipality="Bilbao"),
        call("get_rent_reference", municipality="Barcelona"),
    ]
    together = score_case(case, calls, [1, 1], defaults)
    assert together["arguments_ok"] and together["sequence_ok"]
    assert not score_case(case, calls, [1, 2], defaults)["sequence_ok"]


def test_summary_by_category():
    rows = [
        {"category": "single", "needs_tool": True, "tool_calls": [1], "turns": 2,
         "selection_ok": True, "arguments_ok": False, "sequence_ok": False},
        {"category": "no_tool", "needs_tool": False, "tool_calls": [1], "turns": 2,
         "selection_ok": False, "arguments_ok": False, "sequence_ok": False},
    ]  # fmt: skip
    summary = summarise(rows)
    assert summary["tool_selection_accuracy"] == 0.5 and summary["false_call_rate"] == 1.0
    assert summary["by_category"]["single"]["arguments"] == 0.0


def test_phase1_compare_summary_by_variant_and_family():
    from tool_use.phase1_compare import registry_for
    from tool_use.phase1_compare import summarise as summarise_phase1

    assert list(registry_for("arithmetic").tools) == ["calculator"]
    assert not registry_for("none").tools
    ok = {"ok": True}
    rows = [
        {"variant": "none", "family": "net_yield", "correct": False, "tool_calls": []},
        {"variant": "domain", "family": "net_yield", "correct": True, "tool_calls": [ok]},
        {"variant": "domain", "family": "irpf_rental", "correct": False, "tool_calls": [ok]},
    ]
    summary = summarise_phase1(rows)
    assert summary["none"]["pass_at_1"] == 0.0 and summary["domain"]["pass_at_1"] == 0.5
    assert summary["domain"]["by_family"] == {"irpf_rental": 0.0, "net_yield": 1.0}
    assert summary["domain"]["used_a_tool"] == 1.0
