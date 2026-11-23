"""write_investment_report: every figure from the case file, the disclaimer always. No model."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from agent import case_file
from agent.auditor import DISCLAIMER, audit
from agent.case_file import CaseFile, InvestorProfile, Property
from agent.playbook.schema import load_levers
from agent.tools import report
from agent.tools.case_tools import analyze_property, what_if
from agent.tools.report import TOOLS, write_investment_report
from tool_use.registry import ToolRegistry

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def reports_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCA_REPORTS_DIR", str(tmp_path / "reports"))
    return tmp_path / "reports"


def make_case() -> CaseFile:
    """Two analysed properties, P1 with levers and a doubtful fact simulated, P3 without data."""
    case = CaseFile(
        session_id="sesion/7",
        profile=InvestorProfile(
            properties_owned=2,
            financing=True,
            interest_rate_pct=3.2,
            marginal_tax_rate_pct=37,
            target_net_yield_pct=4.5,
        ),
    )
    case.properties["P1"] = Property(
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
    case.properties["P2"] = Property(
        id="P2", municipality="Valencia", price=150000, monthly_rent=800
    )
    case.properties["P3"] = Property(id="P3", municipality="Madrid")
    with case_file.active(case):
        analyze_property(property_id="P1")
        analyze_property(property_id="P2")
        what_if(
            property_id="P1",
            lever_ids=["rent_cut_over_5pct", "rehabilitation_before_contract", "short_term_rental"],
            overrides={"reference_value": 150000},
        )
    case.cite("boe/lirpf.md · Artículo 23")
    return case


def write(case: CaseFile, **arguments) -> tuple[dict, str]:
    with case_file.active(case):
        out = write_investment_report(**arguments)
    return out, Path(out["path"]).read_text(encoding="utf-8")


def sections(text: str) -> dict[str, str]:
    out = {}
    for chunk in text.split("\n## ")[1:]:
        heading, _, body = chunk.partition("\n")
        out[heading.strip()] = body
    return out


def playbook_texts() -> list[str]:
    return [f"{lever.title} {lever.risk or ''} {lever.evidence.source}" for lever in load_levers()]


def case_texts(case: CaseFile) -> list[str]:
    """Everything the case file holds besides the engine figures: what the user gave,
    the assumptions, the open questions, the sources, the scenario names."""
    return [
        case.session_id,
        case.profile.model_dump_json(),
        *(p.model_dump_json() for p in case.properties.values()),
        *(a.model_dump_json() for a in case.assumptions),
        *case.open_questions,
        *case.sources.values(),
        *(f.scenario for f in case.figures),
    ]


def test_report_is_written_and_returns_only_its_path(reports_dir):
    case = make_case()
    out, text = write(case, property_ids=["p1", "P2", "P1"])
    path = Path(out["path"])
    assert path.parent == reports_dir and path.exists()
    assert path.name == "sesion-7-informe-de-inversion-p1-p2.md"
    assert out["n_properties"] == 2
    assert out["sections"] == [
        "Resumen",
        "Cifras por piso",
        "Palancas evaluadas",
        "Supuestos",
        "Preguntas abiertas",
        "Fuentes consultadas",
        "Aviso",
    ]
    assert list(sections(text)) == out["sections"]
    assert set(out) == {"path", "n_properties", "sections"}  # never the text itself


def test_every_figure_of_the_tables_is_a_case_figure():
    case = make_case()
    _, text = write(case, property_ids=["P1", "P2"])
    parts = sections(text)
    tables = parts["Cifras por piso"] + parts["Palancas evaluadas"]
    figures = [f.value for f in case.figures]
    # Only the lever titles and the scenario names may add a number (a legal threshold, the
    # value a what_if override branched on); every other number is an engine figure.
    names = playbook_texts() + [f.scenario for f in case.figures]
    result = audit(tables, sources=names, figures=figures)
    assert result.unsupported_numbers == []
    assert "4,92 %" in tables and "275.000 €" in tables  # P1's engine figures are shown


def test_every_number_of_the_report_is_in_the_case_file():
    case = make_case()
    _, text = write(case, property_ids=[])
    result = audit(
        text,
        sources=case_texts(case) + playbook_texts(),
        figures=[f.value for f in case.figures],
        retrieved_ids=case.sources,
    )
    assert result.ok, result.unsupported_numbers


def test_the_check_is_not_vacuous():
    case = make_case()
    _, text = write(case, property_ids=["P1"])
    tampered = text.replace("4,92 %", "4,99 %")
    result = audit(tampered, sources=case_texts(case) + playbook_texts(), figures=[])
    assert "4,99 %" in result.unsupported_numbers


def test_lever_differences_are_recorded_as_figures_of_the_report():
    case = make_case()
    _, text = write(case, property_ids=["P1"])
    deltas = {(f.scenario, f.name): f.value for f in case.figures if f.tool == report.TOOL_NAME}
    assert deltas[("rent_cut_over_5pct", "net_yield_pct_change")] == -0.33
    assert "4,59 % (-0,33 pp)" in text
    # Written again, the differences are replaced, not duplicated.
    write(case, property_ids=["P1"])
    again = [f for f in case.figures if f.tool == report.TOOL_NAME]
    assert len(again) == len(deltas)


def test_levers_quantified_with_difference_and_qualitative_with_risk():
    case = make_case()
    _, text = write(case, property_ids=["P1"])
    levers_part = sections(text)["Palancas evaluadas"]
    assert "`rehabilitation_before_contract`, legal" in levers_part
    assert "Combinadas (`rent_cut_over_5pct+rehabilitation_before_contract`)" in levers_part
    assert "Escenario `if reference_value=150000`" in levers_part
    assert "`short_term_rental`, zona gris" in levers_part and "Riesgo:" in levers_part


@pytest.mark.parametrize(
    "ids",
    [["P1"], ["P2"], ["P2", "P3"], []],
    ids=["levers", "no-levers", "with-missing-data", "all"],
)
def test_the_disclaimer_is_always_there(ids):
    _, text = write(make_case(), property_ids=ids)
    assert text.rstrip().endswith(DISCLAIMER)
    assert "asesor fiscal" in text and "datos sintéticos" in text


def test_assumptions_and_open_questions_of_the_properties_asked():
    case = make_case()
    case.ask("P3: falta price")
    _, text = write(case, property_ids=["P2"])
    parts = sections(text)
    assert "P2 · `reference_value` = 150.000" in parts["Supuestos"]
    assert "P1 ·" not in parts["Supuestos"]
    assert "P2: falta cadastral_value" in parts["Preguntas abiertas"]
    assert "P3: falta price" not in parts["Preguntas abiertas"]


def test_property_without_figures_is_reported_and_warned():
    out, text = write(make_case(), property_ids=["P2", "P3"])
    assert "P3" in out["warnings"][0]
    assert "Sin cifras del motor" in sections(text)["Cifras por piso"]


def test_unknown_id_is_an_observation_listing_the_known_ones(reports_dir):
    registry = ToolRegistry().register(*TOOLS)
    with case_file.active(make_case()):
        record = registry.call("write_investment_report", {"property_ids": ["P1", "P9"]})
    assert not record.ok
    assert "'P9'" in record.error and "P1, P2, P3" in record.error
    assert not reports_dir.exists()  # nothing written


def test_no_engine_figures_asks_for_analyze_property(reports_dir):
    case = CaseFile(session_id="s", properties={"P1": Property(id="P1", price=100000)})
    with case_file.active(case), pytest.raises(ValueError, match="analyze_property"):
        write_investment_report(property_ids=["P1"])
    assert not reports_dir.exists()


def test_title_in_words_names_the_file_and_figures_are_refused():
    case = make_case()
    out, text = write(case, property_ids=["P1"], title="Piso de la calle Mallorca")
    assert Path(out["path"]).name == "sesion-7-piso-de-la-calle-mallorca.md"
    assert text.startswith("# Piso de la calle Mallorca\n")
    with case_file.active(case), pytest.raises(ValueError, match="figures"):
        write_investment_report(property_ids=["P1"], title="Piso de 250.000 € al 5,1 %")


def test_needs_confirmation_and_is_exported():
    assert TOOLS == [write_investment_report]
    assert write_investment_report.requires_confirmation
    schema = write_investment_report.definition["function"]["parameters"]
    assert schema["required"] == ["property_ids"]


def test_outputs_stay_out_of_git():
    assert report.DEFAULT_DIR.parts[0] == "outputs"
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "outputs/" in ignored
