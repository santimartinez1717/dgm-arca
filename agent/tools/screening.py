"""``screen_properties``: every property of the case file through the rule engine at once.

The star task of the proposal ("te paso 15 pisos en un CSV, quédate con los que den más de un
4,5 % neto") is more than 45 steps for a 1.7B model going flat by flat. This tool does the
mechanical screening in one call with the same ``analyze`` as ``analyze_property``, so both
give the same figures, and the agent only digs into the finalists and the near misses.

The output goes into a small model's context, so it is one short row per property, and the
reasons are written in Spanish with the figure that fails ("neto 3,8 % < 4,5 %"), ready to be
copied into the answer.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from agent.analysis import Analysis, analyze
from agent.case_file import CaseFile, Property, current
from tool_use.registry import tool

TOOL_NAME = "screen_properties"
# Figures that count as "rent above the legal cap" or "cap unknown" in analyze's warnings.
RENT_WARNINGS = ("rent_above_legal_cap", "legal_cap_unknown")
ASKING_SCENARIO = "asking_rent"


def _num(value: float) -> str:
    """Spanish number: 3.8 -> "3,8", 250000 -> "250.000"."""
    if abs(value) >= 1000:
        return f"{value:,.0f}".replace(",", ".")
    return f"{round(value, 2):g}".replace(".", ",")


def _missing_reason(result: Analysis, figure: str) -> str:
    """Why ``figure`` was not computed, as "falta X" (the first gap analyze reported)."""
    gaps = [m.split(" (")[0] for m in result.missing]
    if figure == "cash_on_cash_pct" and not gaps:
        return "falta financing (record_investor: financing, interest_rate_pct)"
    # The IRPF gap only blocks the after-tax yield: name the gap that blocks this figure.
    if figure != "after_tax_yield_pct":
        gaps = [g for g in gaps if "cadastral" not in g and not g.startswith("IRPF")] or gaps
    return "falta " + (gaps[0] if gaps else figure)


def _row(prop: Property, result: Analysis, yield_key: str, coc: bool) -> dict[str, Any]:
    f = result.figures
    price = prop.price
    if price is not None and price.is_integer():
        price = int(price)  # "250000", not "250000.0": fewer tokens
    row: dict[str, Any] = {"id": prop.id, "price": price}
    for key in ("net_yield_pct", yield_key) + (("cash_on_cash_pct",) if coc else ()):
        if key in f:
            row[key] = f[key]
    warnings = [w for w in result.warnings if w.startswith(RENT_WARNINGS)]
    if warnings:
        row["warnings"] = warnings
    return row


@tool
def screen_properties(
    min_net_yield_pct: Annotated[float, Field(ge=0, le=100)] | None = None,
    max_price: Annotated[float, Field(gt=0)] | None = None,
    min_cash_on_cash_pct: Annotated[float, Field(ge=-100, le=100)] | None = None,
    require_legal_rent: bool = True,
    near_miss_pct: Annotated[float, Field(ge=0, le=10)] = 0.5,
    after_tax: bool = False,
) -> dict[str, Any]:
    """Screen every property in the case file with the rule engine, in one call.

    Use it when the user gives several properties (e.g. a CSV) and a criterion. It runs the
    same analysis as analyze_property on each one and returns: passed (sorted by yield, best
    first), rejected (each with its reason and the failing figure) and near_miss (ids of the
    rejected ones that miss the yield by near_miss_pct points or less: try find_levers on
    them). Record the properties first with record_property.

    Args:
        min_net_yield_pct: Minimum net yield in percent, inclusive (4.5 means 4.5 %). If
            omitted, the investor's target_net_yield_pct is used.
        max_price: Maximum purchase price in euros.
        min_cash_on_cash_pct: Minimum mortgage cash-on-cash in percent (needs financing).
        require_legal_rent: True (default) computes with the rent the law allows, i.e. the
            asking rent capped at the legal maximum. False uses the asking rent.
        near_miss_pct: Yield points below the minimum that still count as a near miss.
        after_tax: True compares the yield after IRPF instead of the net yield before tax
            (use it when the user says "después de impuestos").
    """
    case = current()
    if not case.properties:
        raise ValueError("the case file has no properties: record them first with record_property")
    if min_net_yield_pct is None:
        min_net_yield_pct = case.profile.target_net_yield_pct
    yield_key = "after_tax_yield_pct" if after_tax else "net_yield_pct"
    yield_label = "neto tras IRPF" if after_tax else "neto"
    coc = bool(case.profile.financing) or min_cash_on_cash_pct is not None

    passed, rejected, near = [], [], []
    for prop in case.properties.values():
        result = _screen_one(case, prop, require_legal_rent)
        row = _row(prop, result, yield_key, coc)
        reasons: list[str] = []
        gap = 0.0  # yield points missing, for the near misses
        blocked = False  # a reason that no lever on the yield can fix (price, missing data)

        if prop.price is None:
            reasons.append("falta price")
            blocked = True
        elif max_price is not None and prop.price > max_price:
            reasons.append(f"precio {_num(prop.price)} € > {_num(max_price)} €")
            blocked = True

        for key, minimum, label in (
            (yield_key, min_net_yield_pct, yield_label),
            ("cash_on_cash_pct", min_cash_on_cash_pct, "cash-on-cash"),
        ):
            if minimum is None or prop.price is None:
                continue
            value = result.figures.get(key)
            if value is None:
                reasons.append(_missing_reason(result, key))
                case.ask(f"{prop.id}: {reasons[-1]}")
                blocked = True
            elif value < minimum:
                reasons.append(f"{label} {_num(value)} % < {_num(minimum)} %")
                gap = max(gap, minimum - value)

        if min_net_yield_pct is None and yield_key not in result.figures and not reasons:
            # No yield criterion: the property cannot be ranked, so it is not a pass either.
            reasons.append(_missing_reason(result, yield_key))
            blocked = True

        if not reasons:
            passed.append(row)
            continue
        capped = result.figures.get("legal_max_rent")
        if capped is not None and any(
            w.startswith("rent_above_legal_cap") for w in result.warnings
        ):
            reasons.append(
                f"renta pedida {_num(prop.monthly_rent or 0)} €/mes > tope legal {_num(capped)}"
            )
            row.pop("warnings", None)  # the reason already says it, in Spanish
        row["reason"] = "; ".join(reasons)
        rejected.append(row)
        if not blocked and gap <= near_miss_pct:
            near.append((gap, prop.id))

    def by_yield(row: dict[str, Any]) -> float:
        return row.get(yield_key, float("-inf"))

    out: dict[str, Any] = {
        "criteria": {
            k: v
            for k, v in {
                "min_" + yield_key: min_net_yield_pct,
                "max_price": max_price,
                "min_cash_on_cash_pct": min_cash_on_cash_pct,
                "rent": "legal" if require_legal_rent else "asking",
            }.items()
            if v is not None
        },
        "passed": sorted(passed, key=by_yield, reverse=True),
        "rejected": sorted(rejected, key=by_yield, reverse=True),
        "near_miss": [pid for _, pid in sorted(near)],
    }
    if near:
        out["next"] = "find_levers on the near_miss ids"
    return out


def _screen_one(case: CaseFile, prop: Property, require_legal_rent: bool) -> Analysis:
    """Analyse one property and record its figures. With ``require_legal_rent=False`` and an
    asking rent above the cap, the figures of the screen are those of the asking rent, recorded
    as a separate scenario so the auditor never mistakes them for the legal ones."""
    result = analyze(prop, case.profile)
    result.record(case, TOOL_NAME)
    if require_legal_rent or not any(w.startswith("rent_above_legal_cap") for w in result.warnings):
        return result
    # The cap only exists in a stressed zone: outside it the asking rent is what counts. The
    # IRPF of this scenario is then the one outside a stressed zone (an illegal rent has no
    # legal reduction to compare with anyway).
    asking = analyze(prop.model_copy(update={"stressed_zone": False}), case.profile)
    asking.record(case, TOOL_NAME, scenario=ASKING_SCENARIO)
    asking.warnings = [w for w in result.warnings if w.startswith(RENT_WARNINGS)]
    return asking


TOOLS = [screen_properties]
"""What the ReAct loop registers from this module (``agent.tools.screening.TOOLS``)."""
