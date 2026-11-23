"""General ITP rate for second-hand dwellings, by autonomous community.

This is *data*, not a rule: it changes with each regional budget law. The rule (ITP on the
higher of price and cadastral reference value) lives in ``rlm/realestate_rules.py``.

The table was first taken from Gibobs, "ITP 2026" (https://www.gibobs.com/blog/itp-2026/),
consulted 2026-11-17. On 2026-11-23 every row was checked against an official source (the
community's tax agency, its official gazette or the BOE), linked next to the row. Four rates
and two notes were wrong in the secondary source and have been corrected here.

Several communities use a progressive scale or special regimes. For them the table holds the
general (lowest) rate, and ``note`` explains what the tool cannot model; the tool returns
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

SOURCE = "Haciendas autonómicas y forales (fuentes oficiales), verificado el 23/11/2026"


@dataclass(frozen=True)
class ItpRate:
    rate_pct: float
    note: str = ""
    verified: bool = False


ITP_GENERAL: dict[str, ItpRate] = {
    # https://www.juntadeandalucia.es/sites/default/files/2024-07/ATRIAN_GUIA_ITPAJD.pdf (consultada 23/11/2026)
    "andalucia": ItpRate(7.0, verified=True),
    # https://aragon.es/documents/d/guest/transmision-de-un-inmueble-por-un-sujeto-pasivo-del-iva-pdf (consultada 23/11/2026)
    "aragon": ItpRate(
        8.0,
        "tarifa progresiva: 8 % hasta 400.000 €, sube por tramos hasta el 10 % por encima de 750.000 €",
        verified=True,
    ),
    # https://www.asturias.es/Asturias/descargas/PDF_TEMAS/Economia/consultas_tributarias/consulta_1_2018.pdf (consultada 23/11/2026)
    # Corregida la nota: no es una escala por tramos, el tipo se elige por el valor total y se aplica a toda la base.
    "asturias": ItpRate(
        8.0,
        "tipo único según el valor total: 8 % hasta 300.000 €, 9 % hasta 500.000 €, 10 % por encima (sobre toda la base)",
        verified=True,
    ),
    # https://www.atib.es/TA/contenido.aspx?Id=9854&lang=es (consultada 23/11/2026)
    # Corregida la nota: el tramo más alto es el 13 %, no el 11 %.
    "baleares": ItpRate(
        8.0,
        "tarifa progresiva: 8 % hasta 400.000 €, 9 %, 10 %, 12 % y 13 % por encima de 2.000.000 €",
        verified=True,
    ),
    # https://sede.gobiernodecanarias.org/boc/boc-a-2018-235-5589.pdf (art. 31; consultada 23/11/2026)
    "canarias": ItpRate(6.5, verified=True),
    # https://www.boe.es/boe/dias/2024/01/25/pdfs/BOE-A-2024-1373.pdf (Ley de Cantabria 3/2023; consultada 23/11/2026)
    # Corregido: 10 % -> 9 % desde el 1/1/2024.
    "cantabria": ItpRate(9.0, verified=True),
    # https://portaltributario.jccm.es/sites/portaltributario.castillalamancha.es/files/documentos/pdf/20260511/c-63-2026-itpajd-tpo.pdf (consultada 23/11/2026)
    "castilla_la_mancha": ItpRate(9.0, verified=True),
    # https://tributos.jcyl.es/web/es/preguntas-frecuentes/compra-vivienda-usada.html (consultada 23/11/2026)
    # Añadida la nota: el tramo del 10 % faltaba.
    "castilla_y_leon": ItpRate(
        8.0,
        "la parte de la base que supera 250.000 € tributa al 10 %",
        verified=True,
    ),
    # https://atc.gencat.cat/ca/tributs/itpajd/operacions/immobles/compravenda-immobles/ (consultada 23/11/2026)
    # https://economia.gencat.cat/ca/inici/nota-premsa/?id=701402 (tramos del 12 % y 13 %; consultada 23/11/2026)
    "cataluna": ItpRate(
        10.0,
        "tarifa progresiva desde 2026: 10 % hasta 600.000 €, 11 % hasta 900.000 €, 12 % hasta 1.500.000 €, 13 % por encima",
        verified=True,
    ),
    # https://atv.gva.es/documents/173852445/177585437/Presentaci%C3%B3n+DG+Tributos+novedades+fiscales/ad720e9a-a565-4862-bb72-c281a3a2d500 (consultada 23/11/2026)
    # Corregido: 10 % -> 9 % para devengos desde el 1/6/2026 (Ley 5/2025, art. 33).
    "comunidad_valenciana": ItpRate(
        9.0,
        "11 % sobre toda la base si el inmueble vale más de 1.000.000 €; 10 % para devengos anteriores al 1/6/2026",
        verified=True,
    ),
    # https://portaltributario.juntaex.es/PortalTributario/c/document_library/get_file?uuid=5941531d-d901-4c1c-838a-a169e494c161&groupId=10136 (DLeg 1/2018, art. 36; consultada 23/11/2026)
    # Añadida la nota: la tarifa progresiva faltaba.
    "extremadura": ItpRate(
        8.0,
        "tarifa progresiva: 8 % hasta 360.000 €, 10 % hasta 600.000 €, 11 % por encima",
        verified=True,
    ),
    # https://www.atriga.gal/documents/20632401/0/BeneficiosFiscales-Transmisiones-es-01-01-2025.pdf/c863f141-b2c0-44c8-a8d0-24674a1dacf2 (art. 14; consultada 23/11/2026)
    # https://www.atriga.gal/documents/20632401/21069643/TABLAS+MK+600E+GALLEGO+DIC+2025+v2.pdf/3f40f879-7f88-490e-921f-efa928f998e3 (claves del modelo 600, dic. 2025)
    # Corregido: 10 % -> 8 %.
    "galicia": ItpRate(8.0, verified=True),
    # https://www.larioja.org/tributos/es/asistencia-tributaria-contribuyente/guias-breves/hacer-compro-vivienda-usada-segunda-mano (consultada 23/11/2026)
    "la_rioja": ItpRate(7.0, verified=True),
    # https://www.comunidad.madrid/atencion-contribuyente/transmisiones-patrimoniales-onerosas (consultada 23/11/2026)
    "madrid": ItpRate(6.0, verified=True),
    # https://agenciatributaria.carm.es/web/guest/-/novedades-en-materia-de-tributos-aprobadas-en-la-ley-de-presupuestos-generales-de-la-comunidad-autonoma-de-la-region-de-murcia-para-el-ano-2025 (consultada 23/11/2026)
    # Corregido: 8 % -> 7,75 % desde el 25/7/2025 (Ley 3/2025).
    "murcia": ItpRate(7.75, verified=True),
    # http://www.navarra.es/home_es/Gobierno+de+Navarra/Organigrama/Los+departamentos/Economia+y+Hacienda/Organigrama/Estructura+Organica/Hacienda/Informacion+Fiscal/Preguntas+mas+frecuentes/Impuesto+sobre+transmisiones+patrimoniales+y+AJD/Transmisiones+Patrimoniales/Otros+bienes/tipos_gravamen.htm (consultada 23/11/2026)
    "navarra": ItpRate(6.0, "régimen foral", verified=True),
    # Álava: https://web.araba.eus/es/hacienda/impuestos/preguntas-frecuentes-impuesto-transmisiones-y-actos-juridicos-documentados (consultada 23/11/2026)
    # Bizkaia: https://www.bizkaia.eus/documents/1135059/1352576/ITP+Tarifa.pdf/c4388ca6-7611-2afd-d3a8-c06f1a0806fd (consultada 23/11/2026)
    # Gipuzkoa: https://www.gipuzkoa.eus/es/web/ogasuna/impuestos/modelo/60t/tipos-impositivos (consultada 23/11/2026)
    # Las tres haciendas forales coinciden: 4 % vivienda, 7 % resto de inmuebles.
    "pais_vasco": ItpRate(
        4.0,
        "régimen foral (Álava, Bizkaia y Gipuzkoa): 4 % en vivienda, 7 % en otros inmuebles; "
        "la vivienda pierde el 4 % si el comprador tiene más de 5 viviendas",
        verified=True,
    ),
}
