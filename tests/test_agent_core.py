"""Phase-4 core: case file, analysis, levers, auditor and memory policy. No model, no network."""

from __future__ import annotations

from datetime import date

import pytest

from agent import case_file, levers
from agent.analysis import analyze
from agent.auditor import DISCLAIMER, audit, numbers_in, parse_number
from agent.case_file import CaseFile, InvestorProfile, Property
from agent.memory import ConversationMemory
from agent.playbook.schema import Lever, parse_levers
from agent.tools.case_tools import CASE_TOOLS
from tool_use.registry import ToolRegistry


def barcelona(**extra) -> Property:
    data = dict(
        id="P1",
        municipality="Barcelona",
        price=250000,
        area_m2=70,
        monthly_rent=1300,
        previous_rent=1250,
        cadastral_value=120000,
        land_share_pct=40,
        ibi=500,
        community_monthly=60,
        insurance=250,
        contract_date=date(2026, 12, 15),
    )
    return Property(**{**data, **extra})


PROFILE = InvestorProfile(properties_owned=2, marginal_tax_rate_pct=37, target_net_yield_pct=4.5)


# --------------------------------------------------------------------------- case file


def test_case_file_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCA_CASE_DB", str(tmp_path / "cases.sqlite"))
    case = case_file.load("s1")
    assert case.properties == {}
    case.properties["P1"] = barcelona()
    case.add_figure("net_yield_pct", 4.92, "%", "analyze_property", "P1")
    case.add_figure("net_yield_pct", 4.95, "%", "analyze_property", "P1")  # replaces
    case_file.save(case)
    again = case_file.load("s1")
    assert again.properties["P1"].contract_date == date(2026, 12, 15)
    assert [f.value for f in again.figures] == [4.95]


def test_unknown_property_lists_the_known_ones():
    case = CaseFile(session_id="s", properties={"P1": barcelona()})
    assert case.property("p1").id == "P1"
    with pytest.raises(ValueError, match="P1"):
        case.property("P9")


def test_current_only_inside_active():
    with pytest.raises(RuntimeError):
        case_file.current()
    case = CaseFile(session_id="s")
    with case_file.active(case):
        assert case_file.current() is case


def test_citation_keys_are_reused():
    case = CaseFile(session_id="s")
    assert case.cite("boe/lau.md · a-1") == "K1"
    assert case.cite("boe/lau.md · a-2") == "K2"
    assert case.cite("boe/lau.md · a-1") == "K1"


# --------------------------------------------------------------------------- analysis


def test_rent_above_previous_one_is_capped_in_a_stressed_zone():
    result = analyze(barcelona(), PROFILE)
    assert result.stressed_zone is True
    assert result.figures["legal_max_rent"] == 1250
    assert result.figures["effective_rent"] == 1250
    assert any(w.startswith("rent_above_legal_cap") for w in result.warnings)
    # ITP 10 % in Catalonia on the price (reference value assumed equal to the price)
    assert result.figures["total_investment"] == 275000
    assert "reference_value" in {a.field for a in result.assumptions}


def test_missing_data_is_reported_not_raised():
    result = analyze(Property(id="P2", municipality="Valencia", price=180000), InvestorProfile())
    assert "monthly_rent" in result.missing
    assert "total_investment" in result.figures
    assert analyze(Property(id="P3"), InvestorProfile()).missing == ["price"]


def test_absurd_monthly_rent_is_not_computed():
    # bench inconsistent-03: "se alquila por 10.200 € al mes" for a 140.000 € flat
    flat = Property(id="P1", municipality="Murcia", price=140000, monthly_rent=10200)
    result = analyze(flat, InvestorProfile())
    assert "net_yield_pct" not in result.figures
    assert any(m.startswith("monthly_rent") for m in result.missing)
    case = CaseFile(session_id="s", properties={"P1": flat})
    out = levers.simulate(case, "P1", overrides={"monthly_rent": 850})
    assert out["scenarios"][0]["net_yield_pct"] > 0


def test_contract_date_decides_the_irpf_scale():
    before = analyze(barcelona(contract_date=date(2026, 11, 30)), PROFILE)
    after = analyze(barcelona(), PROFILE)
    assert "Ley 12/2023" in before.rules["irpf_reduction"]
    assert "RDL 29/2026" in after.rules["irpf_reduction"]


# --------------------------------------------------------------------------- levers


def test_find_levers_filters_by_the_case():
    case = CaseFile(session_id="s", profile=PROFILE, properties={"P1": barcelona()})
    found = levers.find(case, "P1")
    ids = {lever["id"] for lever in found["applicable"]}
    assert "rent_cut_over_5pct" in ids
    # the reference value is unknown, so it cannot be above the price
    assert "reference_value_above_price" not in ids


def test_rent_cut_raises_the_reduction_and_is_recorded():
    case = CaseFile(session_id="s", profile=PROFILE, properties={"P1": barcelona()})
    out = levers.simulate(case, "P1", ["rent_cut_over_5pct"])
    scenario = out["scenarios"][0]
    assert scenario["irpf_reduction_pct"] == 90
    assert scenario["effective_rent"] == 1175  # 1250 * 0.94
    assert any(f.scenario == "rent_cut_over_5pct" for f in case.figures)


def test_overrides_branch_on_a_fact_and_reject_unknown_fields():
    case = CaseFile(session_id="s", profile=PROFILE, properties={"P1": barcelona()})
    out = levers.simulate(case, "P1", overrides={"reference_value": 300000})
    assert out["scenarios"][0]["total_investment"] == 280000  # ITP on 300.000
    out = levers.simulate(case, "P1", overrides={"bogus": 1})
    assert "error" in out["scenarios"][0]


def test_contract_date_lever_compares_both_irpf_scales():
    case = CaseFile(session_id="s", profile=PROFILE, properties={"P1": barcelona()})
    assert "contract_date_before_rdl_29_2026" in {
        lever["id"] for lever in levers.find(case, "P1")["applicable"]
    }
    out = levers.simulate(case, "P1", ["contract_date_before_rdl_29_2026"])
    assert "Ley 12/2023" in out["scenarios"][0]["irpf_rule"]


def test_cheapest_itp_region_lowers_the_purchase_cost():
    assert levers.cheapest_itp_region() == "pais_vasco"
    case = CaseFile(session_id="s", profile=PROFILE, properties={"P1": barcelona()})
    out = levers.simulate(case, "P1", ["cheapest_itp_region"])
    assert out["scenarios"][0]["total_investment_change"] < 0


def test_large_holder_lever_only_for_investors_near_the_threshold():
    case = CaseFile(session_id="s", profile=PROFILE, properties={"P1": barcelona()})
    assert "stay_below_large_holder" not in {
        lever["id"] for lever in levers.find(case, "P1")["applicable"]
    }
    big = PROFILE.model_copy(update={"properties_owned": 12})
    case = CaseFile(session_id="s", profile=big, properties={"P1": barcelona()})
    assert "stay_below_large_holder" in {
        lever["id"] for lever in levers.find(case, "P1")["applicable"]
    }


def test_regional_levers_follow_the_resolved_region():
    madrid = barcelona(municipality="Madrid", region="Comunidad de Madrid")
    for prop, expected in ((madrid, True), (barcelona(), False)):
        case = CaseFile(session_id="s", profile=PROFILE, properties={"P1": prop})
        ids = {lever["id"] for lever in levers.find(case, "P1")["applicable"]}
        assert ("madrid_rental_expenses_deduction" in ids) is expected


def test_illegal_and_qualitative_levers_are_never_priced():
    case = CaseFile(session_id="s", profile=PROFILE, properties={"P1": barcelona()})
    out = levers.simulate(case, "P1", ["short_term_rental", "undeclared_cash_price"])
    assert "qualitative" in out["scenarios"][0]
    assert "refused" in out["scenarios"][1]


def test_playbook_schema_rules():
    base = {
        "id": "x",
        "title": "t",
        "evidence": {"source": "boe/lau.md", "quote": "una cita literal suficientemente larga"},
        "explanation": "sin cifras",
    }
    assert parse_levers([{**base, "level": "legal"}])[0].id == "x"
    with pytest.raises(ValueError, match="risk"):
        Lever.model_validate({**base, "level": "grey"})
    with pytest.raises(ValueError, match="figures"):
        Lever.model_validate({**base, "level": "legal", "explanation": "ahorras un 5 %"})
    with pytest.raises(ValueError):
        Lever.model_validate({**base, "level": "legal", "engine": {"set": {"property.nope": 1}}})
    with pytest.raises(ValueError, match="duplicated"):
        parse_levers([{**base, "level": "legal"}, {**base, "level": "legal"}])


# --------------------------------------------------------------------------- tools


def test_case_tools_through_the_registry():
    registry = ToolRegistry().register(*CASE_TOOLS)
    case = CaseFile(session_id="s")
    with case_file.active(case):
        r = registry.call("record_property", {"property_id": "P1", "municipality": "Valencia"})
        assert r.ok and r.result["saved"] == ["municipality"]
        r = registry.call("record_property", {"property_id": "P1", "price": 180000})
        assert case.properties["P1"].municipality == "Valencia"
        r = registry.call("analyze_property", {"property_id": "P1"})
        assert r.ok and "monthly_rent" in r.result["missing"]
        assert any("monthly_rent" in q for q in case.open_questions)
        r = registry.call("what_if", {"property_id": "P1"})
        assert not r.ok and "lever_ids" in r.error


# --------------------------------------------------------------------------- auditor


@pytest.mark.parametrize(
    ("text", "value"),
    [("275.000", 275000), ("275 000", 275000), ("4,56", 4.56), ("4.56", 4.56), ("1.250,5", 1250.5)],
)
def test_parse_spanish_and_english_numbers(text, value):
    assert parse_number(text) == value


def test_dates_and_ids_are_not_figures():
    found = [w for w, _, _ in numbers_in("P1 firmó el 15/12/2026 un 4,5 %")]
    assert found == ["4,5 %"]


def test_auditor_accepts_grounded_figures_and_adds_the_disclaimer():
    result = audit(
        "El neto es 4,92 % sobre 275.000 € [K1].",
        sources=["piso de 250.000 €"],
        figures=[4.92, 275000.0],
        retrieved_ids=["K1"],
    )
    assert result.ok and result.disclaimer_added
    assert result.answer.endswith(DISCLAIMER)


def test_auditor_rejects_invented_figures_and_citations():
    result = audit("Sacarías un 4,7 % y 2.000 € más [K9]. Consulta a un asesor.", sources=[])
    assert not result.ok
    assert result.unsupported_numbers == ["4,7 %", "2.000 €"]
    assert result.unknown_citations == ["K9"]
    assert not result.disclaimer_added
    assert "4,7 %" in result.feedback()


def test_auditor_tolerates_rounding_and_percent_fractions():
    assert audit("un 4,6 %", sources=[], figures=[4.56]).ok
    assert audit("un 4,5 %", sources=[], figures=[0.045]).ok
    assert not audit("un 4,7 %", sources=[], figures=[4.56]).ok


# --------------------------------------------------------------------------- memory


def test_memory_keeps_the_task_and_shrinks_old_observations():
    memory = ConversationMemory("sys", count_tokens=len, token_budget=200, keep_last=2)
    memory.add("user", "TASK")
    for i in range(4):
        memory.add("assistant", f"call {i}")
        memory.add("tool", "x" * 500, name="t")
    seen = []
    assert memory.compress(lambda old: seen.extend(old) or "summary")
    assert memory.messages[0]["content"] == "TASK"
    assert memory.messages[1]["role"] != "tool"  # a call is never split from its result
    assert all(len(m["content"]) < 320 for m in seen if m["role"] == "tool")
    assert "summary" in memory.render("new system")[0]["content"]
    assert memory.render("new system")[0]["content"].startswith("new system")
