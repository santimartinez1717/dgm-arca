"""Public-data tools against responses recorded on 17/11/2026: no network in the tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tool_use import public_data
from tool_use.build_data import _split_municipalities, normalise_name, parse_resolution
from tool_use.tools import default_registry

FIXTURES = Path(__file__).parent / "fixtures" / "public_data"


class FakeHTTP:
    """Serves a recorded body for each URL prefix and remembers what was asked."""

    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, params=None):
        self.calls.append((url, params or {}))
        for prefix, fixture in self.routes.items():
            if url.startswith(prefix):
                body = (FIXTURES / fixture).read_bytes()
                return httpx.Response(200, content=body, request=httpx.Request("GET", url))
        raise AssertionError(f"unexpected URL {url}")


@pytest.fixture
def registry():
    return default_registry()


def use(monkeypatch, **routes) -> FakeHTTP:
    fake = FakeHTTP({getattr(public_data, k): v for k, v in routes.items()})
    monkeypatch.setattr(public_data, "http_get", fake)
    return fake


def test_lookup_by_address_lists_the_dwellings(monkeypatch, registry):
    use(monkeypatch, CARTOCIUDAD="cartociudad_embajadores.txt", CATASTRO="catastro_building.json")
    record = registry.call("lookup_property", {"address": "Calle Embajadores 100, Madrid"})
    assert record.ok, record.error
    result = record.result
    assert result["municipality_code"] == "28079" and result["region"] == "madrid"
    assert result["units"] == 5 and result["units_by_use"]["Residencial"] == 3
    assert len(result["dwellings"]) == 3 and "floor and door" in result["note"]


def test_lookup_floor_and_door_narrow_it_down(monkeypatch, registry):
    use(monkeypatch, CARTOCIUDAD="cartociudad_embajadores.txt", CATASTRO="catastro_building.json")
    two = registry.call(
        "lookup_property", {"address": "Embajadores 100, Madrid", "floor": "2", "door": "b"}
    )
    assert two.ok and two.result["units"] == 2  # two staircases have a 2.º B
    one = registry.call("lookup_property", {"address": "Embajadores 100, Madrid", "floor": "3"})
    assert one.ok and one.result["area_m2"] == 99 and one.result["use"] == "Residencial"
    assert len(one.result["cadastral_ref"]) == 20


def test_lookup_single_unit_and_areas_with_thousands_dot(monkeypatch, registry):
    use(monkeypatch, CATASTRO="catastro_single.json")
    record = registry.call("lookup_property", {"cadastral_ref": "1446401VK4714E"})
    assert record.ok and record.result["area_m2"] == 52949 and record.result["year_built"] == 1999


def test_lookup_errors_reach_the_model(monkeypatch, registry):
    use(monkeypatch, CATASTRO="catastro_error.json")
    record = registry.call("lookup_property", {"cadastral_ref": "0000000XX0000X"})
    assert not record.ok and "NO EXISTE" in record.error
    assert not registry.call("lookup_property", {}).ok


def test_market_rates(monkeypatch, registry):
    use(monkeypatch, BDE_EURIBOR="bde_euribor.json", INE_IRAV="ine_irav.json")
    result = registry.call("get_market_rates", {}).result
    assert result["euribor_12m_pct"] == 3.239 and result["euribor_month"] == "2026-10"
    assert result["irav_pct"] == 2.57 and result["irav_month"] == "2026-10"


def test_rent_reference_reads_zones_and_serpavi(registry):
    barcelona = registry.call("get_rent_reference", {"municipality": "barcelona"}).result
    assert barcelona["stressed_zone"] and barcelona["zone"]["zone_lowers_threshold"]
    assert barcelona["rents_paid"]["eur_m2_month"]["median"] > 10
    madrid = registry.call("get_rent_reference", {"municipality": "28079"}).result
    assert madrid["municipality"] == "Madrid" and not madrid["stressed_zone"]


def test_rent_reference_names_partial_zones_and_aliases(registry):
    donostia = registry.call("get_rent_reference", {"municipality": "San Sebastián"}).result
    assert donostia["stressed_zone"]
    gijon = registry.call("get_rent_reference", {"municipality": "Gijón"}).result
    assert gijon["stressed_zone"] and not gijon["zone"]["whole_municipality"]
    assert not gijon["zone"]["zone_lowers_threshold"]  # Asturias keeps the general threshold
    vitoria = registry.call("get_rent_reference", {"municipality": "Vitoria"}).result
    assert vitoria["municipality"].startswith("Vitoria") and vitoria["stressed_zone"]


def test_zone_list_parsing_handles_boe_typos():
    names = _split_municipalities("Abrera, Manresa el Masnou, Gijón (barrio de A, y B), i Vic.")
    assert names == ["Abrera", "Manresa", "el Masnou", "Gijón (barrio de A, y B)", "Vic"]
    assert normalise_name("L'Hospitalet de Llobregat") == "hospitalet de llobregat"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Coruña, A", "coruna"),  # INE writes the article at the end
        ("A Coruña", "coruna"),
        ("Rozas de Madrid, Las", "rozas de madrid"),
        ("Olot", "olot"),  # starts like the article "o"
        ("Alella", "alella"),  # starts like "a"
        ("Lasarte-Oria", "lasarte-oria"),  # starts like "la"
        ("Móra la Nova", "mora la nova"),
    ],
)
def test_normalise_name_only_strips_whole_articles(name, expected):
    assert normalise_name(name) == expected


def test_parse_resolution_reads_the_table():
    xml = """<documento><metadatos><fecha_publicacion>20260202</fecha_publicacion></metadatos>
    <texto><table><tbody><tr><td>País Vasco.</td><td>Hernani.</td>
    <td>Tres años desde el día siguiente a la publicación de la presente resolución.</td>
    <td>... titular de cinco o más inmuebles urbanos de uso residencial ...</td>
    <td>Sí, conforme a la Orden.</td><td>enlaces</td></tr></tbody></table></texto></documento>"""
    [zone] = parse_resolution("BOE-TEST", xml)
    assert zone["municipality"] == "Hernani" and zone["valid_from"] == "2026-02-03"
    assert zone["valid_until"] == "2029-02-02"
    assert zone["lowers_large_holder_threshold"] and zone["caps_unrented"]


def test_built_data_files_are_consistent():
    zones = json.loads(public_data.ZONES_FILE.read_text(encoding="utf-8"))["zones"]
    assert len(zones) > 300 and all(z["valid_from"] < z["valid_until"] for z in zones)
    rows = public_data._serpavi()
    assert len(rows) > 2000 and all(len(r["code"]) == 5 for r in rows)
