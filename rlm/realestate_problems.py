"""Verifiable problem generator for the buy-to-let investment domain (phase 1 dataset).

Same pattern as ``generate_problems.py``: ``sample_params`` draws one problem, ``solve``
computes the answer with the rule engine in ``realestate_rules.py`` (reference
implementation and verifier at once), and ``render`` writes the statement in Spanish.

Design decisions, explained in ``docs/propuesta.md``:

* The statement gives the *data* (regional tax rate, rent index, cadastral values…). The
  model must know the *rules* (which base, which cap, which reduction). ``--with-rules``
  prepends a rule sheet for the ablation that measures how much of the task is knowledge.
* Parameters are sampled around the thresholds where the rules branch: reference value
  above and below the price, landlords with 4-6 and 9-12 dwellings, tenants around 35,
  negative net income, interest plus repairs above gross income.
* Each row stores ``checkpoints``: intermediate values the reasoning should contain. The
  third GRPO reward uses them.
* ``train`` and ``test`` share the six families; ``ood`` holds two *compositions* of rules
  that never appear together in training.

Generate everything with one command (a shared fingerprint set guarantees the splits do
not overlap)::

    uv run python -m rlm.realestate_problems --out-dir rlm/data
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rlm import realestate_rules as rules

TRAIN_FAMILIES = (
    "acquisition_cost",
    "net_yield",
    "legal_rent",
    "irpf_rental",
    "cash_on_cash",
    "max_price",
)
OOD_FAMILIES = ("max_price_capped", "becomes_large_holder")

EUR_TOLERANCE_ABS = 0.01
EUR_TOLERANCE_REL = 0.0005
PCT_TOLERANCE_ABS = 0.01

EUR_ASKS = (
    "Responde en euros con dos decimales.",
    "Da el resultado en euros, con dos decimales.",
    "Indica la cifra en euros con dos decimales.",
)
PCT_ASKS = (
    "Responde en porcentaje con dos decimales.",
    "Da el resultado en %, con dos decimales.",
    "Expresa la respuesta como porcentaje con dos decimales.",
)

DISTRACTORS = (
    "Es un tercero exterior con ascensor.",
    "La vivienda tiene orientación sur y dos baños.",
    "El barrio tiene metro a cinco minutos.",
    "La cocina se reformó hace unos años.",
    "El edificio es de 1978 y tiene la ITE favorable.",
    "Tiene plaza de garaje incluida en el precio.",
    "",
    "",
)


# --------------------------------------------------------------------------- formatting


def eur(value: float, decimals: int | None = None) -> str:
    """Spanish money format: 208850 -> '208.850 €', 1234.5 -> '1.234,50 €'."""
    if decimals is None:
        decimals = 0 if float(value).is_integer() else 2
    text = f"{abs(value):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if value < 0 else ''}{text} €"


def pct(fraction: float) -> str:
    """Spanish percent format from a fraction: 0.075 -> '7,5 %'."""
    text = f"{100 * fraction:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{text} %"


def num(value: float) -> str:
    """Spanish number without unit: 12.5 -> '12,5'."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def lognormal_round(
    rng: random.Random, median: float, sigma: float, lo: float, hi: float, step: float
) -> float:
    """Log-normal draw clipped to [lo, hi] and rounded to ``step``."""
    value = min(max(median * math.exp(rng.gauss(0, sigma)), lo), hi)
    return round(value / step) * step


# --------------------------------------------------------------------------- problem record


@dataclass
class RealEstateProblem:
    question: str
    answer: str
    family: str
    unit: str
    tolerance_abs: float
    tolerance_rel: float
    checkpoints: list[float]
    params: dict[str, Any]
    template_id: int
    branches: dict[str, str] = field(default_factory=dict)


@dataclass
class Solution:
    answer: float
    unit: str
    checkpoints: list[float]
    branches: dict[str, str]


# --------------------------------------------------------------------------- sampling


def _sample_itp(rng: random.Random) -> float:
    return rng.choice([0.06, 0.07, 0.08, 0.09, 0.10, 0.10, 0.05, 0.04, 0.035])


def _sample_zone_context(rng: random.Random, ood_holder: bool = False) -> dict[str, Any]:
    """Landlord and zone for a rent-cap problem, sampled around the legal thresholds."""
    area = rng.randint(38, 125)
    index_upper = round(rng.uniform(9.0, 22.0), 1)
    market = round(area * index_upper * rng.uniform(0.85, 1.35) / 10) * 10
    stressed = True if ood_holder else rng.random() < 0.8
    zone_lowers = True if ood_holder else rng.random() < 0.5
    if ood_holder:
        in_zone = 4  # owns four here: the purchase is the fifth
        total = rng.randint(4, 9)
    else:
        total = rng.choice([rng.randint(1, 3), rng.randint(4, 6), rng.randint(9, 12)])
        in_zone = rng.randint(0, total)
    residential_m2 = round(total * rng.uniform(55, 115))
    previous = None
    if rng.random() < 0.6:
        previous = round(market * rng.uniform(0.7, 1.05) / 5) * 5
    return {
        "area_m2": area,
        "index_upper_eur_m2": index_upper,
        "market_rent": market,
        "stressed_zone": stressed,
        "zone_lowers_threshold": zone_lowers,
        "dwellings_total": total,
        "dwellings_in_zone": in_zone,
        "residential_m2": residential_m2,
        "previous_rent_updated": previous,
        "ten_percent_exception": previous is not None and rng.random() < 0.2,
        "declaration_caps_unrented": rng.random() < 0.5,
    }


def sample_params(family: str, rng: random.Random) -> dict[str, Any]:
    """Draw the data of one problem of ``family``."""
    p: dict[str, Any] = {"family": family}
    if family == "acquisition_cost":
        price = lognormal_round(rng, 190_000, 0.45, 60_000, 700_000, 500)
        new_build = rng.random() < 0.2
        ratio = rng.uniform(0.75, 1.0) if new_build else rng.uniform(0.8, 1.3)
        p.update(
            price=price,
            reference_value=round(price * ratio, -2),
            new_build=new_build,
            itp_rate=_sample_itp(rng),
            ajd_rate=rng.choice([0.005, 0.007, 0.01, 0.012, 0.015]),
            notary_registry=round(rng.uniform(1_500, 4_500), -1),
            agency_fee=rng.choice([0, 0, round(price * rng.choice([0.02, 0.03]), -1)]),
            renovation=rng.choice([0, round(rng.uniform(3_000, 45_000), -2)]),
        )
    elif family == "net_yield":
        rent = round(rng.uniform(450, 2_200), -1)
        p.update(
            monthly_rent=rent,
            vacant_months=rng.choice([0, 0, 0.5, 1, 1, 2]),
            ibi=round(rng.uniform(150, 1_200)),
            community_monthly=round(rng.uniform(20, 150)),
            insurance=round(rng.uniform(120, 450)),
            maintenance_pct=rng.choice([0, 0.03, 0.05]),
            management_pct=rng.choice([0, 0, 0.04, 0.06, 0.08]),
            total_investment=round(rent * 12 / rng.uniform(0.045, 0.09), -3),
        )
    elif family in ("legal_rent", "becomes_large_holder"):
        p.update(_sample_zone_context(rng, ood_holder=family == "becomes_large_holder"))
    elif family == "irpf_rental":
        rent = round(rng.uniform(5_000, 24_000), -2)
        acquisition = round(rng.uniform(80_000, 400_000), -3)
        cadastral = round(acquisition * rng.uniform(0.3, 0.8), -3)
        interest = rng.choice([0, round(rng.uniform(500, 6_000), -1)])
        repairs = rng.choice([0, round(rng.uniform(100, 3_000), -1)])
        if rng.random() < 0.1:  # force the interest + repairs limit to bind
            interest = round(rent * rng.uniform(0.8, 1.2), -1)
            repairs = round(rng.uniform(500, 3_000), -1)
        p.update(
            annual_rent=rent,
            ibi=round(rng.uniform(150, 1_200)),
            community_annual=round(rng.uniform(240, 1_800), -1),
            insurance=round(rng.uniform(120, 450)),
            interest=interest,
            repairs=repairs,
            acquisition_cost_total=acquisition,
            cadastral_value=cadastral,
            land_value=round(cadastral * rng.uniform(0.2, 0.6), -2),
            stressed_zone=rng.random() < 0.6,
            previously_rented=rng.random() < 0.5,
            rent_cut_over_5pct=rng.random() < 0.55,
            tenant_age=rng.choice([rng.randint(19, 34), 35, 36, rng.randint(37, 70)]),
            public_or_social_tenant=rng.random() < 0.07,
            rehabilitation_last_2y=rng.random() < 0.2,
        )
    elif family == "cash_on_cash":
        investment = round(rng.uniform(100_000, 450_000), -3)
        p.update(
            total_investment=investment,
            loan=round(investment * rng.uniform(0.5, 0.8), -3),
            annual_rate=round(rng.uniform(0.02, 0.045) * 2000) / 2000,
            years=rng.choice([15, 20, 25, 30]),
            noi=round(investment * rng.uniform(0.035, 0.065), -1),
        )
    elif family == "max_price":
        p.update(
            noi=round(rng.uniform(4_000, 20_000), -1),
            target_yield=rng.choice([0.04, 0.045, 0.05, 0.055, 0.06, 0.065, 0.07]),
            itp_rate=_sample_itp(rng),
            fixed_costs=round(rng.uniform(2_000, 25_000), -2),
        )
    elif family == "max_price_capped":
        p.update(_sample_zone_context(rng))
        p.update(
            annual_costs=round(rng.uniform(900, 3_000), -1),
            target_yield=rng.choice([0.04, 0.045, 0.05, 0.055, 0.06]),
            itp_rate=_sample_itp(rng),
            fixed_costs=round(rng.uniform(2_000, 20_000), -2),
        )
    else:
        raise ValueError(f"unknown family {family}")
    return p


# --------------------------------------------------------------------------- solving


def _rent_cap(p: dict[str, Any], purchase: bool = False) -> tuple[rules.RentCap, bool]:
    extra = 1 if purchase else 0
    holder = rules.is_large_holder(
        p["dwellings_total"] + extra,
        p["residential_m2"] + (p["area_m2"] if purchase else 0),
        p["dwellings_in_zone"] + extra,
        p["zone_lowers_threshold"],
    )
    cap = rules.legal_rent_cap(
        market_rent=p["market_rent"],
        stressed_zone=p["stressed_zone"],
        large_holder=holder,
        previous_rent_updated=p["previous_rent_updated"],
        ten_percent_exception=p["ten_percent_exception"],
        index_upper_eur_m2=p["index_upper_eur_m2"],
        area_m2=p["area_m2"],
        declaration_caps_unrented=p["declaration_caps_unrented"],
    )
    return cap, holder


def solve(p: dict[str, Any]) -> Solution:
    """Reference implementation: the answer, the checkpoints and the branches taken."""
    family = p["family"]
    if family == "acquisition_cost":
        r = rules.acquisition_cost(
            p["price"],
            p["reference_value"],
            p["new_build"],
            p["itp_rate"],
            p["ajd_rate"],
            p["notary_registry"],
            p["agency_fee"],
            p["renovation"],
        )
        taxes = [r.vat, r.stamp_duty] if p["new_build"] else [r.transfer_tax]
        return Solution(
            r.total,
            "eur",
            [r.tax_base, *taxes],
            {
                "new_build": str(p["new_build"]),
                "base": "reference" if p["reference_value"] > p["price"] else "price",
            },
        )
    if family == "net_yield":
        r = rules.net_yield(
            p["monthly_rent"],
            p["vacant_months"],
            p["ibi"],
            p["community_monthly"],
            p["insurance"],
            p["maintenance_pct"],
            p["management_pct"],
            p["total_investment"],
        )
        return Solution(
            r.net_yield_pct,
            "pct",
            [r.collected_rent, r.operating_costs, r.net_income],
            {"vacancy": str(p["vacant_months"] > 0), "management": str(p["management_pct"] > 0)},
        )
    if family in ("legal_rent", "becomes_large_holder"):
        cap, holder = _rent_cap(p, purchase=family == "becomes_large_holder")
        return Solution(
            rules.round2(12 * cap.max_rent),
            "eur",
            [cap.max_rent],
            {"rule": cap.rule, "large_holder": str(holder), "stressed": str(p["stressed_zone"])},
        )
    if family == "irpf_rental":
        reduction = rules.rental_reduction_pct(
            p["stressed_zone"],
            p["previously_rented"],
            p["rent_cut_over_5pct"],
            p["tenant_age"],
            p["public_or_social_tenant"],
            p["rehabilitation_last_2y"],
        )
        r = rules.rental_income_tax(
            p["annual_rent"],
            p["ibi"],
            p["community_annual"],
            p["insurance"],
            p["interest"],
            p["repairs"],
            p["acquisition_cost_total"],
            p["cadastral_value"],
            p["land_value"] / p["cadastral_value"],
            reduction,
        )
        return Solution(
            r.reduced_net_income,
            "eur",
            [r.depreciation, r.net_income],
            {
                "reduction": str(r.reduction_pct),
                "limit_binds": str(p["interest"] + p["repairs"] > p["annual_rent"]),
                "negative": str(r.net_income <= 0),
            },
        )
    if family == "cash_on_cash":
        r = rules.cash_on_cash(
            p["total_investment"], p["loan"], p["annual_rate"], p["years"], p["noi"]
        )
        return Solution(
            r.cash_on_cash_pct,
            "pct",
            [r.monthly_payment, r.annual_cash_flow, r.equity],
            {"negative_cash_flow": str(r.annual_cash_flow < 0), "years": str(p["years"])},
        )
    if family == "max_price":
        price = rules.max_price_for_target_yield(
            p["noi"], p["target_yield"], p["itp_rate"], p["fixed_costs"]
        )
        return Solution(
            price,
            "eur",
            [rules.round2(p["noi"] / p["target_yield"])],
            {"target": str(p["target_yield"])},
        )
    if family == "max_price_capped":
        cap, holder = _rent_cap(p)
        noi = 12 * cap.max_rent - p["annual_costs"]
        price = rules.max_price_for_target_yield(
            noi, p["target_yield"], p["itp_rate"], p["fixed_costs"]
        )
        return Solution(
            price,
            "eur",
            [cap.max_rent, rules.round2(noi)],
            {"rule": cap.rule, "large_holder": str(holder)},
        )
    raise ValueError(f"unknown family {family}")


# --------------------------------------------------------------------------- rendering


def _zone_text(p: dict[str, Any], purchase: bool = False) -> list[str]:
    """Sentences describing the landlord, the zone and the previous contract."""
    s = []
    if p["stressed_zone"]:
        s.append("La vivienda está en una zona declarada de mercado residencial tensionado.")
        s.append(
            "La declaración de la zona rebaja el umbral de gran tenedor a cinco viviendas en "
            "la zona."
            if p["zone_lowers_threshold"]
            else "La declaración de la zona no modifica el umbral general de gran tenedor."
        )
        s.append(
            "La resolución extiende el índice de referencia a las viviendas sin contrato en "
            "los últimos cinco años."
            if p["declaration_caps_unrented"]
            else "La resolución no extiende el índice a las viviendas sin contrato previo."
        )
    else:
        s.append("La vivienda no está en ninguna zona de mercado residencial tensionado.")
    owner = "El inversor" if purchase else "El propietario"
    if purchase:
        s.append(
            f"{owner} ya tiene {p['dwellings_total']} viviendas ({p['residential_m2']} m² en "
            f"total), {p['dwellings_in_zone']} de ellas en esta misma zona, y se plantea "
            f"comprar esta."
        )
    else:
        s.append(
            f"{owner} tiene {p['dwellings_total']} "
            f"{'vivienda' if p['dwellings_total'] == 1 else 'viviendas'} en total, con "
            f"{p['residential_m2']} m² de uso residencial; {p['dwellings_in_zone']} "
            f"{'está' if p['dwellings_in_zone'] == 1 else 'están'} en esta zona."
        )
    if p["previous_rent_updated"] is None:
        s.append("La vivienda no ha estado alquilada en los últimos cinco años.")
    else:
        s.append(
            f"Hace dos años tuvo un contrato de vivienda habitual cuya última renta, ya "
            f"actualizada, es de {eur(p['previous_rent_updated'])} al mes."
        )
        if p["ten_percent_exception"]:
            s.append(
                "Tras ese contrato se hicieron obras de mejora de la eficiencia energética "
                "que cumplen los requisitos de la ley."
            )
    s.append(
        f"Tiene {p['area_m2']} m², el valor superior del índice de referencia (SERPAVI) es "
        f"{num(p['index_upper_eur_m2'])} €/m² al mes y el mercado pagaría "
        f"{eur(p['market_rent'])} al mes."
    )
    return s


def render(p: dict[str, Any], rng: random.Random) -> tuple[str, int]:
    """Statement in Spanish, one of several templates per family, facts in shuffled order."""
    family = p["family"]
    distractor = rng.choice(DISTRACTORS)
    eur_ask = rng.choice(EUR_ASKS)
    pct_ask = rng.choice(PCT_ASKS)

    if family == "acquisition_cost":
        kind = "de obra nueva" if p["new_build"] else "de segunda mano"
        facts = [
            f"El valor de referencia del Catastro es {eur(p['reference_value'])}.",
            (
                f"El tipo de AJD de la comunidad es del {pct(p['ajd_rate'])}."
                if p["new_build"]
                else f"El tipo de ITP de la comunidad es del {pct(p['itp_rate'])}."
            ),
            f"Notaría, registro y gestoría suman {eur(p['notary_registry'])}.",
            (
                f"La agencia cobra {eur(p['agency_fee'])} al comprador."
                if p["agency_fee"]
                else "No hay comisión de agencia."
            ),
            (
                f"Hay que invertir {eur(p['renovation'])} en reforma."
                if p["renovation"]
                else "No necesita reforma."
            ),
        ]
        rng.shuffle(facts)
        templates = [
            f"Quiero comprar para alquilar una vivienda {kind} por {eur(p['price'])}. "
            + " ".join(facts)
            + f" {distractor} ¿Cuánto capital necesito en total? {eur_ask}",
            f"Precio de compra: {eur(p['price'])} (vivienda {kind}). "
            + " ".join(facts)
            + f" {distractor} Calcula la inversión total, impuestos incluidos. {eur_ask}",
            f"Estoy analizando un piso {kind} que se vende por {eur(p['price'])}. {distractor} "
            + " ".join(facts)
            + f" ¿Cuál es el desembolso total de la operación? {eur_ask}",
        ]
    elif family == "net_yield":
        facts = [
            f"El IBI es de {eur(p['ibi'])} al año.",
            f"La comunidad cuesta {eur(p['community_monthly'])} al mes.",
            f"El seguro de hogar e impago cuesta {eur(p['insurance'])} al año.",
            (
                f"Calculo un {pct(p['maintenance_pct'])} de los ingresos cobrados para "
                f"mantenimiento."
                if p["maintenance_pct"]
                else "No reservo nada para mantenimiento."
            ),
            (
                f"La gestora cobra un {pct(p['management_pct'])} de lo cobrado."
                if p["management_pct"]
                else "Lo gestiono yo mismo, sin gestora."
            ),
            (
                f"Espero {num(p['vacant_months'])} "
                f"{'mes' if p['vacant_months'] == 1 else 'meses'} al año sin inquilino."
                if p["vacant_months"]
                else "Espero tenerlo alquilado todo el año."
            ),
        ]
        rng.shuffle(facts)
        templates = [
            f"He invertido {eur(p['total_investment'])} en total en un piso que alquilo por "
            f"{eur(p['monthly_rent'])} al mes. "
            + " ".join(facts)
            + f" {distractor} ¿Qué rentabilidad neta anual obtengo, antes de impuestos? {pct_ask}",
            f"Renta mensual: {eur(p['monthly_rent'])}. Inversión total: "
            f"{eur(p['total_investment'])}. "
            + " ".join(facts)
            + f" Calcula la rentabilidad neta sobre la inversión total. {pct_ask}",
            f"{distractor} Un piso me costó {eur(p['total_investment'])} con todos los gastos y "
            f"lo alquilo a {eur(p['monthly_rent'])} mensuales. "
            + " ".join(facts)
            + f" ¿Cuál es su rentabilidad neta? {pct_ask}",
        ]
    elif family in ("legal_rent", "becomes_large_holder"):
        purchase = family == "becomes_large_holder"
        facts = _zone_text(p, purchase=purchase)
        head, tail = facts[:-1], facts[-1]
        rng.shuffle(head)
        body = " ".join(head + [tail])
        if purchase:
            templates = [
                body + f" {distractor} Si lo compra, ¿qué renta anual máxima podrá cobrar en el "
                f"primer año del nuevo contrato? {eur_ask}",
                "Me planteo una nueva compra. "
                + body
                + f" Tras la compra, ¿cuánto podré ingresar como máximo en el primer año del "
                f"nuevo contrato de esta vivienda? {eur_ask}",
            ]
        else:
            templates = [
                body + f" {distractor} ¿Cuál es la renta anual máxima que puede cobrar en el "
                f"primer año del nuevo contrato? {eur_ask}",
                "Voy a firmar un nuevo contrato de alquiler de vivienda habitual. "
                + body
                + f" ¿Cuánto puedo ingresar como máximo en el primer año? {eur_ask}",
                f"{distractor} " + body + " Calcula la renta máxima del primer año del nuevo "
                f"contrato (doce mensualidades). {eur_ask}",
            ]
    elif family == "irpf_rental":
        tenant = (
            "una entidad sin ánimo de lucro que la destina a alquiler social"
            if p["public_or_social_tenant"]
            else f"una persona de {p['tenant_age']} años"
        )
        facts = [
            f"El IBI es de {eur(p['ibi'])}, la comunidad de {eur(p['community_annual'])} al año y "
            f"el seguro de {eur(p['insurance'])}.",
            f"Pago {eur(p['interest'])} de intereses de la hipoteca al año."
            if p["interest"]
            else "No tengo hipoteca.",
            f"Este año gasté {eur(p['repairs'])} en reparaciones."
            if p["repairs"]
            else "No hubo reparaciones.",
            f"Compré por un coste total, gastos e impuestos incluidos, de "
            f"{eur(p['acquisition_cost_total'])}.",
            f"El valor catastral es {eur(p['cadastral_value'])}, del que "
            f"{eur(p['land_value'])} corresponde al suelo.",
            "Está en zona de mercado residencial tensionado."
            if p["stressed_zone"]
            else "No está en zona tensionada.",
            (
                "Ya había estado alquilada antes"
                + (
                    " y en el nuevo contrato bajé la renta más de un 5 % respecto al anterior."
                    if p["rent_cut_over_5pct"]
                    else ", con una renta igual o superior a la actual."
                )
            )
            if p["previously_rented"]
            else "Es la primera vez que la alquilo.",
            "Terminé una rehabilitación de la vivienda un año antes de firmar el contrato."
            if p["rehabilitation_last_2y"]
            else "No he hecho obras de rehabilitación.",
        ]
        rng.shuffle(facts)
        templates = [
            f"Alquilo una vivienda como residencia habitual a {tenant} por "
            f"{eur(p['annual_rent'])} al año (contrato firmado en 2025). "
            + " ".join(facts)
            + f" {distractor} ¿Cuál es el rendimiento neto reducido del capital inmobiliario "
            f"que declaro en el IRPF? {eur_ask}",
            f"Ingresos por alquiler del año: {eur(p['annual_rent'])}. Inquilino: {tenant}, "
            f"contrato de 2025. "
            + " ".join(facts)
            + f" Calcula el rendimiento neto reducido a efectos del IRPF. {eur_ask}",
        ]
    elif family == "cash_on_cash":
        templates = [
            f"Invierto {eur(p['total_investment'])} en total en un piso y financio "
            f"{eur(p['loan'])} con una hipoteca a {p['years']} años al "
            f"{pct(p['annual_rate'])} fijo. El piso genera {eur(p['noi'])} netos al año antes "
            f"de la hipoteca. {distractor} ¿Qué rentabilidad obtengo sobre el dinero que pongo "
            f"yo (cash-on-cash)? {pct_ask}",
            f"Operación: inversión total {eur(p['total_investment'])}, préstamo "
            f"{eur(p['loan'])} a {p['years']} años, interés fijo del {pct(p['annual_rate'])}, "
            f"ingreso neto operativo de {eur(p['noi'])} anuales. Calcula el flujo de caja "
            f"sobre capital propio. {pct_ask}",
            f"{distractor} Con una hipoteca de {eur(p['loan'])} ({p['years']} años, "
            f"{pct(p['annual_rate'])}) compro un piso que en total me cuesta "
            f"{eur(p['total_investment'])} y que da {eur(p['noi'])} netos al año. ¿Cuál es mi "
            f"rentabilidad sobre fondos propios? {pct_ask}",
        ]
    elif family in ("max_price", "max_price_capped"):
        if family == "max_price":
            income = f"El piso generaría {eur(p['noi'])} netos al año."
        else:
            facts = _zone_text(p)
            head, tail = facts[:-1], facts[-1]
            rng.shuffle(head)
            income = " ".join(head + [tail]) + (
                f" Los gastos anuales (IBI, comunidad, seguro) suman {eur(p['annual_costs'])} y "
                f"lo alquilaría todo el año por la renta máxima que permita la ley."
            )
        templates = [
            f"Busco una rentabilidad neta del {pct(p['target_yield'])} sobre la inversión "
            f"total. {income} El ITP es del {pct(p['itp_rate'])} y el valor de referencia es "
            f"inferior al precio. Notaría, registro y reforma suman {eur(p['fixed_costs'])}. "
            f"{distractor} ¿Cuál es el precio máximo que debería pagar? {eur_ask}",
            f"{income} Quiero un {pct(p['target_yield'])} neto. Impuesto de transmisiones: "
            f"{pct(p['itp_rate'])} sobre el precio. Otros gastos de compra: "
            f"{eur(p['fixed_costs'])}. ¿Hasta qué precio de compra me sale la operación? "
            f"{eur_ask}",
        ]
    else:
        raise ValueError(f"unknown family {family}")

    template_id = rng.randrange(len(templates))
    text = " ".join(templates[template_id].split())
    return text, template_id


RULES_TEXT = """Reglas (resumen para la ablación con reglas en el enunciado):
- ITP de vivienda usada: tipo de la comunidad sobre el mayor entre precio y valor de
  referencia. Obra nueva: IVA del 10 % sobre el precio más AJD sobre el mayor de ambos.
- Rentabilidad neta: (renta cobrada - gastos) / inversión total. Los porcentajes de
  mantenimiento y gestión se aplican sobre la renta cobrada.
- Gran tenedor: más de 10 viviendas o más de 1.500 m² residenciales; o 5 o más en una zona
  tensionada cuya declaración rebaje el umbral.
- Zona tensionada: si hubo contrato en los últimos cinco años, la renta no puede superar la
  última actualizada (hasta un 10 % más con obras de mejora). Si el propietario es gran
  tenedor, además no puede superar el índice de referencia × m². Sin contrato previo, se
  aplica el índice si la resolución lo prevé. Nunca se cobra más que el mercado.
- IRPF: amortización del 3 % sobre el mayor entre coste de adquisición y valor catastral,
  solo la parte de construcción. Intereses + reparaciones no pueden superar los ingresos.
  Reducción sobre rendimiento neto positivo: 90 % (zona tensionada, ya alquilada, renta
  rebajada más de un 5 %), 70 % (zona tensionada, primera vez, inquilino de 18 a 35 años; o
  alquiler social a entidad), 60 % (rehabilitación en los dos años anteriores), 50 % resto.
- Cuota de hipoteca: sistema francés, redondeada al céntimo.
- Precio máximo: NOI / (P × (1 + ITP) + gastos) = rentabilidad objetivo."""


# --------------------------------------------------------------------------- generation


def _fingerprint(p: dict[str, Any]) -> str:
    return json.dumps(p, sort_keys=True, default=str)


def _tolerances(unit: str) -> tuple[float, float]:
    if unit == "eur":
        return EUR_TOLERANCE_ABS, EUR_TOLERANCE_REL
    return PCT_TOLERANCE_ABS, 0.0


def generate(
    families: tuple[str, ...], n_per_family: int, seed: str, seen: set[str]
) -> list[RealEstateProblem]:
    """``n_per_family`` unique problems of each family, skipping fingerprints in ``seen``."""
    rng = random.Random(seed)
    problems: list[RealEstateProblem] = []
    for family in families:
        made = attempts = 0
        while made < n_per_family:
            attempts += 1
            if attempts > 200 * n_per_family:
                raise RuntimeError(f"parameter space of {family} too small")
            params = sample_params(family, rng)
            key = _fingerprint(params)
            if key in seen:
                continue
            seen.add(key)
            solution = solve(params)
            question, template_id = render(params, rng)
            tol_abs, tol_rel = _tolerances(solution.unit)
            problems.append(
                RealEstateProblem(
                    question=question,
                    answer=f"{solution.answer:.2f}",
                    family=family,
                    unit=solution.unit,
                    tolerance_abs=tol_abs,
                    tolerance_rel=tol_rel,
                    checkpoints=solution.checkpoints,
                    params=params,
                    template_id=template_id,
                    branches=solution.branches,
                )
            )
            made += 1
    rng.shuffle(problems)
    return problems


def _leaks(problem: RealEstateProblem) -> bool:
    """True when the answer appears in the statement written as the statement writes numbers.

    We look for the value *with its unit* ("6.997,20 €", "2,45 %"): a bare "2" matches half
    the statements by coincidence and says nothing about leakage.
    """
    value = float(problem.answer)
    if problem.unit == "eur":
        candidates = {eur(value, 2), eur(value)}
    else:
        candidates = {pct(value / 100)}
    return any(c in problem.question for c in candidates)


def describe(problems: list[RealEstateProblem]) -> dict[str, Any]:
    """Branch coverage per family, templates and leakage: the numbers for EXPERIMENTS.md."""
    by_family: dict[str, dict[str, Counter]] = {}
    for problem in problems:
        branches = by_family.setdefault(problem.family, {})
        for name, value in problem.branches.items():
            branches.setdefault(name, Counter())[value] += 1
    return {
        "n_problems": len(problems),
        "families": dict(Counter(p.family for p in problems)),
        "templates_per_family": {
            f: len({p.template_id for p in problems if p.family == f}) for f in by_family
        },
        "branches": {f: {k: dict(v) for k, v in b.items()} for f, b in by_family.items()},
        "answer_leaked_in_statement": sum(_leaks(p) for p in problems),
    }


def write_jsonl(
    problems: list[RealEstateProblem], path: Path, split: str, with_rules: bool
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for problem in problems:
            row = problem.__dict__.copy()
            if with_rules:
                row["question"] = f"{RULES_TEXT}\n\n{row['question']}"
            row["split"] = split
            row["label_source"] = "generator"
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir", default="rlm/data")
    parser.add_argument("--n-train", type=int, default=400, help="per family")
    parser.add_argument("--n-test", type=int, default=50, help="per family")
    parser.add_argument("--n-ood", type=int, default=75, help="per OOD family")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--with-rules", action="store_true", help="prepend the rule sheet")
    args = parser.parse_args()

    seen: set[str] = set()
    splits = {
        "train": generate(TRAIN_FAMILIES, args.n_train, f"{args.seed}-train", seen),
        "test": generate(TRAIN_FAMILIES, args.n_test, f"{args.seed}-test", seen),
        "test_ood": generate(OOD_FAMILIES, args.n_ood, f"{args.seed}-ood", seen),
    }
    out_dir = Path(args.out_dir)
    suffix = "_with_rules" if args.with_rules else ""
    report = {}
    for split, problems in splits.items():
        path = out_dir / f"{split}{suffix}.jsonl"
        write_jsonl(problems, path, split, args.with_rules)
        report[split] = describe(problems)
        print(f"{len(problems):>5} problemas -> {path}")
    stats_path = out_dir / f"dataset_stats{suffix}.json"
    stats_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"estadísticas de ramas y fugas -> {stats_path}")
    example = splits["train"][0]
    print(f"\nEjemplo ({example.family}):\n{example.question}\nRespuesta: {example.answer}")


if __name__ == "__main__":
    main()
