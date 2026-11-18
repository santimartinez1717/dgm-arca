"""Domain calculators: the phase 1 rule engine exposed as tools.

Every tool here is a thin layer over ``rlm/realestate_rules.py``, which stays the single
source of truth. The layer does three things the engine does not:

* takes percentages as people write them (``4`` means 4 %), because that is how they appear
  in the user's message and a small model copies numbers better than it converts them;
* looks up data the user rarely knows (the ITP rate of their region) and derives what
  people usually get wrong (which IRPF reduction applies) instead of asking for it;
* returns the rule that produced each figure, and warnings when an input is missing or a
  case falls outside what the engine models, so the answer can cite them.

Phase 1 failed on rules (VAT on new builds, depreciation in IRPF) and on arithmetic
(divisions, the French mortgage). These tools remove both, which is exactly what the
"with vs without tools" comparison of phase 2 measures.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Annotated, Any

from pydantic import Field

from rlm import realestate_rules as rules
from tool_use.itp_rates import ITP_GENERAL, SOURCE
from tool_use.regions import resolve_region
from tool_use.registry import tool

Euros = Annotated[float, Field(ge=0)]
PositiveEuros = Annotated[float, Field(gt=0)]
# A community, province or municipality; resolve_region turns it into a community.
Place = Annotated[str, Field(min_length=2, max_length=60)]
Pct = Annotated[float, Field(ge=0, le=100)]


@tool
def acquisition_cost(
    price: PositiveEuros,
    region: Place,
    new_build: bool = False,
    reference_value: Euros | None = None,
    notary_registry: Euros = 0.0,
    agency_fee: Euros = 0.0,
    renovation: Euros = 0.0,
    itp_rate_pct: Pct | None = None,
    ajd_rate_pct: Pct | None = None,
) -> dict[str, Any]:
    """Total capital needed to buy a dwelling in Spain, purchase taxes included.

    Second-hand dwellings pay ITP on the higher of price and the cadastral reference value.
    New builds pay 10 % VAT on the price plus AJD. Use this for "how much money do I need",
    "total investment" or "taxes of the purchase".

    Args:
        price: Purchase price in euros.
        region: Where the dwelling is: the city as the user wrote it (e.g. "Sevilla") or
            the autonomous community. The tool finds the community and its ITP rate.
        new_build: True for a new build bought from the developer (VAT + AJD instead of ITP).
        reference_value: Cadastral reference value ("valor de referencia") in euros, if known.
        notary_registry: Notary, registry and agency paperwork costs in euros.
        agency_fee: Real-estate agency fee paid by the buyer, in euros.
        renovation: Renovation budget in euros, added to the investment.
        itp_rate_pct: ITP rate in percent (8 means 8 %), only to override the regional table.
        ajd_rate_pct: AJD rate in percent; required for new builds (e.g. 1.5).
    """
    region = resolve_region(region)
    warnings: list[str] = []
    if reference_value is None:
        reference_value = 0.0
        warnings.append(
            "valor de referencia no indicado: si supera el precio, el ITP se paga sobre él"
        )
    if itp_rate_pct is None:
        row = ITP_GENERAL[region]
        itp_rate_pct = row.rate_pct
        if row.note:
            warnings.append(f"ITP de {region}: {row.note}")
        if not row.verified:
            warnings.append(f"tipo de ITP sin verificar con la comunidad ({SOURCE})")
    if new_build and ajd_rate_pct is None:
        raise ValueError("new_build=True needs ajd_rate_pct (AJD rate of the region, e.g. 1.5)")
    result = rules.acquisition_cost(
        price=price,
        reference_value=reference_value,
        new_build=new_build,
        itp_rate=itp_rate_pct / 100,
        ajd_rate=(ajd_rate_pct or 0.0) / 100,
        notary_registry=notary_registry,
        agency_fee=agency_fee,
        renovation=renovation,
    )
    rule = (
        "obra nueva: IVA 10 % sobre el precio + AJD sobre max(precio, valor de referencia)"
        if new_build
        else f"ITP {itp_rate_pct:g} % sobre max(precio, valor de referencia) (Ley 11/2021)"
    )
    return {**asdict(result), "region": region, "rule": rule, "warnings": warnings}


# Above this a "monthly" rent is a yearly figure in the wrong argument (phase 1 test,
# max_price: 19.770 EUR net a year went in as the rent and the price came out 12 times higher).
MAX_MONTHLY_RENT = 10_000


def _net_income(
    monthly_rent: float | None, annual_net_income: float | None, **costs: float
) -> dict[str, Any]:
    """Annual net operating income, from the rent and costs or as given by the user."""
    # With both, the net income wins: it is already net, and when the user gives it the model
    # tends to add a made-up rent next to it (phase 1 test, cash_on_cash).
    if annual_net_income is not None:
        out: dict[str, Any] = {"net_income": annual_net_income}
        if monthly_rent is not None:
            out["note"] = "used annual_net_income; monthly_rent and the costs were ignored"
        return out
    if monthly_rent is None:
        raise ValueError("pass monthly_rent (with the costs) or annual_net_income")
    if monthly_rent >= MAX_MONTHLY_RENT:
        raise ValueError(
            f"monthly_rent is per MONTH and {monthly_rent:g} looks like a yearly figure: pass a "
            "net yearly income as annual_net_income, or divide a yearly rent by 12"
        )
    noi = rules.net_yield(
        monthly_rent=monthly_rent,
        vacant_months=costs["vacant_months"],
        ibi=costs["ibi"],
        community_monthly=costs["community_monthly"],
        insurance=costs["insurance"],
        maintenance_pct=costs["maintenance_pct"] / 100,
        management_pct=costs["management_pct"] / 100,
        total_investment=1.0,  # the yield is computed by the caller
    )
    return {
        "collected_rent": noi.collected_rent,
        "operating_costs": noi.operating_costs,
        "net_income": noi.net_income,
    }


@tool
def rental_returns(
    total_investment: PositiveEuros,
    annual_net_income: PositiveEuros | None = None,
    monthly_rent: PositiveEuros | None = None,
    vacant_months: Annotated[float, Field(ge=0, le=12)] = 0.0,
    ibi: Euros = 0.0,
    community_monthly: Euros = 0.0,
    insurance: Euros = 0.0,
    maintenance_pct: Pct = 0.0,
    management_pct: Pct = 0.0,
    loan: Euros = 0.0,
    interest_rate_pct: Pct | None = None,
    loan_years: Annotated[int, Field(ge=0, le=40)] | None = None,
    rate_shock_pct: Annotated[float, Field(ge=0, le=10)] = 0.0,
) -> dict[str, Any]:
    """Yield of a rental: gross and net yield and, with a mortgage, cash-on-cash return.

    Net yield = (collected rent - operating costs) / total investment, before income tax.
    With a loan it also returns the monthly mortgage payment and the return on the
    investor's own money. Use this for "rentabilidad", "yield", "cash flow" or "¿me compensa?".

    Args:
        total_investment: All the money invested in euros (price, taxes, costs, renovation).
        annual_net_income: Net income per YEAR after costs and before the mortgage, only when
            the user gives it instead of the rent (e.g. "genera 9.840 € netos al año"). Then
            leave out monthly_rent and the costs.
        monthly_rent: Rent per MONTH in euros (e.g. 900). A yearly figure is not a rent.
        vacant_months: Months per year without a tenant.
        ibi: Annual property tax (IBI) in euros.
        community_monthly: Monthly homeowners' community fee in euros.
        insurance: Annual insurance premium in euros (home and rent default).
        maintenance_pct: Maintenance reserve as a percent of collected rent (3 means 3 %).
        management_pct: Property manager fee as a percent of collected rent.
        loan: Mortgage principal in euros; 0 if bought in cash.
        interest_rate_pct: Annual mortgage interest rate in percent (3.2 means 3.2 %).
        loan_years: Mortgage term in years; leave it out (or 0) if there is no loan.
        rate_shock_pct: Extra interest points for a stress scenario (2 means +2 points).
    """
    income = _net_income(
        monthly_rent,
        annual_net_income,
        vacant_months=vacant_months,
        ibi=ibi,
        community_monthly=community_monthly,
        insurance=insurance,
        maintenance_pct=maintenance_pct,
        management_pct=management_pct,
    )
    net_income = income["net_income"]
    out: dict[str, Any] = {
        **income,
        "net_yield_pct": rules.round2(100 * net_income / total_investment),
    }
    if "collected_rent" in income:
        out["gross_yield_pct"] = rules.round2(100 * 12 * monthly_rent / total_investment)
    if loan > 0:
        if interest_rate_pct is None or not loan_years:
            raise ValueError("a loan needs interest_rate_pct and loan_years")
        coc = rules.cash_on_cash(
            total_investment=total_investment,
            loan=loan,
            annual_rate=interest_rate_pct / 100,
            years=loan_years,
            annual_net_operating_income=net_income,
        )
        out["financing"] = asdict(coc)
        if rate_shock_pct > 0:
            stressed = rules.cash_on_cash(
                total_investment=total_investment,
                loan=loan,
                annual_rate=(interest_rate_pct + rate_shock_pct) / 100,
                years=loan_years,
                annual_net_operating_income=net_income,
            )
            out["stress"] = {"interest_rate_pct": interest_rate_pct + rate_shock_pct}
            out["stress"].update(asdict(stressed))
    return out


@tool
def max_offer_price(
    target_net_yield_pct: Annotated[float, Field(gt=0, le=100)],
    annual_net_income: PositiveEuros | None = None,
    monthly_rent: PositiveEuros | None = None,
    region: Place | None = None,
    vacant_months: Annotated[float, Field(ge=0, le=12)] = 0.0,
    ibi: Euros = 0.0,
    community_monthly: Euros = 0.0,
    insurance: Euros = 0.0,
    maintenance_pct: Pct = 0.0,
    management_pct: Pct = 0.0,
    fixed_costs: Euros = 0.0,
    itp_rate_pct: Pct | None = None,
) -> dict[str, Any]:
    """Highest price to offer for a second-hand dwelling so that it reaches a target net yield.

    Solves net income / (price + ITP + fixed costs) = target. Use this for "¿cuánto puedo
    ofrecer?", "precio máximo" or "what price gives me a 5 % yield".

    Args:
        target_net_yield_pct: Target net yield in percent (5 means 5 %).
        annual_net_income: Net income per YEAR after costs, only when the user gives it
            instead of the rent (e.g. "generaría 19.770 € netos al año"); then leave out
            monthly_rent and the costs.
        monthly_rent: Expected rent per MONTH in euros (e.g. 900). A yearly figure is not a
            rent.
        region: Where the dwelling is: the city as the user wrote it or the autonomous
            community. The tool finds the community and its ITP rate. Not needed if the
            user gives the ITP rate.
        vacant_months: Months per year without a tenant.
        ibi: Annual property tax (IBI) in euros.
        community_monthly: Monthly homeowners' community fee in euros.
        insurance: Annual insurance premium in euros.
        maintenance_pct: Maintenance reserve as a percent of collected rent.
        management_pct: Property manager fee as a percent of collected rent.
        fixed_costs: Costs that do not depend on the price (notary, agency, renovation).
        itp_rate_pct: ITP rate in percent when the user gives it (8 means 8 %); otherwise
            the tool takes the region's.
    """
    warnings = ["supone que el valor de referencia no supera el precio"]
    if region is not None:
        region = resolve_region(region)
    if itp_rate_pct is None:
        if region is None:
            raise ValueError("pass region (to look up the ITP rate) or itp_rate_pct")
        itp_rate_pct = ITP_GENERAL[region].rate_pct
        warnings.append(f"tipo de ITP sin verificar con la comunidad ({SOURCE})")
    income = _net_income(
        monthly_rent,
        annual_net_income,
        vacant_months=vacant_months,
        ibi=ibi,
        community_monthly=community_monthly,
        insurance=insurance,
        maintenance_pct=maintenance_pct,
        management_pct=management_pct,
    )
    net_income = income["net_income"]
    if "note" in income:
        warnings.append(income["note"])
    price = rules.max_price_for_target_yield(
        annual_net_operating_income=net_income,
        target_yield=target_net_yield_pct / 100,
        itp_rate=itp_rate_pct / 100,
        fixed_costs=fixed_costs,
    )
    return {
        "max_price": price,
        "annual_net_income": net_income,
        "region": region,
        "itp_rate_pct": itp_rate_pct,
        "warnings": warnings,
    }


@tool
def legal_rent_cap(
    market_rent: Euros,
    stressed_zone: bool,
    large_holder: bool,
    area_m2: Annotated[float, Field(gt=0)],
    previous_rent: Euros | None = None,
    ten_percent_exception: bool = False,
    index_upper_eur_m2: Euros | None = None,
    declaration_caps_unrented: bool = False,
) -> dict[str, Any]:
    """Maximum legal monthly rent of a new habitual-residence contract (LAU art. 17.6 and 17.7).

    Outside a stressed zone there is no cap. Inside one, the new rent cannot exceed the
    previous contract's rent (17.6) and, for a large holder ("gran tenedor"), the upper value
    of the SERPAVI reference index times the area (17.7). Use this for "¿cuánto puedo cobrar?"
    or "¿es legal esta renta?".

    Args:
        market_rent: Monthly rent the market would pay, in euros.
        stressed_zone: True if the dwelling is in a declared stressed residential market zone.
        large_holder: True if the landlord is a "gran tenedor" (see get_portfolio).
        area_m2: Built area of the dwelling in square metres.
        previous_rent: Updated monthly rent of the last habitual-residence contract of the
            last five years, in euros; omit if there was none.
        ten_percent_exception: True if the previous rent may rise up to 10 % (rehabilitation
            or energy works in the last two years, or a contract of ten years or more).
        index_upper_eur_m2: Upper value of the SERPAVI reference index, in euros per m2 per
            month.
        declaration_caps_unrented: True if the zone declaration also caps dwellings with no
            previous contract.
    """
    needs_index = large_holder or (previous_rent is None and declaration_caps_unrented)
    if stressed_zone and needs_index and index_upper_eur_m2 is None:
        raise ValueError("this case is capped by the reference index: pass index_upper_eur_m2")
    cap = rules.legal_rent_cap(
        market_rent=market_rent,
        stressed_zone=stressed_zone,
        large_holder=large_holder,
        previous_rent_updated=previous_rent,
        ten_percent_exception=ten_percent_exception,
        index_upper_eur_m2=index_upper_eur_m2 or 0.0,
        area_m2=area_m2,
        declaration_caps_unrented=declaration_caps_unrented,
    )
    return {
        "max_monthly_rent": cap.max_rent,
        "max_annual_rent": rules.round2(12 * cap.max_rent),
        "binding_rule": cap.rule,
        "caps": cap.caps,
    }


@tool
def rental_income_tax(
    annual_rent: Euros,
    acquisition_cost_total: Euros,
    cadastral_value: Euros,
    contract_date: date,
    land_value: Euros | None = None,
    land_share_pct: Pct | None = None,
    ibi: Euros = 0.0,
    community_annual: Euros = 0.0,
    insurance: Euros = 0.0,
    interest: Euros = 0.0,
    repairs: Euros = 0.0,
    stressed_zone: bool = False,
    previously_rented: bool = True,
    monthly_rent: Euros | None = None,
    previous_rent: Euros | None = None,
    index_max_rent: Euros | None = None,
    large_holder: bool = False,
    same_tenant_after_term: bool = False,
    tenant_age: Annotated[int, Field(ge=18, le=120)] | None = None,
    social_tenant: bool = False,
    rehabilitation_last_2y: bool = False,
) -> dict[str, Any]:
    """Net rental income for Spanish IRPF, with depreciation and the art. 23.2 reduction.

    Deducts expenses and the 3 % depreciation of the building (never of the land), caps
    interest plus repairs at the income, and decides which reduction applies from the
    contract's date and facts: 60 % before 26/05/2023, the Ley 12/2023 scale until
    01/12/2026, and the RDL 29/2026 scale after, which depends on how the rent changed.
    Use this for "¿cuánto tributo?", "rendimiento neto" or "IRPF del alquiler".

    Args:
        annual_rent: Rent collected in the year, in euros.
        acquisition_cost_total: Purchase price plus the purchase expenses and taxes, in euros.
        cadastral_value: Total cadastral value ("valor catastral") from the IBI receipt.
        contract_date: Date the rental contract was signed, YYYY-MM-DD.
        land_value: Cadastral value of the land ("valor del suelo") in euros, when the user
            gives it as an amount. Pass it as written; the tool computes the share.
        land_share_pct: Share of the cadastral value that is land, in percent, only when the
            user gives a percentage (40 means 40 %). Pass land_value or land_share_pct.
        ibi: Annual property tax (IBI) in euros.
        community_annual: Annual homeowners' community fees in euros.
        insurance: Annual insurance premiums in euros.
        interest: Mortgage interest paid in the year, in euros.
        repairs: Repair and maintenance costs of the year, in euros.
        stressed_zone: True if the dwelling is in a declared stressed zone.
        previously_rented: False if the dwelling had never been rented before this contract.
        monthly_rent: Rent per MONTH of this contract (e.g. 1250), not the yearly total.
            Only needed for contracts from 01/12/2026.
        previous_rent: Rent per MONTH the previous tenant paid (e.g. 1000). Only needed
            for contracts from 01/12/2026.
        index_max_rent: Monthly rent limit of the SERPAVI reference index for this dwelling.
        large_holder: True if the landlord was a "gran tenedor" when signing.
        same_tenant_after_term: True if the contract renews with the same tenant after the
            minimum five-year term and its extensions.
        tenant_age: Age of the tenant, only needed for the young-tenant reductions.
        social_tenant: True if the tenant is a public administration or a non-profit that
            sublets it as social housing.
        rehabilitation_last_2y: True if a rehabilitation finished in the two years before
            the contract.
    """
    warnings: list[str] = []
    # The model rounds a share it works out by hand (49.27 % became 46 %): take the euros.
    if land_value is not None:
        if not 0 <= land_value <= cadastral_value or cadastral_value == 0:
            raise ValueError("land_value must be between 0 and cadastral_value")
        land_share = land_value / cadastral_value
    elif land_share_pct is not None:
        land_share = land_share_pct / 100
    else:
        raise ValueError("pass land_value (in euros) or land_share_pct")
    change = None
    if monthly_rent is not None and previous_rent:
        change = 100 * (monthly_rent - previous_rent) / previous_rent
    age = tenant_age if tenant_age is not None else 0

    if contract_date < rules.LEY_VIVIENDA_IN_FORCE:
        reduction = 60
        why = "contrato anterior al 26/05/2023: 60 % (art. 23.2 en su redacción de 2021)"
    elif contract_date < rules.RDL_29_2026_CONTRACTS:
        reduction = rules.rental_reduction_pct(
            stressed_zone=stressed_zone,
            previously_rented=previously_rented,
            rent_cut_over_5pct=change is not None and change < -5,
            tenant_age=age,
            public_or_social_tenant=social_tenant,
            rehabilitation_last_2y=rehabilitation_last_2y,
        )
        why = f"contrato del 26/05/2023 al 30/11/2026, escala de la Ley 12/2023: {reduction} %"
        if previously_rented and stressed_zone and change is None:
            warnings.append("sin la renta anterior y la nueva no se puede aplicar el 90 %")
    else:
        if previously_rented and change is None and not (social_tenant or large_holder):
            raise ValueError(
                "contracts from 01/12/2026 on a dwelling rented before need monthly_rent and "
                "previous_rent: the reduction depends on how much the rent changed"
            )
        below_index = (
            index_max_rent is not None
            and monthly_rent is not None
            and monthly_rent < index_max_rent
        )
        reduction = rules.rental_reduction_pct_2026(
            large_holder=large_holder,
            previously_rented=previously_rented,
            rent_change_pct=change,
            same_tenant_after_term=same_tenant_after_term,
            below_index=below_index,
            stressed_zone=stressed_zone,
            tenant_age=age,
            public_or_social_tenant=social_tenant,
            rehabilitation_last_2y=rehabilitation_last_2y,
        )
        why = f"contrato desde el 01/12/2026, escala del RDL 29/2026: {reduction} %"
        if index_max_rent is None and (not previously_rented or (change or 0) < -5):
            warnings.append("sin el límite del índice SERPAVI no se puede aplicar el 100 %")
        if large_holder:
            warnings.append("un gran tenedor no tiene la reducción general desde el RDL 29/2026")
    if change is not None:
        warnings.append(f"variación de la renta frente al contrato anterior: {change:+.2f} %")
    result = rules.rental_income_tax(
        annual_rent=annual_rent,
        ibi=ibi,
        community_annual=community_annual,
        insurance=insurance,
        interest=interest,
        repairs=repairs,
        acquisition_cost_total=acquisition_cost_total,
        cadastral_value=cadastral_value,
        land_share=land_share,
        reduction_pct=reduction,
    )
    if interest + repairs > annual_rent:
        warnings.append(
            "intereses + reparaciones superan los ingresos: el exceso se arrastra 4 años"
        )
    return {**asdict(result), "reduction_rule": why, "warnings": warnings}


CALCULATORS = (acquisition_cost, rental_returns, max_offer_price, legal_rent_cap, rental_income_tax)
