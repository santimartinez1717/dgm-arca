"""Tools that query official Spanish data: cadastre, interest rates, rent references.

* ``lookup_property``: CartoCiudad (IGN) geocodes an address and returns its cadastral
  reference; the Catastro's free web service returns use, built area and year of each unit.
  Neither the cadastral value nor the reference value is public: they need a certificate.
* ``get_market_rates``: 12-month Euribor (Banco de España) and IRAV, the index that caps
  annual rent updates (INE). No API key.
* ``get_rent_reference``: whether a municipality is a declared stressed zone today, with the
  two facts of its declaration that change the legal rent (from the BOE resolutions), and the
  rents tenants actually pay there (SERPAVI). Both read files built by ``build_data.py``.

All HTTP goes through ``http_get`` so the tests can replace it with recorded responses.
Every failure becomes a clear error the model can read and explain.
"""

from __future__ import annotations

import csv
import functools
import json
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import httpx
from pydantic import Field

from tool_use.build_data import SERPAVI_FILE, ZONES_FILE, normalise_name
from tool_use.regions import PROVINCE_REGION
from tool_use.registry import tool

CARTOCIUDAD = "https://www.cartociudad.es/geocoder/api/geocoder/findJsonp"
CATASTRO = (
    "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Consulta_DNPRC"
)
BDE_EURIBOR = "https://app.bde.es/bierest/resources/srdatosapp/favoritas"
INE_IRAV = "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IRAV1"
TIMEOUT = 15.0
MAX_UNITS_LISTED = 25

FORAL_PROVINCES = {"01", "20", "31", "48"}  # own cadastres, not in the Catastro service


def http_get(url: str, params: dict[str, Any] | None = None) -> httpx.Response:
    """The single HTTP entry point of the public-data tools (replaced in the tests)."""
    response = httpx.get(url, params=params, timeout=TIMEOUT, headers={"Accept": "*/*"})
    response.raise_for_status()
    return response


# --------------------------------------------------------------------------- cadastre


def _geocode(address: str) -> dict[str, Any]:
    text = http_get(CARTOCIUDAD, {"q": address}).text.strip()
    payload = json.loads(re.sub(r"^callback\((.*)\)$", r"\1", text, flags=re.S))
    if not payload or not payload.get("refCatastral"):
        raise ValueError(
            f"CartoCiudad found no building with a cadastral reference for {address!r}"
        )
    return payload


def _area(value: str | None) -> int | None:
    """Catastro writes areas with a thousands dot: '1.567' is 1567 m2."""
    return int(value.replace(".", "")) if value else None


def _full_rc(rc: dict[str, str]) -> str:
    return rc["pc1"] + rc["pc2"] + rc["car"] + rc["cc1"] + rc["cc2"]


def _unit(rc: dict[str, str], loint: dict[str, str], debi: dict[str, str]) -> dict[str, Any]:
    return {
        "cadastral_ref": _full_rc(rc),
        "use": debi.get("luso"),
        "area_m2": _area(debi.get("sfc")),
        "year_built": int(debi["ant"]) if debi.get("ant") else None,
        "staircase": loint.get("es"),
        "floor": loint.get("pt"),
        "door": loint.get("pu"),
    }


def _same(a: str | None, b: str | None) -> bool:
    """Floors and doors as people write them: '2' matches '02', 'b' matches 'B'."""
    norm = lambda x: (x or "").strip().upper().lstrip("0") or "0"  # noqa: E731
    return norm(a) == norm(b)


@tool
def lookup_property(
    address: Annotated[str, Field(min_length=3, max_length=200)] | None = None,
    cadastral_ref: Annotated[str, Field(min_length=14, max_length=20)] | None = None,
    floor: Annotated[str, Field(max_length=5)] | None = None,
    door: Annotated[str, Field(max_length=5)] | None = None,
) -> dict[str, Any]:
    """Look up a property in the Spanish cadastre: use, built area, year built, municipality.

    Only call it when the user gives an address or a cadastral reference; never make one
    up. A building with several units returns the list of dwellings unless floor and door
    identify one. Use this to check the m2 of a
    listing or to find the municipality and region of an address. It does not return the
    cadastral value or the reference value (they are not public).

    Args:
        address: Only the street, number and municipality the user gave (no floor, door or
            staircase: those go in floor and door).
        cadastral_ref: Cadastral reference, 14 characters (building) or 20 (unit).
        floor: Floor of the dwelling, e.g. "2", "BJ" for ground floor.
        door: Door of the dwelling, e.g. "B" or "IZ".
    """
    if not address and not cadastral_ref:
        raise ValueError("give an address or a cadastral_ref")
    found: dict[str, Any] = {}
    if address and not cadastral_ref:
        geo = _geocode(address)
        cadastral_ref = geo["refCatastral"]
        found = {
            "matched_address": f"{geo.get('tip_via', '')} {geo.get('address', '')} "
            f"{geo.get('portalNumber', '')}, {geo.get('muni', '')}".strip(),
            "postal_code": geo.get("postalCode"),
        }
        if geo.get("provinceCode") in FORAL_PROVINCES:
            raise ValueError("País Vasco and Navarra have their own cadastre, not covered")

    data = http_get(CATASTRO, {"RefCat": cadastral_ref.upper()}).json()["consulta_dnprcResult"]
    if "lerr" in data:
        errors = data["lerr"]
        errors = errors.get("err", []) if isinstance(errors, dict) else errors
        message = errors[0].get("des") if errors else "unknown error"
        raise ValueError(f"Catastro: {message}")

    if "bico" in data:  # a single unit
        bi = data["bico"]["bi"]
        loine = bi["dt"]["loine"]
        lourb = bi["dt"]["locs"]["lous"]["lourb"]
        units = [_unit(bi["idbi"]["rc"], lourb.get("loint", {}), bi["debi"])]
        cadastral_address = bi.get("ldt")
    else:
        rows = data["lrcdnp"]["rcdnp"]
        loine = rows[0]["dt"]["loine"]
        units = [
            _unit(r["rc"], r["dt"]["locs"]["lous"]["lourb"].get("loint", {}), r["debi"])
            for r in rows
        ]
        dir_ = rows[0]["dt"]["locs"]["lous"]["lourb"]["dir"]
        cadastral_address = f"{dir_.get('tv', '')} {dir_.get('nv', '')} {dir_.get('pnp', '')}"

    province = loine["cp"].zfill(2)
    found.update(
        {
            "cadastral_address": cadastral_address,
            "municipality_code": province + loine["cm"].zfill(3),
            "region": PROVINCE_REGION.get(province),
        }
    )
    if floor or door:
        units = [
            u
            for u in units
            if (not floor or _same(u["floor"], floor)) and (not door or _same(u["door"], door))
        ]
        if not units:
            raise ValueError(f"no unit at floor {floor!r}, door {door!r} in {cadastral_ref}")
    if len(units) == 1:
        return {**found, **units[0]}

    dwellings = [u for u in units if (u["use"] or "").lower().startswith("residencial")]
    uses: dict[str, int] = {}
    for u in units:
        uses[u["use"]] = uses.get(u["use"], 0) + 1
    return {
        **found,
        "building_ref": cadastral_ref[:14].upper(),
        "units": len(units),
        "units_by_use": uses,
        "year_built": units[0]["year_built"],
        "dwellings": [
            {k: u[k] for k in ("staircase", "floor", "door", "area_m2", "cadastral_ref")}
            for u in dwellings[:MAX_UNITS_LISTED]
        ],
        "note": "several units: call again with floor and door to get one dwelling",
    }


# --------------------------------------------------------------------------- market rates


@tool
def get_market_rates() -> dict[str, Any]:
    """Latest 12-month Euribor (mortgage reference) and IRAV (cap on yearly rent updates).

    Use this when a calculation needs the current mortgage rate or when the user asks how
    much a rent can rise this year.
    """
    euribor = http_get(BDE_EURIBOR, {"idioma": "es", "series": "D_1NBAF472"}).json()[0]
    irav = http_get(INE_IRAV, {"nult": 1}).json()["Data"][-1]
    return {
        "euribor_12m_pct": euribor["valor"],
        "euribor_month": euribor["fechaValor"][:7],
        "irav_pct": irav["Valor"],
        "irav_month": f"{irav['Anyo']}-{irav['FK_Periodo']:02d}",
        "sources": "Banco de España (serie D_1NBAF472) e INE (IRAV)",
        "note": "a mortgage rate is usually Euribor plus a spread agreed with the bank",
    }


# --------------------------------------------------------------------------- rent reference


@functools.cache
def _zones() -> list[dict[str, Any]]:
    return json.loads(Path(ZONES_FILE).read_text(encoding="utf-8"))["zones"]


@functools.cache
def _serpavi() -> list[dict[str, str]]:
    with Path(SERPAVI_FILE).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _names(name: str) -> set[str]:
    """All the ways a bilingual name can be written: 'Donostia / San Sebastián' -> 3 forms."""
    return {normalise_name(n) for n in [name, *name.split("/")]} - {""}


def _matches(query: str, name: str) -> bool:
    return bool(_names(query) & _names(name))


def declared_zones(municipality: str) -> list[dict[str, Any]]:
    """The stressed-zone declarations of a municipality in force today (empty if none)."""
    today = date.today().isoformat()
    return [
        z
        for z in _zones()
        if _names(municipality) & set(z["aliases"]) and z["valid_from"] <= today <= z["valid_until"]
    ]


@tool
def get_rent_reference(
    municipality: Annotated[str, Field(min_length=2, max_length=100)],
    province: Annotated[str, Field(max_length=60)] | None = None,
) -> dict[str, Any]:
    """Rent reference of a Spanish municipality: stressed-zone status and actual rents paid.

    Says whether the municipality is a declared stressed residential zone today, and if so
    whether its declaration lowers the large-holder threshold to 5 dwellings and whether the
    index cap also applies to dwellings with no previous contract (the arguments
    zone_lowers_threshold and declaration_caps_unrented of other tools). Also returns the
    rents tenants actually pay for flats there (SERPAVI, from tax returns): useful as the
    market rent, usually below the asking prices of listings.

    Args:
        municipality: Municipality name, e.g. "Barcelona", or its 5-digit INE code.
        province: Province, only needed if several municipalities share the name.
    """
    by_code = municipality.isdigit()
    rows = [
        r
        for r in _serpavi()
        if (r["code"] == municipality.zfill(5) if by_code else _matches(municipality, r["name"]))
    ]
    if not rows and not by_code:  # "Vitoria" for "Vitoria-Gasteiz"
        prefix = normalise_name(municipality)
        rows = [r for r in _serpavi() if any(n.startswith(prefix) for n in _names(r["name"]))]
    if province and not by_code:
        rows = [r for r in rows if _matches(province, r["province"])] or rows
    if len(rows) > 1:
        raise ValueError(
            "several municipalities match; pass province: "
            + ", ".join(f"{r['name']} ({r['province']})" for r in rows[:10])
        )
    name = rows[0]["name"] if rows else municipality

    zones = declared_zones(name)
    out: dict[str, Any] = {"municipality": name}
    if zones:
        zone = max(zones, key=lambda z: z["valid_from"])  # the latest declaration wins
        out["stressed_zone"] = True
        out["zone"] = {
            "whole_municipality": not any(z["partial"] for z in zones),
            "areas": [z["area"] for z in zones if z["partial"]],
            "valid_until": zone["valid_until"],
            "zone_lowers_threshold": zone["lowers_large_holder_threshold"],
            "declaration_caps_unrented": zone["caps_unrented"],
            "source": zone["source"],
        }
    else:
        out["stressed_zone"] = False
    if rows:
        r = rows[0]
        out["rents_paid"] = {
            "year": int(r["year"]),
            "contracts": int(r["n_contracts"]),
            "eur_m2_month": {
                "p25": float(r["eur_m2_p25"]),
                "median": float(r["eur_m2_median"]),
                "p75": float(r["eur_m2_p75"]),
            },
            "median_monthly_rent": float(r["monthly_rent_median"]),
            "median_area_m2": float(r["area_m2_median"]),
            "source": "SERPAVI (MIVAU), flats, rents declared in income tax returns",
        }
    else:
        out["rents_paid"] = None
        out["note"] = "no SERPAVI data (municipality not found or under 10 contracts)"
    out["legal_index_note"] = (
        "the legal SERPAVI index for a specific dwelling (needed by legal_rent_cap) comes from "
        "serpavi.mivau.gob.es with its cadastral reference; these figures are market rents"
    )
    return out


PUBLIC_DATA_TOOLS = (lookup_property, get_market_rates, get_rent_reference)
