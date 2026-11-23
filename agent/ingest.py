"""Deterministic ingestion: the CSV of flats pasted in a task goes to the case file before the loop.

Copying fifteen flats one by one with ``record_property`` would take a 1.7B model fifteen
steps and fifteen chances to get a number wrong. This module parses them in code instead and
replaces the table in the task by one line, so the context does not pay for it twice::

    properties, text = extract_properties(task)
    # text: "...\n[15 pisos cargados en el expediente: P01…P15]\n..."

A block is a CSV when its first line is a header with at least two known columns (Spanish or
English, see ``COLUMNS``), followed by rows with the same number of cells. The separator is
``;``, ``,`` or a tab, and the block may sit inside a fenced code block. Numbers are read as
Spanish users write them (``180.000``, ``4,5``) or in English (``180000``, ``4.5``).
"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from agent.case_file import Property

log = logging.getLogger(__name__)

# Normalised header -> Property field. Normalising folds case and accents, drops units
# ("precio (€)", "m²") and joins words with "_".
COLUMNS: dict[str, str] = {
    **dict.fromkeys(["id", "ref", "referencia", "piso", "label", "etiqueta", "nombre"], "id"),
    **dict.fromkeys(
        ["municipio", "ciudad", "localidad", "poblacion", "municipality", "city", "town"],
        "municipality",
    ),
    **dict.fromkeys(["comunidad_autonoma", "ccaa", "region", "provincia", "province"], "region"),
    **dict.fromkeys(
        ["precio", "precio_compra", "precio_venta", "price", "purchase_price", "asking_price"],
        "price",
    ),
    **dict.fromkeys(
        ["valor_referencia", "valor_de_referencia", "reference_value"], "reference_value"
    ),
    **dict.fromkeys(["obra_nueva", "nueva", "new_build", "new"], "new_build"),
    **dict.fromkeys(["ajd", "ajd_pct", "tipo_ajd", "ajd_rate_pct"], "ajd_rate_pct"),
    **dict.fromkeys(
        ["m2", "superficie", "metros", "metros_cuadrados", "area", "area_m2", "sqm", "size"],
        "area_m2",
    ),
    **dict.fromkeys(
        [
            "renta",
            "renta_mensual",
            "renta_pedida",
            "renta_mes",
            "alquiler",
            "alquiler_mensual",
            "alquiler_mes",
            "rent",
            "monthly_rent",
            "asking_rent",
        ],
        "monthly_rent",
    ),
    **dict.fromkeys(
        [
            "renta_anterior",
            "renta_contrato_anterior",
            "alquiler_anterior",
            "previous_rent",
            "last_rent",
        ],
        "previous_rent",
    ),
    **dict.fromkeys(["alquilado_antes", "previously_rented"], "previously_rented"),
    **dict.fromkeys(["zona_tensionada", "tensionada", "stressed_zone"], "stressed_zone"),
    **dict.fromkeys(["indice_serpavi", "serpavi", "index_upper_eur_m2"], "index_upper_eur_m2"),
    **dict.fromkeys(["valor_catastral", "catastral", "cadastral_value"], "cadastral_value"),
    **dict.fromkeys(
        ["suelo", "suelo_pct", "pct_suelo", "porcentaje_suelo", "land_share", "land_share_pct"],
        "land_share_pct",
    ),
    **dict.fromkeys(
        ["fecha_contrato", "fecha_firma", "fecha", "contract_date", "date"], "contract_date"
    ),
    **dict.fromkeys(
        ["notaria", "notaria_registro", "notary", "notary_registry"], "notary_registry"
    ),
    **dict.fromkeys(["agencia", "honorarios_agencia", "agency_fee"], "agency_fee"),
    **dict.fromkeys(["reforma", "obras", "renovation"], "renovation"),
    **dict.fromkeys(["ibi", "ibi_anual"], "ibi"),
    **dict.fromkeys(
        [
            "comunidad",
            "comunidad_mes",
            "comunidad_mensual",
            "gastos_comunidad",
            "community",
            "community_monthly",
            "hoa",
        ],
        "community_monthly",
    ),
    **dict.fromkeys(["seguro", "seguro_anual", "insurance"], "insurance"),
    **dict.fromkeys(
        ["meses_vacio", "meses_vacios", "vacio_meses", "vacant_months"], "vacant_months"
    ),
    **dict.fromkeys(["mantenimiento", "mantenimiento_pct", "maintenance_pct"], "maintenance_pct"),
    **dict.fromkeys(["gestion", "gestion_pct", "management_pct"], "management_pct"),
    **dict.fromkeys(
        ["rehabilitacion", "rehabilitado", "rehabilitation_last_2y"], "rehabilitation_last_2y"
    ),
    **dict.fromkeys(["edad_inquilino", "tenant_age"], "tenant_age"),
}

TEXT_FIELDS = {"id", "municipality", "region"}
BOOL_FIELDS = {
    name for name, info in Property.model_fields.items() if info.annotation in (bool, bool | None)
}
INT_FIELDS = {"tenant_age"}
DATE_FIELDS = {"contract_date"}

TRUE = {"si", "s", "yes", "y", "true", "1", "x", "verdadero"}
FALSE = {"no", "n", "false", "0", "falso", ""}

FENCE = re.compile(r"^\s*```")
UNIT = re.compile(r"\((?:[^)]*)\)|€|eur\b|euros?\b|%|²", re.IGNORECASE)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def normalise_header(name: str) -> str:
    """'Precio (€)' -> 'precio', 'Valor de referencia' -> 'valor_de_referencia', 'm²' -> 'm2'."""
    text = _fold(name).replace("m²", "m2")
    text = UNIT.sub(" ", text)
    return "_".join(re.findall(r"[a-z0-9]+", text))


def parse_number(cell: str) -> float:
    """'180.000' -> 180000, '4,5' -> 4.5, '1.234,56 €' -> 1234.56, '180000' -> 180000."""
    text = re.sub(r"[^\d,.\-]", "", cell.replace("−", "-"))
    if not re.search(r"\d", text):
        raise ValueError(f"not a number: {cell!r}")
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        text = text.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "." in text:
        # In a Spanish table a dot followed by groups of three digits is a thousands mark.
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", text):
            text = text.replace(".", "")
    elif "," in text:
        if re.fullmatch(r"-?\d{1,3}(?:,\d{3}){2,}", text):  # 1,234,567
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    return float(text)


def parse_date(cell: str) -> date:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(cell.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {cell!r}")


def parse_bool(cell: str) -> bool:
    value = _fold(cell).rstrip(".")
    if value in TRUE:
        return True
    if value in FALSE:
        return False
    raise ValueError(f"not a yes/no: {cell!r}")


def _value(field_name: str, cell: str) -> Any:
    if field_name in TEXT_FIELDS:
        return cell.strip()
    if field_name in BOOL_FIELDS:
        return parse_bool(cell)
    if field_name in DATE_FIELDS:
        return parse_date(cell)
    number = parse_number(cell)
    return int(number) if field_name in INT_FIELDS else number


@dataclass
class IngestResult:
    properties: list[Property]
    text: str
    ignored_columns: list[str] = field(default_factory=list)
    bad_cells: list[str] = field(default_factory=list)  # "P03.price: 'unos 100k'"


def _split(line: str, sep: str) -> list[str]:
    return next(csv.reader([line], delimiter=sep, skipinitialspace=True))


def _header(line: str) -> tuple[str, list[str]] | None:
    """(separator, cells) when the line looks like the header of a table of flats."""
    for sep in (";", "\t", ","):
        if sep not in line:
            continue
        cells = _split(line, sep)
        known = {COLUMNS.get(normalise_header(c)) for c in cells} - {None}
        if len(cells) >= 2 and len(known) >= 2:
            return sep, cells
    return None


def _block_end(lines: list[str], start: int, sep: str, width: int) -> int:
    """Index after the last row of the table that starts with the header at ``start``."""
    end = start + 1
    while end < len(lines) and lines[end].strip() and not FENCE.match(lines[end]):
        if len(_split(lines[end], sep)) != width:
            break
        end += 1
    return end


def _summary(ids: list[str]) -> str:
    shown = ", ".join(ids) if len(ids) <= 3 else f"{ids[0]}…{ids[-1]}"
    noun = "piso cargado" if len(ids) == 1 else "pisos cargados"
    return f"[{len(ids)} {noun} en el expediente: {shown}]"


def ingest(task: str) -> IngestResult:
    """Every table of flats in ``task``, as ``Property`` objects, and the task without them."""
    lines = task.split("\n")
    out_lines: list[str] = []
    properties: list[Property] = []
    ignored: list[str] = []
    bad: list[str] = []
    i = 0
    while i < len(lines):
        found = _header(lines[i])
        end = _block_end(lines, i, found[0], len(found[1])) if found else i
        if not found or end == i + 1:  # a header with no rows is prose
            out_lines.append(lines[i])
            i += 1
            continue
        sep, header = found
        fields = [COLUMNS.get(normalise_header(c)) for c in header]
        ignored += [c.strip() for c, f in zip(header, fields, strict=True) if f is None]
        ids: list[str] = []
        for row in lines[i + 1 : end]:
            values: dict[str, Any] = {}
            unreadable: list[str] = []
            for cell, name in zip(_split(row, sep), fields, strict=True):
                if name is None or not cell.strip():
                    continue
                try:
                    values[name] = _value(name, cell)
                except ValueError:
                    unreadable.append(f"{name}: {cell.strip()!r}")
            pid = str(values.pop("id", "") or f"P{len(properties) + 1}")
            bad += [f"{pid}.{u}" for u in unreadable]
            properties.append(Property(id=pid, **values))
            ids.append(pid)
        # A table inside ``` fences takes its fences with it.
        if (
            out_lines
            and FENCE.match(out_lines[-1])
            and end < len(lines)
            and FENCE.match(lines[end])
        ):
            out_lines.pop()
            end += 1
        out_lines.append(_summary(ids))
        i = end
    ignored = list(dict.fromkeys(ignored))
    if ignored or bad:
        log.info("ingest: ignored columns %s, unreadable cells %s", ignored, bad)
    return IngestResult(properties, "\n".join(out_lines), ignored, bad)


def extract_properties(task: str) -> tuple[list[Property], str]:
    """The flats of every CSV pasted in ``task`` and the task with each table replaced by a line.

    A task without a table comes back unchanged and with no properties.
    """
    result = ingest(task)
    return result.properties, result.text
