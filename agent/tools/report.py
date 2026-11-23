"""The investment report: a Markdown file whose every number comes from the case file.

``write_investment_report`` is a tool with an observable effect (it writes a file), so it
asks for confirmation like ``save_to_portfolio``. It receives no figures from the model:
only property ids and an optional title in words. It reads the active case file
(``agent.case_file.current()``): the investor's profile, the requested properties, their
engine figures in the base scenario and per lever, the assumptions and the open questions.

The differences between a lever scenario and the base scenario are the only numbers the
report computes itself. It records them in the case as figures of this tool, so the case
file still accounts for every number the report shows (the auditor's grounding rule).

Qualitative levers leave no figure in the case (``what_if`` does not simulate them), so the
report asks the playbook which of them fit each property, the same way ``find_levers`` does.

Reports go to ``outputs/reports/`` (outside git) unless ``ARCA_REPORTS_DIR`` points elsewhere;
the tests use a temporary directory.
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from agent import levers
from agent.analysis import UNITS
from agent.auditor import DISCLAIMER, needs_check, numbers_in
from agent.case_file import CaseFile, Figure, current
from agent.playbook.schema import load_levers
from rlm import realestate_rules as rules
from tool_use.registry import tool

DEFAULT_DIR = Path("outputs/reports")
TOOL_NAME = "write_investment_report"

# Columns of the per-property table and of the lever table, in this order.
TABLE_METRICS = (
    "price",
    "total_investment",
    "effective_rent",
    "net_yield_pct",
    "cash_on_cash_pct",
    "after_tax_yield_pct",
)
LEVER_METRICS = ("net_yield_pct", "cash_on_cash_pct", "income_tax", "after_tax_yield_pct")

LABELS = {
    "price": "Precio",
    "transfer_tax": "ITP",
    "vat": "IVA",
    "stamp_duty": "AJD",
    "total_investment": "Inversión total",
    "itp_rate_pct": "Tipo de ITP",
    "asking_rent": "Renta pedida",
    "legal_max_rent": "Renta máxima legal",
    "effective_rent": "Renta efectiva",
    "collected_rent": "Renta cobrada",
    "operating_costs": "Gastos de explotación",
    "net_income": "Rendimiento neto",
    "gross_yield_pct": "Rentabilidad bruta",
    "net_yield_pct": "Rentabilidad neta",
    "loan": "Préstamo",
    "monthly_payment": "Cuota mensual",
    "annual_cash_flow": "Flujo de caja anual",
    "cash_on_cash_pct": "Cash-on-cash",
    "irpf_depreciation": "Amortización (IRPF)",
    "irpf_net_income": "Rendimiento neto (IRPF)",
    "irpf_reduction_pct": "Reducción del IRPF",
    "irpf_reduced_net_income": "Rendimiento reducido (IRPF)",
    "income_tax": "Impuesto (IRPF)",
    "after_tax_income": "Rendimiento tras impuestos",
    "after_tax_yield_pct": "Rentabilidad tras impuestos",
}
PROFILE_LABELS = {
    "region": ("Comunidad", ""),
    "properties_owned": ("Viviendas que ya tiene", ""),
    "properties_owned_stressed": ("De ellas, en zona tensionada", ""),
    "area_owned_m2": ("Superficie que ya tiene", "m²"),
    "zone_lowers_threshold": ("La zona baja el umbral de gran tenedor", ""),
    "financing": ("Compra con hipoteca", ""),
    "down_payment_pct": ("Entrada", "%"),
    "interest_rate_pct": ("Tipo de interés", "%"),
    "loan_years": ("Plazo del préstamo (años)", ""),
    "marginal_tax_rate_pct": ("Tipo marginal del IRPF", "%"),
    "target_net_yield_pct": ("Rentabilidad neta objetivo", "%"),
}
LEVEL_NAMES = {"legal": "legal", "grey": "zona gris", "illegal_warning": "ilegal"}
SECTIONS = (
    "Resumen",
    "Cifras por piso",
    "Palancas evaluadas",
    "Supuestos",
    "Preguntas abiertas",
    "Aviso",
)


def reports_dir() -> Path:
    return Path(os.environ.get("ARCA_REPORTS_DIR", DEFAULT_DIR))


# --------------------------------------------------------------------------- formatting


def _spanish(value: float, decimals: int) -> str:
    """12345.6 -> 12.345,60 (Spanish notation, which the auditor's parser reads back)."""
    text = f"{abs(value):,.{decimals}f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return f"-{text}" if value < 0 else text


def fmt(value: Any, unit: str = "") -> str:
    """A figure as the report shows it: percentages with two decimals, euros with thousands."""
    if isinstance(value, bool):
        return "sí" if value else "no"
    if not isinstance(value, int | float):
        return str(value)
    if unit == "%":
        return f"{_spanish(value, 2)} %"
    decimals = 0 if float(value).is_integer() else 2
    text = _spanish(value, decimals)
    suffix = {"EUR": " €", "EUR/month": " €/mes", "EUR/year": " €/año", "m²": " m²"}
    return text + suffix.get(unit, "")


def _delta(value: float, unit: str) -> str:
    if value == 0:
        return "sin cambio"
    sign = "+" if value > 0 else "-"
    if unit == "%":
        return f"{sign}{_spanish(abs(value), 2)} pp"
    return sign + fmt(abs(value), unit)


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def slugify(text: str, max_length: int = 60) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_length].strip("-") or "informe"


# --------------------------------------------------------------------------- reading the case


def _resolve_ids(case: CaseFile, property_ids: list[str]) -> list[str]:
    """Canonical ids in the order asked, without repeats; all properties if none asked."""
    if not property_ids:
        if not case.properties:
            raise ValueError("the case file has no properties yet: call record_property first")
        return list(case.properties)
    found, unknown = [], []
    for pid in property_ids:
        try:
            canonical = case.property(pid).id
        except ValueError:
            unknown.append(pid)
            continue
        if canonical not in found:
            found.append(canonical)
    if unknown:
        raise ValueError(
            f"unknown property_id {', '.join(repr(u) for u in unknown)}; the case file has: "
            + (", ".join(case.properties) or "no properties yet")
        )
    return found


def _base(case: CaseFile, pid: str) -> dict[str, Figure]:
    return {f.name: f for f in case.figures if f.property_id == pid and f.scenario == "base"}


def _scenarios(case: CaseFile, pid: str) -> dict[str, dict[str, Figure]]:
    out: dict[str, dict[str, Figure]] = {}
    for f in case.figures:
        if f.property_id == pid and f.scenario != "base" and f.tool != TOOL_NAME:
            out.setdefault(f.scenario, {})[f.name] = f
    return out


def _record_deltas(case: CaseFile, pid: str) -> dict[str, dict[str, float]]:
    """Scenario minus base for the lever metrics, stored in the case as this tool's figures.

    A zero change is returned but not stored: the report writes it as words.
    """
    case.figures = [f for f in case.figures if not (f.property_id == pid and f.tool == TOOL_NAME)]
    base = _base(case, pid)
    deltas: dict[str, dict[str, float]] = {}
    for scenario, figures in _scenarios(case, pid).items():
        for name in LEVER_METRICS:
            if name in figures and name in base:
                change = rules.round2(figures[name].value - base[name].value)
                deltas.setdefault(scenario, {})[name] = change
                if change:
                    case.add_figure(
                        f"{name}_change", change, figures[name].unit, TOOL_NAME, pid, scenario
                    )
    return deltas


def _scenario_label(scenario: str, playbook: dict[str, Any]) -> str:
    if scenario in playbook:
        lever = playbook[scenario]
        return f"{lever.title} (`{scenario}`, {LEVEL_NAMES[lever.level]})"
    parts = scenario.split("+")
    if len(parts) > 1 and all(p in playbook for p in parts):
        return f"Combinadas (`{scenario}`)"
    return f"Escenario `{scenario}`"


def _qualitative(case: CaseFile, pid: str) -> list[dict[str, Any]]:
    """Playbook levers without a figure that fit this property (and the traps to avoid)."""
    found = levers.find(case, pid)
    entries = found["applicable"] + found.get("maybe", [])
    out = [e for e in entries if not e["quantified"]]
    return out + found.get("traps_to_warn_about", [])


def _check_title(title: str | None) -> None:
    if title is None:
        return
    figures = [w for w, value, unit in numbers_in(title) if needs_check(w, value, unit)]
    if figures:
        raise ValueError(
            f"the title cannot contain figures ({', '.join(figures)}): every number in the "
            "report comes from the case file. Write the title in words."
        )


# --------------------------------------------------------------------------- rendering


def _summary(
    case: CaseFile,
    ids: list[str],
    title: str,
    playbook: dict[str, Any],
    deltas: dict[str, dict[str, dict[str, float]]],
) -> list[str]:
    lines = [f"# {title}", "", "## Resumen", ""]
    lines.append(f"Sesión `{case.session_id}`. Pisos del informe: {', '.join(ids)}.")
    lines.append("")
    profile = case.profile.model_dump(exclude_none=True)
    if profile:
        lines.append("Perfil del inversor:")
        for key, value in profile.items():
            label, unit = PROFILE_LABELS.get(key, (key, ""))
            lines.append(f"- {label}: {fmt(value, unit)}")
        lines.append("")
    target = case.profile.target_net_yield_pct
    with_yield = []
    for pid in ids:
        base = _base(case, pid)
        where = case.properties[pid].municipality
        name = f"{pid} ({where})" if where else pid
        if "net_yield_pct" not in base:
            lines.append(f"- {name}: sin rentabilidad calculada (faltan datos; ver preguntas).")
            continue
        net = base["net_yield_pct"].value
        with_yield.append((net, pid))
        text = f"- {name}: rentabilidad neta {fmt(net, '%')}"
        if "after_tax_yield_pct" in base:
            text += f", tras impuestos {fmt(base['after_tax_yield_pct'].value, '%')}"
        if target is not None:
            text += "; cumple el objetivo" if net >= target else "; no llega al objetivo"
        best = _best_lever(deltas[pid], playbook)
        if best:
            text += f". Palanca que más mejora: {best}"
        lines.append(text + ".")
    if len(with_yield) > 1:
        lines.append("")
        lines.append(f"Mejor rentabilidad neta: {max(with_yield)[1]}.")
    return lines


def _best_lever(deltas: dict[str, dict[str, float]], playbook: dict[str, Any]) -> str | None:
    """The single playbook lever with the largest gain in yield after tax (or net yield)."""
    best: tuple[float, str, str] | None = None
    for scenario, changes in deltas.items():
        if scenario not in playbook:
            continue
        metric = "after_tax_yield_pct" if "after_tax_yield_pct" in changes else "net_yield_pct"
        value = changes.get(metric, 0.0)
        if value > 0 and (best is None or value > best[0]):
            best = (value, scenario, metric)
    if best is None:
        return None
    value, scenario, metric = best
    return f"{playbook[scenario].title} ({LABELS[metric].lower()} {_delta(value, '%')})"


def _table(case: CaseFile, ids: list[str]) -> list[str]:
    lines = ["## Cifras por piso", ""]
    header = ["Piso", "Municipio"] + [LABELS[m] for m in TABLE_METRICS]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for pid in ids:
        base = _base(case, pid)
        cells = [pid, case.properties[pid].municipality or "—"]
        for m in TABLE_METRICS:
            cells.append(fmt(base[m].value, base[m].unit) if m in base else "—")
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    order = {name: i for i, name in enumerate(UNITS)}
    for pid in ids:
        base = _base(case, pid)
        lines += ["", f"### {pid}", ""]
        if not base:
            lines.append("Sin cifras del motor: faltan datos (ver preguntas abiertas).")
            continue
        for name in sorted(base, key=lambda n: order.get(n, len(order))):
            label = LABELS.get(name, name)
            lines.append(f"- {label}: {fmt(base[name].value, base[name].unit)}")
    return lines


def _lever_section(
    case: CaseFile,
    ids: list[str],
    playbook: dict[str, Any],
    deltas: dict[str, dict[str, dict[str, float]]],
) -> list[str]:
    lines = ["## Palancas evaluadas", ""]
    lines.append(
        "Diferencias frente al escenario base calculadas por el motor (`what_if`); "
        "pp = puntos porcentuales."
    )
    for pid in ids:
        lines += ["", f"### {pid}", ""]
        scenarios = _scenarios(case, pid)
        if scenarios:
            header = ["Palanca o escenario"] + [LABELS[m] for m in LEVER_METRICS]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("|" + "---|" * len(header))
            for scenario, figures in scenarios.items():
                cells = [_scenario_label(scenario, playbook)]
                for m in LEVER_METRICS:
                    if m not in figures:
                        cells.append("—")
                        continue
                    cell = fmt(figures[m].value, figures[m].unit)
                    if m in deltas[pid].get(scenario, {}):
                        cell += f" ({_delta(deltas[pid][scenario][m], figures[m].unit)})"
                    cells.append(cell)
                lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
        else:
            lines.append("No se ha simulado ninguna palanca con cifra para este piso.")
        qualitative = _qualitative(case, pid)
        if qualitative:
            lines += ["", "Sin cifra (cualitativas) y prácticas a evitar:"]
            for entry in qualitative:
                level = LEVEL_NAMES.get(entry["level"], entry["level"])
                text = f"- {entry['title']} (`{entry['id']}`, {level}; fuente: {entry['source']})"
                if entry.get("risk"):
                    text += f". Riesgo: {entry['risk']}"
                lines.append(text)
    return lines


def _assumptions(case: CaseFile, ids: list[str]) -> list[str]:
    lines = ["## Supuestos", ""]
    chosen = [a for a in case.assumptions if a.property_id is None or a.property_id in ids]
    if not chosen:
        return lines + ["Ninguno: todos los datos los dio el usuario."]
    for a in chosen:
        where = f"{a.property_id} · " if a.property_id else ""
        lines.append(f"- {where}`{a.field}` = {fmt(a.value)}: {a.reason}")
    return lines


def _questions(case: CaseFile, ids: list[str]) -> list[str]:
    lines = ["## Preguntas abiertas", ""]
    others = [pid for pid in case.properties if pid not in ids]
    chosen = [q for q in case.open_questions if not any(q.startswith(f"{p}:") for p in others)]
    if not chosen:
        return lines + ["Ninguna."]
    return lines + [f"- {q}" for q in chosen]


def _sources(case: CaseFile) -> list[str]:
    lines = ["## Fuentes consultadas", ""]
    return lines + [f"- [{key}] {source}" for key, source in case.sources.items()]


def render(case: CaseFile, ids: list[str], title: str) -> tuple[str, list[str]]:
    """The report text and the names of its sections. Records the lever deltas in the case."""
    playbook = {lever.id: lever for lever in load_levers()}
    deltas = {pid: _record_deltas(case, pid) for pid in ids}
    blocks = [
        _summary(case, ids, title, playbook, deltas),
        _table(case, ids),
        _lever_section(case, ids, playbook, deltas),
        _assumptions(case, ids),
        _questions(case, ids),
    ]
    sections = list(SECTIONS)
    if case.sources:
        blocks.append(_sources(case))
        sections.insert(-1, "Fuentes consultadas")
    blocks.append(["## Aviso", "", DISCLAIMER])
    return "\n\n".join("\n".join(b) for b in blocks) + "\n", sections


# --------------------------------------------------------------------------- the tool


@tool(requires_confirmation=True)
def write_investment_report(
    property_ids: list[Annotated[str, Field(min_length=1, max_length=40)]],
    title: Annotated[str, Field(min_length=1, max_length=120)] | None = None,
) -> dict[str, Any]:
    """Write the investment report for these properties to a Markdown file (needs confirmation).

    The report takes every number from the case file, so first call analyze_property (and
    what_if for the levers) on each property; never pass figures here. It returns the file
    path, not the text.

    Args:
        property_ids: Ids of properties already in the case file, e.g. ["P1", "P2"]. An empty
            list means all the properties of the case.
        title: Optional title in words, without figures.
    """
    case = current()
    _check_title(title)
    ids = _resolve_ids(case, property_ids)
    analysed = [pid for pid in ids if _base(case, pid)]
    if not analysed:
        raise ValueError(
            f"no engine figures for {', '.join(ids)}: call analyze_property first, "
            "the report takes every number from the case file"
        )
    title = title.strip() if title else f"Informe de inversión: {', '.join(ids)}"
    text, sections = render(case, ids, title)
    path = reports_dir() / f"{slugify(case.session_id, 40)}-{slugify(title)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    out: dict[str, Any] = {"path": str(path), "n_properties": len(ids), "sections": sections}
    pending = [pid for pid in ids if pid not in analysed]
    if pending:
        out["warnings"] = [
            f"{', '.join(pending)}: sin cifras del motor (faltan datos); el informe lo dice"
        ]
    return out


TOOLS = [write_investment_report]
"""Tools of this module, for the agent loop's registry."""
