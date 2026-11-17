"""Build the small data files the public-data tools read, from their official sources.

Two datasets, both regenerated with this script and committed because they are small:

* ``zones``: declared stressed residential market zones, parsed from the quarterly resolutions
  of the Ministry of Housing in the BOE (Ley 12/2023 art. 18.2.d). For each municipality: the
  period of validity, whether the declaration lowers the large-holder threshold to five
  dwellings, and whether the reference-index cap of LAU art. 17.7 also applies to dwellings
  with no previous contract. These are two arguments of ``legal_rent_cap`` the user rarely
  knows.
* ``serpavi``: rent statistics by municipality from the SERPAVI database of the Ministry
  (p25, median and p75 of the monthly rent in euros per m2, collective housing), the market
  reference the yield tools need.

Run::

    uv run python -m tool_use.build_data zones
    uv run --with openpyxl python -m tool_use.build_data serpavi --xlsx path/to/serpavi.xlsx

Add the BOE id of each new quarterly resolution to ``ZONE_RESOLUTIONS`` and run it again.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent / "data"
ZONES_FILE = DATA_DIR / "stressed_zones.json"
SERPAVI_FILE = DATA_DIR / "serpavi_municipalities.csv"
MIN_CONTRACTS = 10  # fewer contracts than this and a median says little

# Listed on https://www.mivau.gob.es/vivienda/alquila-bien-es-tu-derecho/serpavi/
# consultar-zonas-de-mercado-residencial-tensionado (checked 17/11/2026).
ZONE_RESOLUTIONS = [
    "BOE-A-2024-5214",
    "BOE-A-2024-20576",
    "BOE-A-2025-1721",
    "BOE-A-2025-8636",
    "BOE-A-2025-15728",
    "BOE-A-2025-21901",
    "BOE-A-2026-2448",
    "BOE-A-2026-9175",
    "BOE-A-2026-16532",
    "BOE-A-2026-23088",
]
BOE_XML = "https://www.boe.es/diario_boe/xml.php?id={}"

# Typos in the BOE lists (a missing comma), fixed by hand.
NAME_FIXES = {"Manresa el Masnou": ["Manresa", "el Masnou"]}
PARTIAL_MARKERS = ("(", "excepto", "distrito", "barrio", "núcleo")


def normalise_name(name: str) -> str:
    """Lowercase, no accents, no leading article: 'L'Hospitalet' -> 'hospitalet'."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9/' -]", " ", text)
    text = re.sub(r"^(el|la|les|els|los|las|a|o|l')\s*", "", text.strip())
    return " ".join(text.replace("'", " ").split())


def _cells(row_html: str) -> list[str]:
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)
    return [html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip() for c in cells]


def _split_municipalities(cell: str) -> list[str]:
    """'Abrera, Alella, ... i Vilassar de Mar.' -> names; keeps '(barrio ...)' together."""
    cell = re.sub(r",\s*(excepto[^,]*)$", r" (\1)", cell.rstrip("."))
    parts, depth, current = [], 0, ""
    for char in cell:  # split on commas outside parentheses
        depth += char == "("
        depth -= char == ")"
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    names = []
    for part in (p.strip() for p in parts):
        part = re.sub(r"^(i|y)\s+", "", part)
        if part:
            names.extend(NAME_FIXES.get(part, [part]))
    return names


def parse_resolution(boe_id: str, xml: str) -> list[dict]:
    published = re.search(r"<fecha_publicacion>(\d{8})</fecha_publicacion>", xml).group(1)
    pub = date(int(published[:4]), int(published[4:6]), int(published[6:]))
    body = xml[xml.find("<tbody") : xml.find("</tbody>")]
    zones = []
    for row in re.findall(r"<tr>(.*?)</tr>", body, re.S):
        cells = _cells(row)
        if len(cells) < 5:
            continue
        region, municipalities, validity, large_holder, art_17_7 = cells[:5]
        if not validity.startswith("Tres años desde el día siguiente a la publicación"):
            raise ValueError(f"{boe_id}: unexpected validity text: {validity[:80]}")
        for name in _split_municipalities(municipalities):
            base = name.split("(")[0].strip()
            zones.append(
                {
                    "municipality": base,
                    "aliases": [normalise_name(a) for a in base.split("/")],
                    "region": region.rstrip("."),
                    "partial": any(m in name.lower() for m in PARTIAL_MARKERS),
                    "area": name if name != base else "",
                    "valid_from": (pub + timedelta(days=1)).isoformat(),
                    "valid_until": pub.replace(year=pub.year + 3).isoformat(),
                    "lowers_large_holder_threshold": "cinco o más" in large_holder,
                    "caps_unrented": art_17_7.lower().startswith("sí"),
                    "source": boe_id,
                }
            )
    return zones


def build_zones() -> None:
    zones: list[dict] = []
    with httpx.Client(timeout=30) as client:
        for boe_id in ZONE_RESOLUTIONS:
            xml = client.get(BOE_XML.format(boe_id)).raise_for_status().text
            found = parse_resolution(boe_id, xml)
            print(f"{boe_id}: {len(found)} zones")
            zones.extend(found)
    DATA_DIR.mkdir(exist_ok=True)
    lines = ",\n".join(json.dumps(z, ensure_ascii=False) for z in zones)
    header = json.dumps({"built": date.today().isoformat(), "resolutions": ZONE_RESOLUTIONS})
    ZONES_FILE.write_text(f'{header[:-1]}, "zones": [\n{lines}\n]}}\n')
    print(f"{len(zones)} zones -> {ZONES_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="dataset", required=True)
    sub.add_parser("zones")
    serpavi = sub.add_parser("serpavi")
    serpavi.add_argument("--xlsx", required=True)
    args = parser.parse_args()
    if args.dataset == "zones":
        build_zones()
    else:
        build_serpavi(Path(args.xlsx))


SERPAVI_URL = (
    "https://cdn.mivau.gob.es/portal-web-mivau/vivienda/serpavi/"
    "2026-03_09_bd_SERPAVI_2011-2024%20-%20DEFINITIVO%20WEB_v2.xlsx"
)
SERPAVI_FIELDS = {  # output key -> column prefix; VC = collective housing (flats)
    "n_contracts": "BI_ALVHEPCO_TVC",
    "eur_m2_p25": "ALQM2_LV_25_VC",
    "eur_m2_median": "ALQM2_LV_M_VC",
    "eur_m2_p75": "ALQM2_LV_75_VC",
    "monthly_rent_median": "ALQTBID12_M_VC",
    "area_m2_median": "SLVM2_M_VC",
}


def build_serpavi(xlsx: Path) -> None:
    """Latest year with data for each municipality, flats only (``VC``).

    The figures are rents declared in income tax returns (modelo 100) for contracts in force
    that year, crossed with the cadastre: what tenants actually pay, not asking prices.
    Download the workbook (71 MB) from ``SERPAVI_URL`` first; it is not kept in the repo.
    """
    import openpyxl

    sheet = openpyxl.load_workbook(xlsx, read_only=True)["Municipios"]
    rows = sheet.iter_rows(values_only=True)
    header = {name: i for i, name in enumerate(next(rows))}
    years = sorted({int(h[-2:]) for h in header if h.startswith("ALQM2_LV_M_VC_")}, reverse=True)
    out = []
    for row in rows:
        code = row[header["CUMUN"]]
        if not code:
            continue
        for year in years:
            n = row[header[f"BI_ALVHEPCO_TVC_{year:02d}"]]
            if not isinstance(n, int | float) or n < MIN_CONTRACTS:  # "<5"-style or empty
                continue
            values = [row[header[f"{prefix}_{year:02d}"]] for prefix in SERPAVI_FIELDS.values()]
            values = [round(v, 2) if isinstance(v, float) else v for v in values]
            out.append([code, row[header["NMUN"]], row[header["NPRO"]], 2000 + year, *values])
            break
    DATA_DIR.mkdir(exist_ok=True)
    with SERPAVI_FILE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "name", "province", "year", *SERPAVI_FIELDS])
        writer.writerows(out)
    municipalities = out
    print(f"{len(municipalities)} municipalities -> {SERPAVI_FILE}")


if __name__ == "__main__":
    main()
