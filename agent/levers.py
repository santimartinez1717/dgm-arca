"""The wise guy's two moves: which levers fit this case, and what each one is worth.

``find_levers`` evaluates the playbook's predicates on the case file: deterministic, no
model, no retrieval. ``what_if`` applies a lever (or any override, to branch on a doubtful
fact) to a copy of the property and runs ``agent.analysis.analyze`` again, so every delta
comes from the same engine as the base figures. Illegal levers are never simulated: they
exist so the agent recognises them and warns.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from agent.analysis import Analysis, analyze
from agent.case_file import CaseFile, InvestorProfile, Property
from agent.playbook.schema import REFERENCE, Condition, Lever, check_path, load_levers
from rlm import realestate_rules as rules

# What a scenario reports: enough to compare, short enough for a small model's context.
KEY_METRICS = (
    "price",
    "total_investment",
    "effective_rent",
    "net_yield_pct",
    "cash_on_cash_pct",
    "irpf_reduction_pct",
    "income_tax",
    "after_tax_yield_pct",
)


def _get(path: str, prop: Property, profile: InvestorProfile) -> Any:
    scope, _, name = path.partition(".")
    return getattr(prop if scope == "property" else profile, name)


def resolve_value(
    value: Any, prop: Property, profile: InvestorProfile, base: Analysis | None = None
) -> Any:
    """Turn ``$property.x[*k]`` and the named values into numbers; constants pass through."""
    if not (isinstance(value, str) and value.startswith("$")):
        return value
    if value == "$max_offer_price":
        return max_offer_price(prop, profile, base or analyze(prop, profile))
    match = REFERENCE.match(value)
    if match is None:
        raise ValueError(f"cannot resolve {value!r}")
    found = _get(f"{match.group(1)}.{match.group(2)}", prop, profile)
    if found is None:
        raise ValueError(f"{value!r} needs {match.group(1)}.{match.group(2)}, which is unknown")
    return rules.round2(found * float(match.group(3))) if match.group(3) else found


def max_offer_price(prop: Property, profile: InvestorProfile, base: Analysis) -> float:
    """Highest price that reaches the investor's target net yield (ITP on the price)."""
    if profile.target_net_yield_pct is None:
        raise ValueError("the investor has no target_net_yield_pct")
    if "net_income" not in base.figures:
        raise ValueError(f"cannot price {prop.id}: missing {', '.join(base.missing)}")
    return rules.max_price_for_target_yield(
        annual_net_operating_income=base.figures["net_income"],
        target_yield=profile.target_net_yield_pct / 100,
        itp_rate=base.figures.get("itp_rate_pct", 0.0) / 100,
        fixed_costs=prop.notary_registry + prop.agency_fee + prop.renovation,
    )


def evaluate(condition: Condition, prop: Property, profile: InvestorProfile) -> bool | None:
    """True, False, or None when the case does not know the field (the lever may apply)."""
    found = _get(condition.field, prop, profile)
    if condition.op == "is_null":
        return found is None
    if condition.op == "not_null":
        return found is not None
    if found is None:
        return None
    try:
        expected = resolve_value(condition.value, prop, profile)
    except ValueError:
        return None
    if isinstance(found, date) and isinstance(expected, str):
        expected = date.fromisoformat(expected)
    ops = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "lt": lambda a, b: a < b,
        "le": lambda a, b: a <= b,
        "gt": lambda a, b: a > b,
        "ge": lambda a, b: a >= b,
        "in": lambda a, b: a in b,
    }
    return ops[condition.op](found, expected)


def effective_property(prop: Property, base: Analysis) -> Property:
    """The property with what the engine derived (stressed zone, region) filled in."""
    update = {}
    if prop.stressed_zone is None and base.stressed_zone is not None:
        update["stressed_zone"] = base.stressed_zone
    if prop.region is None and base.region is not None:
        update["region"] = base.region
    return prop.model_copy(update=update)


def cite(lever: Lever) -> str:
    section = f" · {lever.evidence.section}" if lever.evidence.section else ""
    return f"{lever.evidence.source}{section}"


def find(case: CaseFile, property_id: str, levers: tuple[Lever, ...] | None = None) -> dict:
    """Levers of the playbook whose conditions hold for this property, and those that might."""
    prop = case.property(property_id)
    base = analyze(prop, case.profile)
    prop = effective_property(prop, base)
    applicable, maybe, traps = [], [], []
    for lever in levers if levers is not None else load_levers():
        results = [evaluate(c, prop, case.profile) for c in lever.applies_when]
        if any(r is False for r in results):
            continue
        entry = {
            "id": lever.id,
            "level": lever.level,
            "title": lever.title,
            "quantified": lever.quantified,
            "source": cite(lever),
        }
        if lever.risk:
            entry["risk"] = lever.risk
        if lever.level == "illegal_warning":
            traps.append(entry)
        elif any(r is None for r in results):
            unknown = [
                c.field for c, r in zip(lever.applies_when, results, strict=True) if r is None
            ]
            maybe.append({**entry, "needs": unknown})
        else:
            applicable.append(entry)
    out: dict[str, Any] = {"property_id": prop.id, "applicable": applicable}
    if maybe:
        out["maybe"] = maybe
    if traps:
        out["traps_to_warn_about"] = traps
    out["next"] = "call what_if with the quantified ids to see what each one is worth"
    return out


def normalise_path(path: str) -> str:
    """``monthly_rent`` -> ``property.monthly_rent``; unknown fields raise ValueError."""
    if "." not in path:
        if path in Property.model_fields and path != "id":
            path = f"property.{path}"
        elif path in InvestorProfile.model_fields:
            path = f"profile.{path}"
    return check_path(path)


def _apply(
    sets: dict[str, Any], prop: Property, profile: InvestorProfile, base: Analysis
) -> tuple[Property, InvestorProfile]:
    prop_update, profile_update = {}, {}
    for path, raw in sets.items():
        scope, _, name = normalise_path(path).partition(".")
        value = resolve_value(raw, prop, profile, base)
        (prop_update if scope == "property" else profile_update)[name] = value
    new_prop = Property.model_validate({**prop.model_dump(), **prop_update})
    new_profile = InvestorProfile.model_validate({**profile.model_dump(), **profile_update})
    return new_prop, new_profile


def _delta(base: Analysis, other: Analysis) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in KEY_METRICS:
        if key in other.figures:
            out[key] = other.figures[key]
            if key in base.figures and other.figures[key] != base.figures[key]:
                out[f"{key}_change"] = rules.round2(other.figures[key] - base.figures[key])
    if other.rules.get("irpf_reduction") != base.rules.get("irpf_reduction"):
        out["irpf_rule"] = other.rules.get("irpf_reduction")
    if other.missing:
        out["missing"] = other.missing
    return out


def simulate(
    case: CaseFile,
    property_id: str,
    lever_ids: list[str] | None = None,
    overrides: dict[str, Any] | None = None,
    tool: str = "what_if",
) -> dict:
    """Base scenario, each lever on its own, all quantified levers together, and overrides."""
    playbook = {lever.id: lever for lever in load_levers()}
    prop = case.property(property_id)
    base = analyze(prop, case.profile)
    base.record(case, tool)
    out: dict[str, Any] = {
        "property_id": prop.id,
        "base": {k: base.figures[k] for k in KEY_METRICS if k in base.figures},
    }
    if base.missing:
        out["base"]["missing"] = base.missing
    scenarios, combined_sets = [], {}
    for lever_id in lever_ids or []:
        lever = playbook.get(lever_id)
        if lever is None:
            scenarios.append(
                {"lever": lever_id, "error": f"unknown lever; known: {list(playbook)}"}
            )
            continue
        if lever.level == "illegal_warning":
            scenarios.append(
                {"lever": lever_id, "refused": "illegal: only to warn the user", "risk": lever.risk}
            )
            continue
        if lever.engine is None:
            scenarios.append(
                {
                    "lever": lever_id,
                    "qualitative": "no figure: explain it with its risk and source",
                    "risk": lever.risk,
                    "source": cite(lever),
                }
            )
            continue
        try:
            new_prop, new_profile = _apply(lever.engine.set, prop, case.profile, base)
        except ValueError as exc:
            scenarios.append({"lever": lever_id, "error": str(exc)})
            continue
        result = analyze(new_prop, new_profile)
        _record_keys(result, case, tool, lever_id)
        scenario = {"lever": lever_id, "level": lever.level, **_delta(base, result)}
        if "property.price" in lever.engine.set and (new_prop.price or 0) >= (prop.price or 0):
            scenario["note"] = "the asking price already reaches the target: this is the ceiling"
        scenarios.append(scenario)
        combined_sets.update(lever.engine.set)
    quantified = [s for s in scenarios if "error" not in s and "qualitative" not in s]
    quantified = [s for s in quantified if "refused" not in s]
    if len(quantified) > 1:
        new_prop, new_profile = _apply(combined_sets, prop, case.profile, base)
        result = analyze(new_prop, new_profile)
        name = "+".join(s["lever"] for s in quantified)
        _record_keys(result, case, tool, name)
        scenarios.append({"lever": name, **_delta(base, result)})
    if overrides:
        try:
            new_prop, new_profile = _apply(overrides, prop, case.profile, base)
        except (ValueError, TypeError) as exc:
            scenarios.append({"override": overrides, "error": str(exc)})
        else:
            result = analyze(new_prop, new_profile)
            name = "if " + ", ".join(f"{k.split('.')[-1]}={v}" for k, v in overrides.items())
            _record_keys(result, case, tool, name)
            scenarios.append({"scenario": name, **_delta(base, result)})
    out["scenarios"] = scenarios
    return out


def _record_keys(result: Analysis, case: CaseFile, tool: str, scenario: str) -> None:
    keys = Analysis(
        property_id=result.property_id,
        figures={k: v for k, v in result.figures.items() if k in KEY_METRICS},
    )
    keys.record(case, tool, scenario)
