"""Tools that work on the case file: record facts, analyse, find levers, simulate them.

They read and write the active case (``agent.case_file.current()``), so the model passes
short ids and the facts the user gave, never the whole case. Every figure they compute is
stored in the case with the tool's name, which is what the auditor checks the answer against.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from pydantic import Field

from agent import levers
from agent.analysis import analyze
from agent.case_file import Property, current
from tool_use.registry import tool

Euros = Annotated[float, Field(ge=0)]
Pct = Annotated[float, Field(ge=0, le=100)]
PropertyId = Annotated[str, Field(min_length=1, max_length=40)]


def _merge(model: Any, values: dict[str, Any]) -> Any:
    given = {k: v for k, v in values.items() if v is not None}
    return type(model).model_validate({**model.model_dump(), **given}), sorted(given)


@tool
def record_property(
    property_id: PropertyId,
    municipality: str | None = None,
    price: Euros | None = None,
    monthly_rent: Euros | None = None,
    area_m2: Annotated[float, Field(gt=0)] | None = None,
    reference_value: Euros | None = None,
    cadastral_value: Euros | None = None,
    land_share_pct: Pct | None = None,
    new_build: bool | None = None,
    previous_rent: Euros | None = None,
    stressed_zone: bool | None = None,
    contract_date: date | None = None,
    ibi: Euros | None = None,
    community_monthly: Euros | None = None,
    insurance: Euros | None = None,
    renovation: Euros | None = None,
    tenant_age: Annotated[int, Field(ge=18, le=120)] | None = None,
) -> dict[str, Any]:
    """Save the facts the user gave about a property in the case file (creates it if new).

    Call this first with every number the user wrote about the property, copied as written.
    Leave out what the user did not say: never guess. Other tools then only need its id.

    Args:
        property_id: Short id for the property, e.g. "P1" or the user's own label.
        municipality: Municipality where it is, e.g. "Valencia".
        price: Purchase price in euros.
        monthly_rent: Rent per MONTH in euros the user expects or asks.
        area_m2: Built area in square metres.
        reference_value: Cadastral reference value ("valor de referencia") in euros.
        cadastral_value: Cadastral value ("valor catastral") from the IBI receipt, in euros.
        land_share_pct: Share of the cadastral value that is land, in percent.
        new_build: True for a new build bought from the developer.
        previous_rent: Monthly rent of the previous contract, if it was rented before.
        stressed_zone: Only if the user says whether it is in a stressed zone.
        contract_date: Date the rental contract is or was signed, YYYY-MM-DD.
        ibi: Annual property tax (IBI) in euros.
        community_monthly: Monthly homeowners' community fee in euros.
        insurance: Annual insurance premium in euros.
        renovation: Renovation budget in euros.
        tenant_age: Age of the tenant, if known.
    """
    case = current()
    values = dict(locals())
    values.pop("case")
    property_id = values.pop("property_id")
    existing = case.properties.get(property_id) or Property(id=property_id)
    merged, saved = _merge(existing, values)
    case.properties[property_id] = merged
    return {"property_id": property_id, "saved": saved, "next": "analyze_property"}


@tool
def record_investor(
    region: str | None = None,
    properties_owned: Annotated[int, Field(ge=0)] | None = None,
    properties_owned_stressed: Annotated[int, Field(ge=0)] | None = None,
    financing: bool | None = None,
    down_payment_pct: Pct | None = None,
    interest_rate_pct: Pct | None = None,
    loan_years: Annotated[int, Field(ge=1, le=40)] | None = None,
    marginal_tax_rate_pct: Pct | None = None,
    target_net_yield_pct: Pct | None = None,
) -> dict[str, Any]:
    """Save what the user said about themselves as an investor in the case file.

    Leave out what the user did not say. The number of dwellings they already own decides
    whether they are a large holder ("gran tenedor"), which changes the legal rent and the IRPF.

    Args:
        region: Autonomous community where they buy, if they say it.
        properties_owned: Dwellings they already own (not counting the one they analyse).
        properties_owned_stressed: Of those, how many are in a stressed zone.
        financing: True if they buy with a mortgage.
        down_payment_pct: Down payment in percent of the price (20 means 20 %).
        interest_rate_pct: Mortgage interest rate in percent.
        loan_years: Mortgage term in years.
        marginal_tax_rate_pct: Their marginal IRPF rate in percent.
        target_net_yield_pct: Net yield they want, in percent (4.5 means 4.5 %).
    """
    case = current()
    values = dict(locals())
    values.pop("case")
    case.profile, saved = _merge(case.profile, values)
    return {"saved": saved}


@tool
def analyze_property(property_id: PropertyId) -> dict[str, Any]:
    """Full analysis of a property with the rule engine: purchase taxes, legal rent, net
    yield, mortgage cash-on-cash, IRPF and the yield after tax. Lists what is missing.

    Args:
        property_id: Id of a property already in the case file (see record_property).
    """
    case = current()
    result = analyze(case.property(property_id), case.profile)
    result.record(case, "analyze_property")
    for name in result.missing:
        case.ask(f"{property_id}: falta {name}")
    return result.summary()


@tool
def find_levers(property_id: PropertyId) -> dict[str, Any]:
    """Legal levers ("trucos") that could improve this investment, from the playbook.

    Returns the levers whose conditions this property meets, those that need a fact we do not
    know, and the illegal tricks to warn the user about. It does not compute their value:
    call what_if with the ids.

    Args:
        property_id: Id of a property already in the case file.
    """
    return levers.find(current(), property_id)


@tool
def what_if(
    property_id: PropertyId,
    lever_ids: list[str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute a property with levers applied, or with a fact changed, and compare.

    Use lever_ids from find_levers to see what each lever is worth (and all of them
    together). Use overrides to branch on a doubtful fact, e.g. {"reference_value": 150000}
    or {"contract_date": "2026-11-30"}: answer with both scenarios and ask the user.

    Args:
        property_id: Id of a property already in the case file.
        lever_ids: Ids of levers returned by find_levers.
        overrides: Facts to change, as {"field": value}, e.g. {"monthly_rent": 900}.
    """
    if not lever_ids and not overrides:
        raise ValueError("pass lever_ids (from find_levers) or overrides")
    return levers.simulate(current(), property_id, lever_ids, overrides)


CASE_TOOLS = [record_property, record_investor, analyze_property, find_levers, what_if]
