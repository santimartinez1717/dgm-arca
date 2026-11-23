"""Rule engine for Spanish buy-to-let investment analysis.

This module is the single source of truth for the domain. Three phases use it:

* phase 1: ``realestate_problems.py`` calls it in ``solve`` to produce the ground truth;
* phase 2: the ``analyze_investment`` tool exposes it to the model;
* phase 4: the agent benchmark checks final answers against it.

Every function is pure and deterministic, and quotes the rule it implements. The legal
*data* that changes over time (the ITP rate of a region, the SERPAVI index, the Euribor) is
an argument; the *rules* that are stable (which base, which cap, which reduction) are code.

Sources, consulted in September 2026:

* Ley 12/2023, por el derecho a la vivienda, art. 3.k (large holder, "gran tenedor").
* Ley 29/1994 de Arrendamientos Urbanos (LAU), art. 17.6 and 17.7 (rent caps in stressed
  zones) as amended by Ley 12/2023.
* Ley 35/2006 del IRPF, art. 23 (deductible expenses and rental reductions) and its
  regulation (RD 439/2007), art. 13 and 14 (3 % depreciation of the building).
* RDL 1/1993 (TRLITPAJD) and Ley 11/2021: the ITP base is the cadastral reference value when
  it is higher than the declared price.
* RDL 29/2026 (BOE-A-2026-20823), art. 6 and DT 38.ª LIRPF: new art. 23.2 reductions for
  contracts signed from 01/12/2026 (``rental_reduction_pct_2026``), read in November 2026.
  The phase 1 dataset predates it and keeps the 2023 rules (``rental_reduction_pct``).

This is an educational model of the rules, not tax advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

CENT = 0.01


def round2(value: float) -> float:
    """Round half away from zero to cents, avoiding binary artefacts such as 2.675 -> 2.67."""
    return float(f"{value + (1e-9 if value >= 0 else -1e-9):.2f}")


# --------------------------------------------------------------------------- acquisition


@dataclass(frozen=True)
class AcquisitionCost:
    """Breakdown of the capital needed to buy the property."""

    tax_base: float
    transfer_tax: float
    vat: float
    stamp_duty: float
    total: float


def acquisition_cost(
    price: float,
    reference_value: float,
    new_build: bool,
    itp_rate: float,
    ajd_rate: float,
    notary_registry: float,
    agency_fee: float,
    renovation: float,
    vat_rate: float = 0.10,
) -> AcquisitionCost:
    """Total capital invested to acquire a dwelling.

    Second-hand dwellings pay ITP (``itp_rate``) on ``max(price, reference_value)``
    (TRLITPAJD art. 10 after Ley 11/2021). New builds pay VAT on the price (10 % for
    dwellings) plus AJD (``ajd_rate``) on the same base as ITP would use. All other costs are
    added as given.
    """
    tax_base = max(price, reference_value)
    transfer_tax = vat = stamp_duty = 0.0
    if new_build:
        vat = price * vat_rate
        stamp_duty = tax_base * ajd_rate
    else:
        transfer_tax = tax_base * itp_rate
    total = price + transfer_tax + vat + stamp_duty + notary_registry + agency_fee + renovation
    return AcquisitionCost(
        tax_base=round2(tax_base),
        transfer_tax=round2(transfer_tax),
        vat=round2(vat),
        stamp_duty=round2(stamp_duty),
        total=round2(total),
    )


# --------------------------------------------------------------------------- operating yield


@dataclass(frozen=True)
class NetYield:
    """Annual operating figures and the resulting net yield in percent."""

    collected_rent: float
    operating_costs: float
    net_income: float
    net_yield_pct: float


def net_yield(
    monthly_rent: float,
    vacant_months: float,
    ibi: float,
    community_monthly: float,
    insurance: float,
    maintenance_pct: float,
    management_pct: float,
    total_investment: float,
) -> NetYield:
    """Net yield before income tax and financing: (collected rent - costs) / investment.

    ``maintenance_pct`` and ``management_pct`` are fractions of the *collected* rent.
    """
    collected = monthly_rent * (12 - vacant_months)
    costs = (
        ibi
        + community_monthly * 12
        + insurance
        + collected * maintenance_pct
        + collected * management_pct
    )
    net = collected - costs
    return NetYield(
        collected_rent=round2(collected),
        operating_costs=round2(costs),
        net_income=round2(net),
        net_yield_pct=round2(100 * net / total_investment),
    )


# --------------------------------------------------------------------------- rent caps


def is_large_holder(
    dwellings_total: int,
    residential_m2: float,
    dwellings_in_zone: int,
    zone_lowers_threshold: bool,
) -> bool:
    """Ley 12/2023 art. 3.k: "gran tenedor".

    More than ten urban residential dwellings, or more than 1,500 m2 of residential use
    (garages and storage rooms excluded). In a stressed zone whose declaration says so, five
    or more urban residential dwellings in that zone.
    """
    if dwellings_total > 10 or residential_m2 > 1500:
        return True
    return zone_lowers_threshold and dwellings_in_zone >= 5


@dataclass(frozen=True)
class RentCap:
    """The maximum initial rent of a new contract, and which rule produced it."""

    max_rent: float
    rule: str
    caps: dict[str, float] = field(default_factory=dict)


def legal_rent_cap(
    market_rent: float,
    stressed_zone: bool,
    large_holder: bool,
    previous_rent_updated: float | None,
    ten_percent_exception: bool,
    index_upper_eur_m2: float,
    area_m2: float,
    declaration_caps_unrented: bool,
) -> RentCap:
    """Maximum initial monthly rent of a new contract (LAU art. 17.6 and 17.7).

    * Outside a stressed zone: no cap, the market rent applies.
    * 17.6: if the dwelling had a habitual-residence contract in the last five years, the new
      rent cannot exceed the last rent once updated; up to 10 % more when an exception applies
      (rehabilitation, energy or accessibility works in the previous two years, or a contract
      of ten years or more).
    * 17.7: if the landlord is a large holder, the rent cannot exceed the upper value of the
      reference index ("sin perjuicio" of 17.6, so both caps apply). The same index cap
      applies to dwellings without a contract in the last five years when the zone
      declaration provides for it.

    The landlord will never ask for more than the market pays, so the result is the minimum
    of the market rent and every applicable cap.
    """
    if not stressed_zone:
        return RentCap(round2(market_rent), "no_zone", {})
    caps: dict[str, float] = {}
    if previous_rent_updated is not None:
        factor = 1.10 if ten_percent_exception else 1.0
        caps["previous_rent"] = round2(previous_rent_updated * factor)
    index_cap = round2(index_upper_eur_m2 * area_m2)
    if large_holder or (previous_rent_updated is None and declaration_caps_unrented):
        caps["index"] = index_cap
    if not caps:
        return RentCap(round2(market_rent), "zone_uncapped", {})
    binding = min(caps, key=caps.get)
    if market_rent <= caps[binding]:
        return RentCap(round2(market_rent), "market_below_cap", caps)
    return RentCap(caps[binding], binding, caps)


# --------------------------------------------------------------------------- personal income tax


@dataclass(frozen=True)
class RentalIncomeTax:
    """Net rental income for IRPF, before and after the art. 23.2 reduction."""

    depreciation: float
    deductible_financing_repairs: float
    net_income: float
    reduction_pct: int
    reduced_net_income: float


def rental_reduction_pct(
    stressed_zone: bool,
    previously_rented: bool,
    rent_cut_over_5pct: bool,
    tenant_age: int,
    public_or_social_tenant: bool,
    rehabilitation_last_2y: bool,
) -> int:
    """Reduction of positive net rental income, LIRPF art. 23.2 (contracts after 26/05/2023).

    Applied in order, the first that matches wins:
    90 % new contract in a stressed zone on a dwelling already rented, with the rent cut by
    more than 5 %; 70 % first-time rental in a stressed zone to a tenant aged 18-35, or rental
    to a public administration / non-profit for social housing; 60 % rehabilitation finished
    in the two years before the contract; 50 % otherwise.
    """
    if stressed_zone and previously_rented and rent_cut_over_5pct:
        return 90
    if (stressed_zone and not previously_rented and 18 <= tenant_age <= 35) or (
        public_or_social_tenant
    ):
        return 70
    if rehabilitation_last_2y:
        return 60
    return 50


# Dates that decide which version of art. 23.2 LIRPF applies (DT 38.ª LIRPF as worded by
# RDL 29/2026, BOE-A-2026-20823, read on 17/11/2026).
LEY_VIVIENDA_IN_FORCE = date(2023, 5, 26)
RDL_29_2026_CONTRACTS = date(2026, 12, 1)


def rental_reduction_pct_2026(
    large_holder: bool,
    previously_rented: bool,
    rent_change_pct: float | None,
    same_tenant_after_term: bool,
    below_index: bool,
    stressed_zone: bool,
    tenant_age: int,
    public_or_social_tenant: bool,
    rehabilitation_last_2y: bool,
) -> int:
    """Reduction of art. 23.2 LIRPF for contracts signed from 01/12/2026 (RDL 29/2026).

    ``rent_change_pct`` is the change of the new initial rent against the last, updated rent
    of the previous contract (``-10`` is a 10 % cut); it is ignored on a first rental.

    a) New contract on a dwelling rented before, landlord not a large holder:
       1.º rent cut by more than 5 %: 100 % if the same tenant renews after the minimum term
       and its extensions, or another tenant pays less than the reference-index limit;
       else 95 % stressed zone and tenant aged 18-35; 90 % stressed zone; 85 % tenant aged
       18-35; 70 % otherwise.
       2.º rent not above the previous one: 50 %.
       3.º rent raised: 40 % up to 5 %, 30 % up to 10 %, 25 % up to 15 %, 20 % up to 20 %,
       15 % above 20 %.
    b) First rental, landlord not a large holder: 100 % below the index limit; else 95 %,
       90 % or 85 % as in a)1.º; 50 % otherwise.
    c) 70 % when the tenant is a public administration or non-profit for social housing.
    d) 60 % rehabilitation finished in the two years before the contract.

    When several apply, the highest wins. Out of scope here: the proportional split among
    several tenants of different ages, the 80 % of a tacit extension, and the loss of the
    reduction when the contract breaks LAU art. 17.6 or the return is filed late.
    """
    young = 18 <= tenant_age <= 35
    candidates = [0]
    if not large_holder:
        if not previously_rented:
            if below_index:
                candidates.append(100)
            elif stressed_zone and young:
                candidates.append(95)
            elif stressed_zone:
                candidates.append(90)
            elif young:
                candidates.append(85)
            else:
                candidates.append(50)
        elif rent_change_pct is not None:
            if rent_change_pct < -5:
                if same_tenant_after_term or below_index:
                    candidates.append(100)
                elif stressed_zone and young:
                    candidates.append(95)
                elif stressed_zone:
                    candidates.append(90)
                elif young:
                    candidates.append(85)
                else:
                    candidates.append(70)
            elif rent_change_pct <= 0:
                candidates.append(50)
            else:
                for limit, pct in ((5, 40), (10, 30), (15, 25), (20, 20)):
                    if rent_change_pct <= limit:
                        candidates.append(pct)
                        break
                else:
                    candidates.append(15)
    if public_or_social_tenant:
        candidates.append(70)
    if rehabilitation_last_2y:
        candidates.append(60)
    return max(candidates)


def rental_income_tax(
    annual_rent: float,
    ibi: float,
    community_annual: float,
    insurance: float,
    interest: float,
    repairs: float,
    acquisition_cost_total: float,
    cadastral_value: float,
    land_share: float,
    reduction_pct: int,
) -> RentalIncomeTax:
    """Net rental income for IRPF and the reduced figure that goes to the tax base.

    * Depreciation (RIRPF art. 14): 3 % of the higher of acquisition cost (price plus the
      expenses and taxes of the purchase) and cadastral value, excluding the land. The land
      share comes from the cadastral valuation.
    * Interest plus repair and maintenance costs cannot exceed the gross income (LIRPF
      art. 23.1.a.1º); the excess carries forward four years and is ignored here.
    * The reduction applies only when the net income is positive (art. 23.2).
    """
    depreciation = 0.03 * max(acquisition_cost_total, cadastral_value) * (1 - land_share)
    financing_repairs = min(interest + repairs, annual_rent)
    net = annual_rent - ibi - community_annual - insurance - financing_repairs - depreciation
    reduced = net * (1 - reduction_pct / 100) if net > 0 else net
    return RentalIncomeTax(
        depreciation=round2(depreciation),
        deductible_financing_repairs=round2(financing_repairs),
        net_income=round2(net),
        reduction_pct=reduction_pct if net > 0 else 0,
        reduced_net_income=round2(reduced),
    )


# --------------------------------------------------------------------------- financing


def mortgage_payment(principal: float, annual_rate: float, years: int) -> float:
    """Monthly payment of a French amortisation loan (constant instalments)."""
    n = years * 12
    if annual_rate == 0:
        return principal / n
    i = annual_rate / 12
    return principal * i / (1 - (1 + i) ** -n)


@dataclass(frozen=True)
class CashOnCash:
    """Leveraged return on the investor's own money."""

    monthly_payment: float
    annual_cash_flow: float
    equity: float
    cash_on_cash_pct: float


def cash_on_cash(
    total_investment: float,
    loan: float,
    annual_rate: float,
    years: int,
    annual_net_operating_income: float,
) -> CashOnCash:
    """(Net operating income - 12 * mortgage payment) / (total investment - loan).

    The monthly payment is rounded to cents before multiplying, as a bank would charge it.
    """
    payment = round2(mortgage_payment(loan, annual_rate, years))
    cash_flow = annual_net_operating_income - 12 * payment
    equity = total_investment - loan
    return CashOnCash(
        monthly_payment=payment,
        annual_cash_flow=round2(cash_flow),
        equity=round2(equity),
        cash_on_cash_pct=round2(100 * cash_flow / equity),
    )


# --------------------------------------------------------------------------- inverse problem


def max_price_for_target_yield(
    annual_net_operating_income: float,
    target_yield: float,
    itp_rate: float,
    fixed_costs: float,
) -> float:
    """Highest second-hand price that still reaches ``target_yield`` net.

    Solves  NOI / (P * (1 + itp) + F) = y  for P, assuming the reference value does not
    exceed the price (so ITP is paid on the price). ``target_yield`` is a fraction.
    """
    return round2((annual_net_operating_income / target_yield - fixed_costs) / (1 + itp_rate))
