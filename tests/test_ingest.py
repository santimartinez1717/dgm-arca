"""Deterministic ingestion of the CSV of flats pasted in a task (issue 12)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from agent.ingest import extract_properties, ingest, normalise_header, parse_number

BENCH_CSV = (Path(__file__).parent / "fixtures/bench_15_flats.csv").read_text(encoding="utf-8")


def test_semicolon_csv_with_spanish_headers_and_numbers():
    task = (
        "Mira estos pisos:\n"
        "Municipio;Precio (€);Renta mensual;Superficie (m²);Valor de referencia;IBI\n"
        "Sevilla;180.000;850;72,5;175.000,50;320\n"
        "Málaga;210.000;1.050;65;;400\n"
        "¿Cuál me conviene?"
    )
    props, text = extract_properties(task)
    assert [p.id for p in props] == ["P1", "P2"]
    p1, p2 = props
    assert (p1.municipality, p1.price, p1.monthly_rent) == ("Sevilla", 180000, 850)
    assert p1.area_m2 == 72.5 and p1.reference_value == 175000.5 and p1.ibi == 320
    assert p2.monthly_rent == 1050 and p2.reference_value is None  # empty cell: default
    assert (
        text == "Mira estos pisos:\n[2 pisos cargados en el expediente: P1, P2]\n¿Cuál me conviene?"
    )


def test_comma_csv_with_english_headers_inside_a_code_fence():
    task = (
        "Analyse these:\n"
        "```csv\n"
        "id,city,price,monthly_rent,area_m2,new_build,contract_date\n"
        "A,Madrid,250000,1200,80,yes,2026-12-15\n"
        'B,Valencia,190000,"950.5",70,no,01/03/2027\n'
        "```\n"
        "Thanks"
    )
    props, text = extract_properties(task)
    a, b = props
    assert (a.id, a.municipality, a.price, a.new_build) == ("A", "Madrid", 250000, True)
    assert a.contract_date == date(2026, 12, 15) and b.contract_date == date(2027, 3, 1)
    assert b.monthly_rent == 950.5 and b.new_build is False
    assert "```" not in text and "[2 pisos cargados en el expediente: A, B]" in text


def test_bench_csv_of_15_flats():
    props, text = extract_properties("Te paso 15 pisos:\n" + BENCH_CSV + "\n\n¿Cuáles pasan?")
    assert len(props) == 15
    assert [p.id for p in props][:2] == ["P01", "P02"] and props[-1].id == "P15"
    p07 = next(p for p in props if p.id == "P07")
    assert p07.municipality == "Santiago de Compostela"
    assert (p07.price, p07.monthly_rent, p07.previous_rent) == (155000, 950, 720)
    assert (p07.community_monthly, p07.insurance) == (50, 165)
    assert props[0].previous_rent is None  # empty cell
    assert "[15 pisos cargados en el expediente: P01…P15]" in text
    assert "265000" not in text


def test_unknown_columns_are_ignored_and_reported():
    result = ingest("precio;renta;color;orientación\n100000;600;azul;sur")
    [prop] = result.properties
    assert prop.price == 100000 and prop.monthly_rent == 600
    assert result.ignored_columns == ["color", "orientación"]


def test_unreadable_cells_are_reported_not_fatal():
    result = ingest("id;precio;renta\nX1;unos cien mil;600")
    [prop] = result.properties
    assert prop.price is None and prop.monthly_rent == 600
    assert result.bad_cells == ["X1.price: 'unos cien mil'"]


@pytest.mark.parametrize(
    "task",
    [
        "Piso en Valencia de 180.000 € alquilado por 850 €/mes, ¿rentabilidad?",
        "Tengo tres pisos: uno en Madrid, otro en Sevilla y otro en Málaga.",
        "precio;renta\n",  # a header with no rows is not a table
        "",
    ],
)
def test_text_without_csv_is_untouched(task):
    props, text = extract_properties(task, prose=False)
    assert props == [] and text == task


# --------------------------------------------------------------------------- one flat in prose

from agent.analysis import analyze  # noqa: E402
from agent.bench.build_bench import build  # noqa: E402
from agent.case_file import InvestorProfile  # noqa: E402
from agent.ingest import extract_prose  # noqa: E402

SPECS = {s.id: s for s in build()}

# Bench task -> (figure of the analysis, figure the bench expects): the prose read in code
# must give the engine the same numbers the bench was built with.
SAME_FIGURES = {
    "lever-01": [("irpf_reduced_net_income", ("after", "reduced_net_income"))],
    "lever-02": [("irpf_reduced_net_income", ("same", "reduced_net_income"))],
    "lever-03": [("effective_rent", ("cap_10pct",)), ("net_yield_pct", ("yield_10pct",))],
    "inconsistent-01": [("effective_rent", ("cap",)), ("net_yield_pct", ("yield_legal",))],
    "inconsistent-02": [("net_yield_pct", ("yield_ref_150000",))],
    "law_on_date-01": [("irpf_reduced_net_income", ("reduced_net_income",))],
    "law_on_date-02": [("irpf_reduced_net_income", ("reduced_net_income",))],
    "kb_plus_tool-01": [("irpf_depreciation", ("depreciation",))],
    "kb_plus_tool-02": [("effective_rent", ("cap",))],
    "kb_plus_tool-03": [("transfer_tax", ("transfer_tax",)), ("total_investment", ("total",))],
    "broken_tool-01": [("effective_rent", ("cap_if_stressed",))],
    "broken_tool-02": [("irpf_reduced_net_income", ("reduced_net_income",))],
}
# Tasks where reading one flat would be wrong: several flats, a portfolio, no flat at all,
# or two different rents.
NO_FLAT = [
    "lever-04", "large_holder-01", "large_holder-02", "grey_or_illegal-01",
    "grey_or_illegal-02", "impossible-01", "impossible-02",
]  # fmt: skip


@pytest.mark.parametrize("task_id", sorted(SAME_FIGURES))
def test_prose_gives_the_engine_the_bench_figures(task_id):
    spec = SPECS[task_id]
    found = extract_prose(spec.task)
    assert found.property is not None, task_id
    figures = analyze(found.property, InvestorProfile()).figures
    for key, path in SAME_FIGURES[task_id]:
        expected = spec.figures
        for part in path:
            expected = expected[part]
        assert figures[key] == pytest.approx(expected, abs=0.01), (task_id, key)


@pytest.mark.parametrize("task_id", NO_FLAT)
def test_prose_reads_no_flat_when_it_should_not(task_id):
    assert extract_prose(SPECS[task_id].task).property is None


def test_rent_after_a_rent_verb_is_not_the_price():
    found = extract_prose(
        "Compré un piso de 75 m² en Sevilla por 155.000 € y lo alquilo por 800 € al mes."
    )
    assert (found.property.price, found.property.monthly_rent) == (155000, 800)


def test_two_values_of_a_field_are_left_to_the_model():
    found = extract_prose(
        "Piso de 70 m² en Murcia por 120.000 €. Cobro 600 € pero podría cobrar 650 €."
    )
    assert found.property.monthly_rent is None and found.ambiguous == ["monthly_rent"]


def test_land_value_and_yearly_community():
    found = extract_prose(
        "Piso de 80 m² en Murcia por 167.000 €, valor catastral 95.000 €, de los que "
        "38.000 € son suelo; comunidad 600 € al año."
    )
    assert found.property.land_share_pct == 40 and found.property.community_monthly == 50


def test_ingest_loads_the_flat_and_keeps_the_prose(monkeypatch):
    task = "Piso en Valencia de 70 m² por 180.000 €, alquilado por 850 € al mes. ¿Rentabilidad?"
    props, text = extract_properties(task)
    assert props[0].id == "P1" and props[0].municipality == "Valencia"
    assert text.startswith(task) and "[1 piso cargado en el expediente: P1 (" in text
    monkeypatch.setenv("ARCA_INGEST_PROSE", "0")
    assert extract_properties(task) == ([], task)


def test_a_csv_wins_over_the_prose():
    props, _ = extract_properties("Piso en Madrid por 100.000 €, 60 m².\nprecio;renta\n90000;500")
    assert [p.price for p in props] == [90000]


def test_two_tables_number_flats_consecutively():
    task = "precio;renta\n100000;500\n\nY estos:\nprecio;renta\n200000;900\n300000;1200"
    props, text = extract_properties(task)
    assert [p.id for p in props] == ["P1", "P2", "P3"]
    assert text.count("cargado") == 2


@pytest.mark.parametrize(
    ("cell", "value"),
    [
        ("180.000", 180000),
        ("180000", 180000),
        ("4,5", 4.5),
        ("4.5", 4.5),
        ("1.234,56 €", 1234.56),
        ("1,234.56", 1234.56),
        ("1.250.000", 1250000),
        ("40 %", 40),
    ],
)
def test_parse_number(cell, value):
    assert parse_number(cell) == value


def test_normalise_header():
    assert normalise_header("Precio (€)") == "precio"
    assert normalise_header("Superficie m²") == "superficie_m2"
    assert normalise_header("% suelo") == "suelo"
    assert normalise_header("Valor de Referencia") == "valor_de_referencia"
