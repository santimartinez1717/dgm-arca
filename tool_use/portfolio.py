"""The investor's portfolio: a tool with state and with an observable effect.

``save_to_portfolio`` writes a row to a SQLite file; ``get_portfolio`` reads it back and
says whether the owner is a large holder ("gran tenedor", Ley 12/2023 art. 3.k). The state
matters for later calls: whether ``legal_rent_cap`` applies the reference-index cap depends
on how many dwellings and square metres the owner already has, so "save, then check the
portfolio, then compute the legal rent" is a chain the model has to follow in order.

The database lives in ``outputs/portfolio.sqlite`` (outside git) unless ``ARCA_PORTFOLIO_DB``
points elsewhere; the tests use a temporary file.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from rlm import realestate_rules as rules
from tool_use.registry import tool

DEFAULT_DB = Path("outputs/portfolio.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    municipality TEXT NOT NULL,
    area_m2 REAL,
    stressed_zone INTEGER NOT NULL,
    purchase_price REAL,
    monthly_rent REAL,
    cadastral_ref TEXT UNIQUE,
    added_at TEXT NOT NULL
)
"""


def db_path() -> Path:
    return Path(os.environ.get("ARCA_PORTFOLIO_DB", DEFAULT_DB))


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    _allow_missing_area(conn)
    return conn


def _allow_missing_area(conn: sqlite3.Connection) -> None:
    """Databases created before 2026-11-23 required area_m2: copy them to the current schema."""
    columns = {row["name"]: row["notnull"] for row in conn.execute("PRAGMA table_info(properties)")}
    if not columns.get("area_m2"):
        return
    with conn:
        conn.execute("ALTER TABLE properties RENAME TO properties_old")
        conn.execute(SCHEMA)
        conn.execute("INSERT INTO properties SELECT * FROM properties_old")
        conn.execute("DROP TABLE properties_old")


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


@tool(requires_confirmation=True)
def save_to_portfolio(
    label: Annotated[str, Field(min_length=1, max_length=200)],
    municipality: Annotated[str, Field(min_length=1, max_length=100)],
    stressed_zone: bool,
    purchase_price: Annotated[float, Field(ge=0)] | None = None,
    monthly_rent: Annotated[float, Field(ge=0)] | None = None,
    area_m2: Annotated[float, Field(gt=0)] | None = None,
    cadastral_ref: Annotated[str, Field(min_length=14, max_length=20)] | None = None,
) -> dict[str, Any]:
    """Save a dwelling the user owns or has bought to their portfolio (writes to a database).

    Only call it when the user asks to save, add or register a property. Saving the same
    cadastral reference twice does not duplicate it.

    Args:
        label: Short name for the dwelling, usually its address.
        municipality: Municipality where it is, e.g. "Barcelona".
        stressed_zone: True if it is in a declared stressed residential market zone.
        purchase_price: Purchase price in euros, if known.
        monthly_rent: Current monthly rent in euros, if rented.
        area_m2: Built residential area in square metres, only if the user gives it.
        cadastral_ref: Cadastral reference (20 characters), if known.
    """
    with closing(_connect()) as conn, conn:
        if cadastral_ref:
            row = conn.execute(
                "SELECT id FROM properties WHERE cadastral_ref = ?", (cadastral_ref.upper(),)
            ).fetchone()
            if row:
                return {"saved": False, "id": row["id"], "reason": "already in the portfolio"}
        cursor = conn.execute(
            "INSERT INTO properties (label, municipality, area_m2, stressed_zone, purchase_price,"
            " monthly_rent, cadastral_ref, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                label.strip(),
                municipality.strip(),
                area_m2,
                int(stressed_zone),
                purchase_price,
                monthly_rent,
                cadastral_ref.upper() if cadastral_ref else None,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        new_id = cursor.lastrowid
    out: dict[str, Any] = {"saved": True, "id": new_id}
    if area_m2 is None:
        out["warnings"] = [
            "superficie no dada: el piso se guarda sin m² y el umbral de 1.500 m² de gran "
            "tenedor no la cuenta; pide la superficie al usuario"
        ]
    out["portfolio"] = _summary(_rows(), None, False)
    return out


def _rows() -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM properties ORDER BY id")]
    for row in rows:
        row["stressed_zone"] = bool(row["stressed_zone"])
        row.pop("added_at", None)
    return rows


def _summary(
    rows: list[dict[str, Any]], municipality: str | None, zone_lowers_threshold: bool
) -> dict[str, Any]:
    total_m2 = sum(r["area_m2"] for r in rows if r["area_m2"] is not None)
    without_area = sum(r["area_m2"] is None for r in rows)
    in_zone = [
        r
        for r in rows
        if municipality
        and r["stressed_zone"]
        and _normalise(r["municipality"]) == _normalise(municipality)
    ]
    large = rules.is_large_holder(
        dwellings_total=len(rows),
        residential_m2=total_m2,
        dwellings_in_zone=len(in_zone),
        zone_lowers_threshold=zone_lowers_threshold,
    )
    if len(rows) > 10:
        reason = "más de 10 viviendas"
    elif total_m2 > 1500:
        reason = "más de 1.500 m² residenciales"
    elif large:
        reason = f"5 o más viviendas en la zona tensionada de {municipality}"
    else:
        reason = "no supera ningún umbral del art. 3.k de la Ley 12/2023"
        if without_area:
            reason += f" (sin contar la superficie de {without_area} piso(s) sin m²)"
    return {
        "dwellings": len(rows),
        "residential_m2": rules.round2(total_m2),
        "dwellings_without_area": without_area,
        "dwellings_in_zone": len(in_zone) if municipality else None,
        "large_holder": large,
        "large_holder_reason": reason,
    }


@tool
def get_portfolio(
    municipality: str | None = None,
    zone_lowers_threshold: bool = False,
) -> dict[str, Any]:
    """List the user's saved dwellings and say whether they are a large holder ("gran tenedor").

    A large holder has more than 10 dwellings or more than 1,500 m2 of residential area; in
    a stressed zone whose declaration lowers the threshold, 5 or more dwellings in that zone.
    Call it before legal_rent_cap when you need to know if the landlord is a large holder.

    Args:
        municipality: Municipality of the stressed zone to count dwellings in, if relevant.
        zone_lowers_threshold: True if that zone's declaration lowers the threshold to 5.
    """
    rows = _rows()
    return {"properties": rows, **_summary(rows, municipality, zone_lowers_threshold)}


PORTFOLIO_TOOLS = (save_to_portfolio, get_portfolio)
