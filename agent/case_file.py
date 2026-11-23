"""The case file ("expediente"): everything the agent knows about one investor's case.

The loop keeps it pinned at the top of the context, so the facts of the case never get lost
in the middle of a long conversation, and the tools that work on the case read it from
``current()`` instead of receiving it as an argument (a 1.7B model copies ids well and long
JSON badly). Every number the rule engine produces is stored as a ``Figure`` together with
the tool that produced it: that is what the auditor checks the final answer against.

Cases persist per ``session_id`` in SQLite (``ARCA_CASE_DB``), so a second turn of the same
session can answer the open questions of the first one.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_DB = Path("outputs/cases.sqlite")


class InvestorProfile(BaseModel):
    """Who invests: what decides the large-holder status, the financing and the goal."""

    region: str | None = None
    properties_owned: int | None = None
    properties_owned_stressed: int | None = None
    area_owned_m2: float | None = None
    zone_lowers_threshold: bool | None = None
    financing: bool | None = None
    down_payment_pct: float | None = None
    interest_rate_pct: float | None = None
    loan_years: int | None = None
    marginal_tax_rate_pct: float | None = None
    target_net_yield_pct: float | None = None


class Property(BaseModel):
    """One dwelling under analysis. Money in euros, percentages as written (4 means 4 %)."""

    id: str
    municipality: str | None = None
    region: str | None = None
    price: float | None = None
    reference_value: float | None = None
    new_build: bool = False
    ajd_rate_pct: float | None = None
    area_m2: float | None = None
    monthly_rent: float | None = None
    previous_rent: float | None = None
    previously_rented: bool | None = None
    stressed_zone: bool | None = None
    index_upper_eur_m2: float | None = None
    cadastral_value: float | None = None
    land_share_pct: float | None = None
    contract_date: date | None = None
    notary_registry: float = 0.0
    agency_fee: float = 0.0
    renovation: float = 0.0
    ibi: float = 0.0
    community_monthly: float = 0.0
    insurance: float = 0.0
    vacant_months: float = 0.0
    maintenance_pct: float = 0.0
    management_pct: float = 0.0
    rehabilitation_last_2y: bool = False
    tenant_age: int | None = None


class Figure(BaseModel):
    """A number the rule engine produced, with where it came from."""

    property_id: str | None
    name: str
    value: float
    unit: str
    tool: str
    scenario: str = "base"


class Assumption(BaseModel):
    """A value the agent used without the user giving it. Always shown in the answer."""

    property_id: str | None
    field: str
    value: Any
    reason: str


class CaseFile(BaseModel):
    session_id: str
    profile: InvestorProfile = Field(default_factory=InvestorProfile)
    properties: dict[str, Property] = Field(default_factory=dict)
    figures: list[Figure] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    # short citation keys ("K1") of the passages search_knowledge_base returned -> source
    sources: dict[str, str] = Field(default_factory=dict)

    def cite(self, source: str) -> str:
        """The citation key of a passage, reusing the key if it was retrieved before."""
        for key, known in self.sources.items():
            if known == source:
                return key
        key = f"K{len(self.sources) + 1}"
        self.sources[key] = source
        return key

    def property(self, property_id: str) -> Property:
        """The property with this id, or a ValueError listing the ids that exist."""
        if property_id in self.properties:
            return self.properties[property_id]
        lowered = {k.lower(): k for k in self.properties}
        if property_id.lower() in lowered:
            return self.properties[lowered[property_id.lower()]]
        raise ValueError(
            f"unknown property_id {property_id!r}; the case file has: "
            + (", ".join(self.properties) or "no properties yet")
        )

    def add_figure(
        self,
        name: str,
        value: float,
        unit: str,
        tool: str,
        property_id: str | None = None,
        scenario: str = "base",
    ) -> None:
        """Record a figure, replacing an older one with the same property, name and scenario."""
        self.figures = [
            f
            for f in self.figures
            if (f.property_id, f.name, f.scenario) != (property_id, name, scenario)
        ]
        self.figures.append(
            Figure(
                property_id=property_id,
                name=name,
                value=float(value),
                unit=unit,
                tool=tool,
                scenario=scenario,
            )
        )

    def add_assumption(self, field: str, value: Any, reason: str, property_id: str | None = None):
        key = (property_id, field)
        if any((a.property_id, a.field) == key for a in self.assumptions):
            return
        self.assumptions.append(
            Assumption(property_id=property_id, field=field, value=value, reason=reason)
        )

    def ask(self, question: str) -> None:
        if question not in self.open_questions:
            self.open_questions.append(question)

    def render(self, max_figures: int = 40) -> str:
        """Compact text block for the top of the context: profile, properties, figures."""
        lines = [f"CASE FILE (session {self.session_id})"]
        profile = self.profile.model_dump(exclude_none=True)
        lines.append("Investor: " + (_kv(profile) or "nothing known yet"))
        if self.properties:
            lines.append("Properties:")
            for p in self.properties.values():
                data = p.model_dump(exclude_none=True, exclude={"id"})
                data = {k: v for k, v in data.items() if v not in (0, 0.0, False)}
                lines.append(f"- {p.id}: {_kv(data)}")
        else:
            lines.append("Properties: none yet")
        base = [f for f in self.figures if f.scenario == "base"]
        if base:
            lines.append("Figures already computed by the engine (base scenario):")
            by_property: dict[str | None, list[Figure]] = {}
            for f in base[-max_figures:]:
                by_property.setdefault(f.property_id, []).append(f)
            for pid, figures in by_property.items():
                values = ", ".join(f"{f.name}={_num(f.value)}" for f in figures)
                lines.append(f"- {pid or 'case'}: {values}")
        scenarios: dict[tuple[str | None, str], list[Figure]] = {}
        for f in self.figures:
            if f.scenario != "base":
                scenarios.setdefault((f.property_id, f.scenario), []).append(f)
        if scenarios:
            lines.append("Scenarios (what_if):")
            for (pid, name), figures in scenarios.items():
                values = ", ".join(f"{f.name}={_num(f.value)}" for f in figures)
                lines.append(f"- {pid} [{name}]: {values}")
        if self.assumptions:
            lines.append("Assumptions (tell the user):")
            # Fifteen screened flats repeat the same assumption fifteen times: one line each.
            grouped: dict[tuple[str, str], list[Assumption]] = {}
            for a in self.assumptions:
                grouped.setdefault((a.field, a.reason), []).append(a)
            for (name, reason), items in grouped.items():
                if len(items) == 1:
                    a = items[0]
                    where = f"{a.property_id} " if a.property_id else ""
                    lines.append(f"- {where}{name} = {_kv({'': a.value})[1:]} ({reason})")
                    continue
                values = {_kv({"": a.value})[1:] for a in items}
                ids = ", ".join(a.property_id or "case" for a in items)
                if len(values) == 1:
                    lines.append(f"- {name} = {values.pop()} in {ids} ({reason})")
                else:
                    per = ", ".join(f"{a.property_id}={_kv({'': a.value})[1:]}" for a in items)
                    lines.append(f"- {name}: {per} ({reason})")
        if self.open_questions:
            lines.append("Open questions for the user:")
            lines.extend(f"- {q}" for q in self.open_questions)
        return "\n".join(lines)


def _num(value: float) -> str:
    return f"{value:g}" if abs(value) < 1e6 else f"{value:.0f}"


def _kv(data: dict[str, Any]) -> str:
    def fmt(v: Any) -> str:
        if isinstance(v, float):
            return _num(v)
        if isinstance(v, date):
            return v.isoformat()
        return str(v)

    return ", ".join(f"{k}={fmt(v)}" for k, v in data.items())


# --------------------------------------------------------------------------- active case

_CURRENT: ContextVar[CaseFile | None] = ContextVar("arca_case_file", default=None)


def current() -> CaseFile:
    """The case file of the agent run in progress. Tools call this to read and write it."""
    case = _CURRENT.get()
    if case is None:
        raise RuntimeError("no active case file: this tool only works inside an agent run")
    return case


@contextlib.contextmanager
def active(case: CaseFile) -> Iterator[CaseFile]:
    """Make ``case`` the active case file for the duration of the block."""
    token = _CURRENT.set(case)
    try:
        yield case
    finally:
        _CURRENT.reset(token)


# --------------------------------------------------------------------------- persistence


def db_path() -> Path:
    return Path(os.environ.get("ARCA_CASE_DB", DEFAULT_DB))


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cases (session_id TEXT PRIMARY KEY, data TEXT NOT NULL,"
        " updated_at TEXT NOT NULL)"
    )
    return conn


def load(session_id: str) -> CaseFile:
    """The stored case of a session, or a new empty one."""
    with contextlib.closing(_connect()) as conn:
        row = conn.execute("SELECT data FROM cases WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        return CaseFile(session_id=session_id)
    return CaseFile.model_validate(json.loads(row[0]))


def save(case: CaseFile) -> None:
    with contextlib.closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO cases (session_id, data, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET data = excluded.data, "
            "updated_at = excluded.updated_at",
            (case.session_id, case.model_dump_json(), datetime.now().isoformat(timespec="seconds")),
        )
