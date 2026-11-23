"""From what the user writes ("Sevilla", "Bizkaia", "Catalunya") to an autonomous community.

The tools that need a community (the ITP rate depends on it) used to take a ``Literal`` of
the 17 names. Qwen3-1.7B did not translate city -> community on its own: in the phase 2
bench it wrote Sevilla -> "extremadura", Bilbao -> "baleares" and Barcelona -> "barcelona".
A strict schema pushes onto the model a lookup that a table does without error, so the tools
now accept a community, a province or a municipality and resolve it here.

Municipalities come from the SERPAVI file (2,616 with at least 10 contracts, every
provincial capital among them); the first two digits of their INE code are the province.
"""

from __future__ import annotations

import csv
import functools
from pathlib import Path

from tool_use.build_data import SERPAVI_FILE, normalise_name
from tool_use.itp_rates import ITP_GENERAL

# INE province code -> community, with the names ITP_GENERAL uses.
PROVINCE_REGION = {
    **dict.fromkeys(["04", "11", "14", "18", "21", "23", "29", "41"], "andalucia"),
    **dict.fromkeys(["22", "44", "50"], "aragon"),
    "33": "asturias",
    "07": "baleares",
    **dict.fromkeys(["35", "38"], "canarias"),
    "39": "cantabria",
    **dict.fromkeys(["02", "13", "16", "19", "45"], "castilla_la_mancha"),
    **dict.fromkeys(["05", "09", "24", "34", "37", "40", "42", "47", "49"], "castilla_y_leon"),
    **dict.fromkeys(["08", "17", "25", "43"], "cataluna"),
    **dict.fromkeys(["03", "12", "46"], "comunidad_valenciana"),
    **dict.fromkeys(["06", "10"], "extremadura"),
    **dict.fromkeys(["15", "27", "32", "36"], "galicia"),
    "26": "la_rioja",
    "28": "madrid",
    "30": "murcia",
    "31": "navarra",
    **dict.fromkeys(["01", "20", "48"], "pais_vasco"),
}

# Other names of the communities, already normalised.
COMMUNITY_ALIASES = {
    "catalunya": "cataluna",
    "euskadi": "pais_vasco",
    "pais vasco euskadi": "pais_vasco",
    "comunitat valenciana": "comunidad_valenciana",
    "comunidad valenciana": "comunidad_valenciana",
    "valenciana": "comunidad_valenciana",
    "comunidad de madrid": "madrid",
    "islas baleares": "baleares",
    "illes balears": "baleares",
    "balears": "baleares",
    "islas canarias": "canarias",
    "principado de asturias": "asturias",
    "region de murcia": "murcia",
    "comunidad foral de navarra": "navarra",
    "nafarroa": "navarra",
    "castilla mancha": "castilla_la_mancha",
    "castilla leon": "castilla_y_leon",
    "rioja": "la_rioja",
}

REGION_HELP = (
    "pass the autonomous community (" + ", ".join(sorted(ITP_GENERAL)) + ") or a Spanish "
    "province or municipality"
)


def _key(text: str) -> str:
    """Normalised form shared by community names, aliases, provinces and municipalities."""
    return normalise_name(text.replace("_", " ").replace("-", " "))


@functools.cache
def _places() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Province and municipality names -> the communities they can mean."""
    provinces: dict[str, set[str]] = {}
    municipalities: dict[str, set[str]] = {}
    with Path(SERPAVI_FILE).open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            region = PROVINCE_REGION.get(row["code"][:2])
            if region is None:  # Ceuta and Melilla: no community in the ITP table
                continue
            for target, name in ((provinces, row["province"]), (municipalities, row["name"])):
                for part in [name, *name.split("/")]:
                    if key := _key(part):
                        target.setdefault(key, set()).add(region)
    return provinces, municipalities


def resolve_region(text: str) -> str:
    """The community a place name belongs to, or ValueError with what the tool accepts."""
    key = _key(text)
    communities = {_key(name): name for name in ITP_GENERAL}
    if key in communities:
        return communities[key]
    if key in COMMUNITY_ALIASES:
        return COMMUNITY_ALIASES[key]
    provinces, municipalities = _places()
    for table in (provinces, municipalities):
        found = table.get(key, set())
        if len(found) == 1:
            return next(iter(found))
        if len(found) > 1:
            raise ValueError(
                f"{text!r} names places in several communities ({', '.join(sorted(found))}): "
                "pass the community"
            )
    raise ValueError(f"unknown place {text!r}: {REGION_HELP}")
