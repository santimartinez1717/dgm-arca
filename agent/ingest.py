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
import os
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


def ingest(task: str, prose: bool | None = None) -> IngestResult:
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
    text = "\n".join(out_lines)
    if not properties and (prose if prose is not None else prose_enabled()):
        found = extract_prose(task)
        if found.property is not None:
            properties.append(found.property)
            facts = ", ".join(f for f in found.fields if f != "id")
            text += f"\n[1 piso cargado en el expediente: P1 ({facts})]"
    return IngestResult(properties, text, ignored, bad)


# --------------------------------------------------------------------------- one flat in prose

# A 1.7B model asked to copy the facts of a sentence into record_property drops some of them:
# in the first runs of the loop (issue 20) it left out the cadastral value, the previous rent
# or the contract date in 3 of 4 tasks, and the engine could not compute the IRPF or the cap.
# These patterns read the facts a Spanish user writes about ONE dwelling. They only fill what
# they find with certainty; the model can still add or correct with record_property.

EUROS = r"(\d[\d.]*(?:,\d+)?)\s*(?:€|euros?\b)"
PROSE_PATTERNS: dict[str, list[str]] = {
    "price": [
        rf"\b(?:por|sale por|precio de|cuesta|vale|pide[n]?)\s+{EUROS}",
    ],
    "monthly_rent": [
        rf"(?:alquil\w*|cobr\w*|pedir|pagará|renta de)\s+(?:por\s+|a\s+)?{EUROS}",
        rf"\bmantengo\s+(?:los\s+|la renta en\s+)?{EUROS}",
    ],
    "previous_rent": [
        rf"(?:inquilino anterior|anterior inquilino|último inquilino|el anterior)"
        rf"\s+pagaba\s+{EUROS}",
    ],
    "area_m2": [r"(\d+(?:[.,]\d+)?)\s*m(?:²|2)\b"],
    "cadastral_value": [rf"valor catastral(?:\s+de|\s+es|:)?\s+{EUROS}"],
    "land_share_pct": [
        r"\((\d+(?:[.,]\d+)?)\s*%\s*(?:de\s+)?suelo\)",
        r"(\d+(?:[.,]\d+)?)\s*%\s*(?:de\s+)?suelo\b",
    ],
    "land_value": [rf"de los que\s+{EUROS}\s+son\s+(?:de\s+)?suelo"],
    "reference_value": [
        rf"valor de referencia(?:\s+del Catastro)?(?:\s+es|\s+de|:)?\s+(?:de\s+)?{EUROS}",
    ],
    "ibi": [rf"\bIBI(?:\s+de|:)?\s+{EUROS}"],
    "community_monthly": [rf"\bcomunidad(?:\s+de|:)?\s+{EUROS}\s*al mes"],
    "community_annual": [rf"\bcomunidad(?:\s+de|:)?\s+{EUROS}\s*al año"],
    "insurance": [rf"\bseguro(?:\s+de|:)?\s+{EUROS}"],
    "notary_registry": [rf"notar[ií]a(?:\s+y\s+(?:el\s+)?registro)?(?:\s+unos|\s+de)?\s+{EUROS}"],
    "ajd_rate_pct": [r"\bAJD\s+(?:del?\s+)?(\d+(?:[.,]\d+)?)\s*%"],
    "tenant_age": [r"inquilino de\s+(\d{2})\s+años"],
    "contract_date": [
        r"(?:firm\w*|contrato(?:\s+\w+)?\s+(?:el|del)|desde el)\s+(?:el\s+)?"
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ],
}
# "por 800 €" after a rent verb is the rent, not the price ("lo alquilo por 800 €").
RENT_BEFORE = re.compile(r"(?:alquil\w*|cobr\w*|pag\w*|ped\w*|renta)\s+(?:\w+\s+)?$", re.I)

# Several dwellings in the text: one Property would mix their facts.
SEVERAL = re.compile(
    r"\b(?:dos|tres|cuatro|cinco|\d+)\s+pisos\b|\bcada uno\b|\bestos pisos\b|\bentre dos\b",
    re.IGNORECASE,
)
REHABILITATION = re.compile(r"rehabilitaci[oó]n|rehabilitad[oa]", re.IGNORECASE)
NEW_BUILD = re.compile(r"\bobra nueva\b", re.IGNORECASE)
MUNICIPALITY = re.compile(
    r"\ben\s+((?:[A-ZÁÉÍÓÚÑ][\wáéíóúñü'-]*)(?:\s+(?:de|del|la|las|los|el|i|d'|[A-ZÁÉÍÓÚÑ][\wáéíóúñü'-]*))*)"
)


def _municipality(text: str) -> str | None:
    """The first "en <Municipio>" whose name is a Spanish municipality (SERPAVI list)."""
    from tool_use.build_data import normalise_name
    from tool_use.public_data import _names, _serpavi

    known = {n for row in _serpavi() for n in _names(row["name"])}
    for match in MUNICIPALITY.finditer(text):
        words = match.group(1).split()
        for end in range(len(words), 0, -1):  # longest first: "Santiago de Compostela"
            candidate = " ".join(words[:end]).rstrip(",.;:")
            if normalise_name(candidate) in known:
                return candidate
    return None


def _values(text: str, patterns: list[str], read, not_after: re.Pattern | None = None) -> set:
    found = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if not_after is not None and not_after.search(
                text[max(0, match.start() - 30) : match.start()]
            ):
                continue
            try:
                found.add(read(match.group(1)))
            except ValueError:
                continue
    return found


@dataclass
class ProseResult:
    property: Property | None
    fields: list[str] = field(default_factory=list)  # what was read
    ambiguous: list[str] = field(default_factory=list)  # several values: left to the model


def extract_prose(text: str, property_id: str = "P1") -> ProseResult:
    """The facts of ONE dwelling described in Spanish prose, only those read with certainty.

    Needs a price and a rent or an area (otherwise it is not the description of a flat), and
    gives up when the text talks about several dwellings. A field with two different values
    ("una web dice 150.000 € y otra 210.000 €") is left out and reported as ambiguous.
    """
    if SEVERAL.search(text):
        return ProseResult(None)
    values: dict[str, Any] = {}
    ambiguous: list[str] = []
    for name, patterns in PROSE_PATTERNS.items():
        if name == "contract_date":
            read = parse_date
        elif name == "tenant_age":
            read = lambda cell: int(parse_number(cell))  # noqa: E731
        else:
            read = parse_number
        found = _values(text, patterns, read, RENT_BEFORE if name == "price" else None)
        if len(found) == 1:
            values[name] = found.pop()
        elif len(found) > 1:
            ambiguous.append(name)
    if "price" not in values or not ({"monthly_rent", "area_m2", "reference_value"} & set(values)):
        return ProseResult(None, ambiguous=ambiguous)
    if "community_annual" in values:
        annual = values.pop("community_annual")
        values.setdefault("community_monthly", round(annual / 12, 2))
    if "land_value" in values and "cadastral_value" in values and "land_share_pct" not in values:
        values["land_share_pct"] = round(100 * values["land_value"] / values["cadastral_value"], 2)
    values.pop("land_value", None)
    if NEW_BUILD.search(text):
        values["new_build"] = True
    if REHABILITATION.search(text):
        values["rehabilitation_last_2y"] = True
    town = _municipality(text)
    if town:
        values["municipality"] = town
    return ProseResult(Property(id=property_id, **values), sorted(values), ambiguous)


def prose_enabled() -> bool:
    return os.environ.get("ARCA_INGEST_PROSE", "1") != "0"


def extract_properties(task: str, prose: bool | None = None) -> tuple[list[Property], str]:
    """The flats of every CSV pasted in ``task`` and the task with each table replaced by a line.

    Without a table, a single dwelling described in prose is read with ``extract_prose``
    (unless ``prose=False`` or ``ARCA_INGEST_PROSE=0``); the text then keeps the prose and
    gets one line saying what was loaded. Otherwise it comes back unchanged.
    """
    result = ingest(task, prose)
    return result.properties, result.text
