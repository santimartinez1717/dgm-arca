"""General ITP rate for second-hand dwellings, by autonomous community.

This is *data*, not a rule: it changes with each regional budget law. The rule (ITP on the
higher of price and cadastral reference value) lives in ``rlm/realestate_rules.py``.

Source: Gibobs, "ITP 2026" (https://www.gibobs.com/blog/itp-2026/), consulted 2026-11-17.
It is a secondary source and it says so itself; every row still has to be checked against
the community's own tax agency (``verified`` stays False until someone does it).

Several communities use a progressive scale or special regimes. For them the table holds the
general (lowest) bracket, and ``note`` explains what the tool cannot model; the tool returns
that note as a warning so the model and the user see it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Region = Literal[
    "andalucia",
    "aragon",
    "asturias",
    "baleares",
    "canarias",
    "cantabria",
    "castilla_la_mancha",
    "castilla_y_leon",
    "cataluna",
    "comunidad_valenciana",
    "extremadura",
    "galicia",
    "la_rioja",
    "madrid",
    "murcia",
    "navarra",
    "pais_vasco",
]

SOURCE = "Gibobs, ITP 2026 (fuente secundaria), consultada el 17/11/2026"


@dataclass(frozen=True)
class ItpRate:
    rate_pct: float
    note: str = ""
    verified: bool = False


ITP_GENERAL: dict[str, ItpRate] = {
    "andalucia": ItpRate(7.0),
    "aragon": ItpRate(8.0, "escala progresiva: los tramos altos pagan hasta un 10 %"),
    "asturias": ItpRate(8.0, "escala progresiva en tramos altos"),
    "baleares": ItpRate(8.0, "escala progresiva del 8 % al 11 %"),
    "canarias": ItpRate(6.5),
    "cantabria": ItpRate(10.0),
    "castilla_la_mancha": ItpRate(9.0),
    "castilla_y_leon": ItpRate(8.0),
    "cataluna": ItpRate(10.0, "escala progresiva del 10 % al 13 % desde 2026"),
    "comunidad_valenciana": ItpRate(10.0),
    "extremadura": ItpRate(8.0),
    "galicia": ItpRate(10.0),
    "la_rioja": ItpRate(7.0),
    "madrid": ItpRate(6.0),
    "murcia": ItpRate(8.0),
    "navarra": ItpRate(6.0, "régimen foral"),
    "pais_vasco": ItpRate(4.0, "régimen foral: 4 % en vivienda, 7 % en otros casos"),
}
