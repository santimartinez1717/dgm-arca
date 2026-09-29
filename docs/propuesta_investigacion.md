# Investigación de fondo para la propuesta Umbral (analista de inversión)

Notas de la investigación que hay detrás de [`propuesta.md`](propuesta.md): qué existe ya, en
qué nos diferenciamos, qué fuentes de datos funcionan de verdad y qué descartamos. Fecha de
corte: 29 de septiembre de 2026.

## 0. Cómo llegamos a este enfoque

La primera versión era un agente para el comprador de vivienda habitual: coste real de la
compra y legalidad del alquiler. La descartamos por dos motivos:

- **No necesitaba un agente.** Seguía siempre la misma cadena de pasos (Catastro → cálculo →
  dossier), algo que un script resuelve igual.
- **Uso esporádico.** Una persona compra casa una vez cada quince años, y cuando abre la
  aplicación ya ha decidido qué piso quiere.

El pequeño inversor, en cambio, analiza decenas de operaciones al mes. Filtrar y comparar
candidatos obliga a decidir en bucle qué consultar y qué descartar, y aprovecha todo el trabajo
de reglas fiscales y legales de la primera versión.

## 1. Qué existe ya

| Producto | Qué hace | Qué no hace |
|---|---|---|
| [Luci](https://www.luci.es/) | Agrega anuncios de todos los portales, búsqueda conversacional, precio frente a comparables, rentabilidad estimada para inversores, alertas. Freemium de 0 a 99 €/mes. | Rentabilidad con renta de mercado, sin tope legal ni IRPF. Su pregunta es "¿qué pisos hay?". |
| Subastas con IA ([Subastech](https://www.subastech.com/), [SubastasIA](https://subastasia.com/), [CashStalker](https://www.cashstalker.com/l/inversores), [InversorBOE](https://www.inversorboe.com/)) | Leen los edictos del BOE, detectan cargas y estiman el valor. | Nicho saturado y centrado en el riesgo jurídico de la subasta, no en la rentabilidad bajo la ley de vivienda. |
| [InmoScanner](https://inmoscanner.com/) | Datos demográficos, inmobiliarios y de subastas en un mapa. | Datos, no análisis de una operación concreta. |
| Agentes para inmobiliarias (Propelos, Realy AI) | Atienden a compradores con la cartera de una agencia. | Trabajan para el vendedor. |
| Calculadoras de rentabilidad | Rentabilidad bruta y a veces neta. | Ignoran el tope del art. 17 LAU, el umbral de gran tenedor y las reducciones del art. 23.2 LIRPF. |

**El hueco.** Nadie calcula la rentabilidad **legalmente alcanzable y después de impuestos**
de un piso concreto, ni el efecto de una compra sobre la cartera (el umbral de gran tenedor).
Son reglas publicadas que cambian el resultado varios puntos.

## 2. Qué nos hace distintos (y por qué encaja con la práctica)

1. **Rentabilidad legal, no de mercado.** El tope de la renta aplica el art. 17.6 y 17.7 LAU
   con los datos de la zona.
2. **Rentabilidad después de impuestos.** Amortización, límite de gastos financieros y
   reducciones del 50 % al 90 %.
3. **Razonamiento de cartera.** El umbral de gran tenedor depende de los pisos que ya tienes.
4. **Problemas inversos.** "¿Hasta qué precio puedo pagar?" es razonamiento de verdad, no una
   fórmula directa.
5. **Un solo motor de reglas para tres fases.** Genera el dataset de la fase 1, es la
   calculadora de la fase 2 y verifica las tareas de la fase 4.
6. **Dependencia del tiempo como característica.** 2026 ha traído cambios reales:
   - el ITP de la Comunidad Valenciana (del 10 % al 9 % el 1 de junio);
   - el RDL 16/2025, no convalidado, que devolvió los coeficientes de plusvalía del
     RDL 8/2023;
   - la STC 13/2026, que avala el valor de referencia como base imponible.

## 3. Fuentes de datos comprobadas

Comprobadas con peticiones reales el 28/09/2026.

| Fuente | Acceso | Qué devuelve | Estado |
|---|---|---|---|
| Catastro, servicios libres (`Consulta_DNPRC`) | REST/JSON, sin clave | Uso, superficie construida, año, tipo de finca, desglose de construcciones | Funciona. Ejemplo: RC `9872023VH5797S0001WX` → residencial, 308 m², 1980 |
| CartoCiudad (IGN) | REST, sin clave | Geocodificación de dirección con coordenadas **y referencia catastral** | Funciona. Encadena con el Catastro |
| Banco de España (`bierest`) | REST/JSON, sin clave | Euríbor 12 meses, serie `D_1NBAF472` | Funciona: 2,954 % (agosto 2026) |
| INE (API JSON Tempus3) | REST/JSON, sin clave | IRAV, IPV, IPC | Funciona |
| BOE, datos abiertos | REST/JSON y XML, sin clave | Legislación consolidada por identificador (p. ej. `BOE-A-2023-12203`, Ley 12/2023) | Funciona. Es la ingesta del corpus |
| SERPAVI (MIVAU) | Capas *shapefile* descargables y servicio ArcGIS | Rango de €/m² por sección censal | Descarga en bloque; se indexa en local |
| Subastas del BOE | Sumario diario por la API de datos abiertos; detalle del lote en el portal, sin API | Tasación, cargas, depósito | Sumario comprobado; el detalle hay que extraerlo de la página del lote |
| SNCZI (MITECO) | WMS OGC | Zonas inundables por periodo de retorno | Documentado; por probar `GetFeatureInfo` |
| Open Data de Registradores | Web, registro gratuito | Precio por m², compraventas e hipotecas por comunidad | Por comprobar si hay API |
| Portal Estadístico del Notariado | Web, registro gratuito | Precio medio de compraventa por código postal | Sin API documentada; descarga de informes |
| Idealista | OAuth2 con clave y secreto, previa solicitud | Búsqueda de anuncios (`/3.5/es/search`) | **Restringida** a proyectos aprobados; hay que pedirla |
| Valor de referencia del Catastro | Sede electrónica con Cl@ve o certificado | Valor de referencia de un inmueble | **No automatizable**; el usuario lo aporta |

**Sobre Idealista.** La API oficial existe pero se concede caso a caso tras describir el
proyecto. Hay wrappers de terceros en marketplaces que en realidad hacen *scraping*; no los
usaremos (condiciones de uso del portal y protección anti-bots). Pediremos acceso académico en
la primera semana; si llega, entra como herramienta opcional con caché.

## 4. Reglas concretas comprobadas para el generador

- **Arancel notarial** (RD 1426/1989, anexo I, n.º 2, consultado en el BOE): hasta 6.010,12 €,
  90,15 €; de ahí a 30.050,61 €, 4,5 ‰; hasta 60.101,21 €, 1,5 ‰; hasta 150.253,03 €, 1 ‰;
  hasta 601.012,10 €, 0,5 ‰; hasta 6.010.121,04 €, 0,3 ‰; por encima, libre. Rebaja general
  del 5 %. Varias webs de calculadoras resumen mal la escala, lo que confirma que vale la pena.
- **ITP 2026**: tipos generales entre el 6 % (Madrid) y el 13 % (Baleares); Andalucía 7 % único;
  Cataluña 10 %; C. Valenciana 9 % desde el 1/6/2026 (11 % por encima de 1 M€); tipos reducidos
  habituales del 3,5 % al 5 % para jóvenes, familias numerosas y discapacidad, cada uno con sus
  requisitos. Las tablas se transcribirán desde los textos autonómicos del BOE, no desde
  agregadores.
- **Base imponible**: el valor de referencia si es mayor que el precio declarado (Ley 11/2021).
- **Hipoteca**: la Ley 5/2019 (art. 14.1.e) pone a cargo del prestamista notaría, registro y
  gestoría; la tasación la paga el prestatario. El AJD de la hipoteca lo paga el prestamista
  desde el RDL 17/2018.
- **Alquiler**: IRAV publicado por el INE desde enero de 2025 como mínimo entre IPC, IPC
  subyacente y una tasa ajustada; tope SERPAVI para grandes tenedores y para viviendas no
  alquiladas en los últimos cinco años en zona tensionada; fianza de una mensualidad y garantía
  adicional de hasta dos; honorarios de gestión a cargo del arrendador.
- **Plusvalía municipal** (familia fuera de distribución): se paga el menor entre método
  objetivo (valor catastral del suelo × coeficiente por años × tipo municipal) y real; exenta si
  hay pérdida. Coeficientes del RDL 8/2023.

- **Topes de renta** (LAU art. 17.6 y 17.7, texto consolidado del BOE):
  - con contrato en los últimos cinco años, el tope es la última renta actualizada (+10 % con
    obras de mejora o contrato de diez años o más);
  - si el arrendador es gran tenedor, además el índice de referencia, porque el 17.7 aplica
    "sin perjuicio" del 17.6 y los dos topes se acumulan;
  - sin contrato previo, el índice solo si la resolución de la zona lo prevé.
- **Gran tenedor** (Ley 12/2023, art. 3.k): más de diez viviendas o más de 1.500 m²
  residenciales; o cinco o más en una zona tensionada cuya declaración rebaje el umbral.
- **IRPF del alquiler** (manual práctico de la AEAT):
  - reducciones del art. 23.2 en orden 90 → 70 → 60 → 50 %, solo sobre rendimiento neto
    positivo;
  - amortización del 3 % sobre el mayor entre coste de adquisición y valor catastral, sin el
    suelo;
  - intereses más reparaciones, como mucho los ingresos íntegros (el exceso se arrastra
    cuatro años).

## 5. Alternativas que consideramos y descartamos

- **Asistente del comprador de vivienda habitual** (nuestra primera versión): el motivo está
  en la sección 0.
- **Tasador automático** (predecir el precio de un piso): no hay verificador exacto. El precio
  de cierre no es público piso a piso y el de anuncio no es la verdad.
- **Agregador tipo Luci:** depende de portales sin API abierta, y la fase 1 no tendría tarea
  verificable.
- **Subastas como tema principal:** nicho ya ocupado por al menos cuatro productos. Las usamos
  como una fuente más de candidatos.
- **"¿Es buen momento para comprar?":** es una predicción del mercado, sin verificador y con
  riesgo de parecer asesoramiento. Es nuestra tarea "imposible" de la fase 4.

## Fuentes

- [LAU consolidada (BOE)](https://www.boe.es/buscar/act.php?id=BOE-A-1994-26003) ·
  [Cuadro de reducciones del art. 23.2 LIRPF (AEAT)](https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2024/c04-rendimientos-capital-inmobiliario/reducciones-rendimiento-neto/arrendamiento-inmuebles-destinados-vivienda/cuadro-reducciones-arrendamiento.html) ·
  [Amortización (AEAT)](https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c04-rendimientos-capital-inmobiliario/gastos-deducibles/cantidades-destinadas-amortizacion.html)
- [Luci](https://www.luci.es/)
- [Idealista, solicitud de acceso a la API](https://developers.idealista.com/access-request) ·
  [cliente Python de ejemplo](https://github.com/yagueto/idealista-api)
- [Servicios web libres del Catastro (PDF)](https://www.catastro.hacienda.gob.es/ws/Webservices_Libres.pdf)
- [API del Banco de España](https://www.bde.es/webbe/en/estadisticas/recursos/api-estadisticas-bde.html)
- [API JSON del INE](https://www.ine.es/dyngs/DAB/index.htm?cid=1099) ·
  [IRAV, últimos datos](https://www.ine.es/uc/oC7D0Ncd)
- [SERPAVI (MIVAU)](https://www.mivau.gob.es/vivienda/alquila-bien-es-tu-derecho/serpavi) ·
  [Incorporación de Álava y Bizkaia, 2026](https://www.mivau.gob.es/el-ministerio/sala-de-prensa/noticias/lun-30032026-0922)
- [SNCZI, acceso WMS](https://www.miteco.gob.es/en/agua/temas/gestion-de-los-riesgos-de-inundacion/snczi/acceso-servicio-wms.html)
- [RD 1426/1989, arancel de los notarios (BOE)](https://www.boe.es/buscar/act.php?id=BOE-A-1989-28111)
- [STC 13/2026 sobre el valor de referencia](https://delajusticia.com/2026/02/13/gozo-en-el-pozo-el-tc-avala-el-valor-de-referencia-de-inmuebles-como-base-imponible/)
- [Plusvalía 2026 y la no convalidación del RDL 16/2025 (OCU)](https://www.ocu.org/fincas-y-casas/compraventa/fiscalidad/analisis/2026/01/cambios-coeficientes-plusvalia-2026)
- [ITP por comunidades 2026 (Tribeus)](https://tribeus.es/legislacion/impuesto-de-transmisiones-patrimoniales-en-espana-y-sus-ccaa/) ·
  [Calculadora ITP (GuíaFiscal)](https://guiafiscal.es/calculadoras/itp/)
- [Proptech españolas 2026 (El Referente)](https://elreferente.es/startups/15-proptech-espanolas-a-seguir-en-2026/) ·
  [Propelos](https://www.cantabriaeconomica.com/patrocinado/informacion-al-dia/propelos-lanza-el-primer-agente-de-busqueda-inmobiliaria-con-inteligencia-artificial-en-espana/)
