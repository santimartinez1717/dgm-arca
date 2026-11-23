"""screen_properties: the batch screening of the case file. No model, no network."""

from __future__ import annotations

from datetime import date

import pytest

from agent import case_file
from agent.analysis import analyze
from agent.case_file import CaseFile, InvestorProfile, Property
from agent.tools.screening import TOOLS, screen_properties
from tool_use.registry import ToolRegistry

COMMON = dict(
    municipality="Murcia",
    area_m2=70,
    ibi=300,
    community_monthly=40,
    insurance=160,
    cadastral_value=60000,
    land_share_pct=40,
    contract_date=date(2026, 12, 15),
)

# (id, price, monthly rent, previous rent, stressed zone, extra facts). The stressed zone is
# given, not looked up, so the test does not depend on which declarations are in force today.
FLATS = [
    ("P01", 120000, 700, None, False, {}),  # passes
    ("P02", 100000, 700, None, False, {}),  # passes, the best
    ("P03", 130000, 690, None, False, {}),  # passes
    ("P04", 150000, 700, None, False, {}),  # passes just above 4.5 %
    ("P05", 300000, 1500, None, False, {}),  # good yield, price above max_price
    ("P06", 160000, 900, 600, True, {}),  # passes only with the asking rent: legal cap 600
    ("P07", 140000, 900, 700, True, {}),  # capped at 700 and still passes
    ("P08", 120000, None, None, False, {}),  # no rent: missing data
    ("P09", None, 700, None, False, {}),  # no price: missing data
    ("P10", 200000, 650, None, False, {}),  # low net yield
    ("P11", 158000, 700, None, False, {}),  # near miss
    ("P12", 240000, 700, None, False, {}),  # low net yield
    ("P13", 156000, 700, None, False, {}),  # near miss, closer
    ("P14", 110000, 650, None, False, {}),  # passes
    ("P15", 125000, 700, None, False, {"municipality": None}),  # no region: missing data
]
PROFILE = InvestorProfile(properties_owned=1, marginal_tax_rate_pct=30, target_net_yield_pct=4.5)


def flats() -> dict[str, Property]:
    out = {}
    for pid, price, rent, previous, stressed, extra in FLATS:
        data = {**COMMON, **extra}
        out[pid] = Property(
            id=pid,
            price=price,
            monthly_rent=rent,
            previous_rent=previous,
            stressed_zone=stressed,
            **data,
        )
    return out


def new_case(profile: InvestorProfile = PROFILE) -> CaseFile:
    return CaseFile(session_id="s", profile=profile, properties=flats())


def screen(case: CaseFile | None = None, **arguments):
    case = case or new_case()
    with case_file.active(case):
        return screen_properties(**arguments), case


def rows(result: dict) -> dict[str, dict]:
    return {r["id"]: r for r in result["passed"] + result["rejected"]}


def test_groups_and_reasons():
    result, _ = screen(min_net_yield_pct=4.5, max_price=250000)
    passed = [r["id"] for r in result["passed"]]
    assert set(passed) == {"P01", "P02", "P03", "P04", "P07", "P14"}
    yields = [r["net_yield_pct"] for r in result["passed"]]
    assert yields == sorted(yields, reverse=True) and passed[0] == "P02"

    reason = {r["id"]: r["reason"] for r in result["rejected"]}
    assert set(reason) == {"P05", "P06", "P08", "P09", "P10", "P11", "P12", "P13", "P15"}
    assert reason["P05"] == "precio 300.000 € > 250.000 €"
    assert reason["P06"].startswith("neto ") and "tope legal 600" in reason["P06"]
    assert reason["P08"] == "falta monthly_rent"
    assert reason["P09"] == "falta price"
    assert reason["P15"].startswith("falta region")
    low = rows(result)["P10"]["net_yield_pct"]
    assert reason["P10"] == f"neto {f'{low:g}'.replace('.', ',')} % < 4,5 %"

    assert result["near_miss"] == ["P13", "P11"]  # closest first; never price or missing data
    assert result["criteria"] == {
        "min_net_yield_pct": 4.5,
        "max_price": 250000,
        "rent": "legal",
    }


def test_rent_above_the_cap_is_flagged():
    result, _ = screen(min_net_yield_pct=4.5)
    r = rows(result)
    assert any(w.startswith("rent_above_legal_cap") for w in r["P07"]["warnings"])
    assert "tope legal 600" in r["P06"]["reason"] and "warnings" not in r["P06"]  # said once
    assert "warnings" not in r["P01"]


def test_figures_match_analyze_one_by_one():
    result, case = screen(min_net_yield_pct=4.5)
    for pid, row in rows(result).items():
        figures = analyze(case.properties[pid], PROFILE).figures
        assert row.get("net_yield_pct") == figures.get("net_yield_pct"), pid
        recorded = {
            f.name: f.value
            for f in case.figures
            if f.property_id == pid and f.scenario == "base" and f.tool == "screen_properties"
        }
        assert recorded == figures, pid


def test_missing_data_becomes_an_open_question():
    _, case = screen(min_net_yield_pct=4.5)
    assert "P08: falta monthly_rent" in case.open_questions
    assert "P09: falta price" not in case.open_questions  # the price is already a reason


def test_target_of_the_profile_is_the_default():
    result, _ = screen()
    assert result["criteria"]["min_net_yield_pct"] == 4.5
    assert {r["id"] for r in result["passed"]} == {"P01", "P02", "P03", "P04", "P05", "P07", "P14"}


def test_asking_rent_when_the_law_is_not_required():
    legal, _ = screen(min_net_yield_pct=4.5)
    result, case = screen(min_net_yield_pct=4.5, require_legal_rent=False)
    assert "P06" in {r["id"] for r in result["passed"]}
    assert rows(result)["P06"]["net_yield_pct"] > rows(legal)["P06"]["net_yield_pct"]
    assert rows(result)["P06"]["warnings"]  # still told that the rent is above the cap
    scenarios = {(f.property_id, f.scenario) for f in case.figures}
    assert ("P06", "asking_rent") in scenarios and ("P01", "asking_rent") not in scenarios
    assert result["criteria"]["rent"] == "asking"


def test_after_tax_uses_the_yield_after_irpf():
    case = new_case()
    case.properties["P01"] = case.properties["P01"].model_copy(update={"cadastral_value": None})
    result, case = screen(case, min_net_yield_pct=4.5, after_tax=True)
    r = rows(result)
    assert r["P01"]["reason"].startswith("falta cadastral_value")
    assert r["P04"]["reason"].startswith("neto tras IRPF ")
    for row in result["passed"]:
        figures = analyze(case.properties[row["id"]], PROFILE).figures
        assert row["after_tax_yield_pct"] == figures["after_tax_yield_pct"] >= 4.5


def test_cash_on_cash_with_financing():
    profile = PROFILE.model_copy(
        update={"financing": True, "interest_rate_pct": 3.0, "down_payment_pct": 20}
    )
    result, case = screen(new_case(profile), min_net_yield_pct=4.5, min_cash_on_cash_pct=8)
    for pid, row in rows(result).items():
        figures = analyze(case.properties[pid], profile).figures
        assert row.get("cash_on_cash_pct") == figures.get("cash_on_cash_pct"), pid
    for row in result["passed"]:
        assert row["cash_on_cash_pct"] >= 8
    assert any("cash-on-cash" in r["reason"] for r in result["rejected"])


def test_cash_on_cash_without_financing_is_missing():
    result, _ = screen(min_cash_on_cash_pct=5)
    assert rows(result)["P01"]["reason"].startswith("falta financing")


def test_empty_case_and_no_case():
    with case_file.active(CaseFile(session_id="s")), pytest.raises(ValueError, match="record"):
        screen_properties()
    with pytest.raises(RuntimeError):
        screen_properties()


def test_registers_as_a_tool():
    registry = ToolRegistry()
    registry.register(*TOOLS)
    definition = screen_properties.definition["function"]
    assert definition["name"] == "screen_properties"
    assert "min_net_yield_pct" in definition["parameters"]["properties"]
    case = new_case()
    with case_file.active(case):
        record = registry.call("screen_properties", {"min_net_yield_pct": 4.5})
    assert record.error is None, record.error
