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
    props, text = extract_properties(task)
    assert props == [] and text == task


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
