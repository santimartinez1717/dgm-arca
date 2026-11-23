# Fuentes de datos y APIs para un agente analista de inversión inmobiliaria para alquilar en España (estado a 17-11-2026)

Leyenda: **[VERIFICADO EN VIVO]** = probado con `curl` desde la DGX el 17-11-2026, con la respuesta resumida. **[DOCUMENTADO]** = solo lo dice la documentación o una fuente secundaria; no se ha probado.

## 1. Catastro (DG del Catastro): servicios libres y servicios que exigen identificación

### Takeaway
Los servicios web libres del Catastro devuelven por referencia catastral (RC), dirección o coordenadas los datos físicos del inmueble: superficie construida, uso, año, coeficiente de participación y desglose de construcciones. Funcionan sin clave y en JSON. **No devuelven el valor catastral ni el valor de referencia.** El valor de referencia por RC solo se obtiene en la Sede con identificación (certificado, Cl@ve o datos del DNI); no he encontrado ningún endpoint anónimo que lo dé.

### Cited Findings
- **[VERIFICADO EN VIVO] Consulta_DNPRC (JSON, sin autenticación).** `GET https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Consulta_DNPRC?RefCat=9872023VH5797S0001WX` → HTTP 200, `application/json`. Devuelve `ldt` (dirección), `debi.luso` = "Residencial", `debi.sfc` = "308" (m² construidos), `debi.cpt` (coeficiente de participación), `debi.ant` = "1980" (año), la parcela (`dff.ss` = 397 m² de suelo) y `lcons[]` con cada unidad constructiva (VIVIENDA 109 m², ALMACEN 187 m²…), su planta y puerta y su tipología. No trae ningún campo de valor. Con una RC de 14 caracteres (solo la parcela) devuelve la lista de inmuebles de la parcela. — documentación oficial de los servicios libres: [Catastro – WCFservices](https://www.catastro.hacienda.gob.es/ws/WCFservices_Consulta.pdf)
- **[VERIFICADO EN VIVO] ObtenerProvincias (JSON).** `…/COVCCallejero.svc/json/ObtenerProvincias` → 200 y 48 provincias. Hay 48 y no 50 porque País Vasco y Navarra tienen catastro foral y quedan fuera del servicio: para esas provincias hacen falta las fuentes forales. — [Catastro WCF](https://www.catastro.hacienda.gob.es/ws/WCFservices_Consulta.pdf)
- **[VERIFICADO EN VIVO] Coordenadas → RC (SOAP/ASMX por GET).** `https://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCCoordenadas.asmx/Consulta_RCCOOR?SRS=EPSG:4326&Coordenada_X=-3.7038&Coordenada_Y=40.4168` → 200 en XML, pero con el error 16 "PARA ESAS COORDENADAS NO HAY REFERENCIA DISPONIBLE" para un punto en plena Puerta del Sol (probablemente cayó en la vía pública). El servicio responde; hay que pasarle un punto que caiga dentro de una parcela o usar `Consulta_RCCOOR_Distancia`.
- **[VERIFICADO EN VIVO] INSPIRE WFS de edificios.** `https://ovc.catastro.meh.es/INSPIRE/wfsBU.aspx?service=WFS&version=2.0.0&request=GetFeature&STOREDQUERIE_ID=GetBuildingByParcel&REFCAT=9872023VH5797S&srsname=EPSG::25830` → 200 con GML de los edificios (huella, número de plantas, uso, año). Existen además `wfsCP.aspx` (parcelas) y `wfsAD.aspx` (direcciones).
- **[VERIFICADO EN VIVO] WMS de cartografía catastral.** `https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx?SERVICE=WMS&REQUEST=GetCapabilities` → 200 (WMS 1.1.1).
- **[DOCUMENTADO] Consulta pública con más datos.** El servicio WCF `https://serwebr.sedecatastro.gob.es/ServiciosWCF/OVCWcfConsulta/OVCConsulta.svc` está documentado como consulta pública de datos catastrales, sin ninguna operación de valor. — [Catastro WCF](https://www.catastro.hacienda.gob.es/ws/WCFservices_Consulta.pdf)
- **[DOCUMENTADO] Valor de referencia.** Se consulta en la Sede Electrónica con la RC y la fecha de la operación, identificándose con certificado electrónico, Cl@ve o los datos del DNI. La consulta anónima por RC da ubicación, superficie, uso y año, pero ningún valor. — [Xataka](https://www.xataka.com/basics/como-saber-valor-casa-piso-valor-referencia-catastro), [Genbeta](https://www.genbeta.com/paso-a-paso/esta-web-te-dice-cuanto-vale-tu-casa-que-quieres-comprar-datos-catastro-consultamos-valor-referencia-2)
- **[DOCUMENTADO] Valor de referencia para administraciones.** Existe un "Servicio de Consulta del Valor de Referencia de un inmueble" (certificado y motivación del cálculo), pero solo para administraciones, a través de la plataforma de intermediación SCSP; no es un endpoint abierto. — [Junta de Andalucía, manual SCSP Catastro](https://desarrollo.juntadeandalucia.es/sites/default/files/2025-05/WAN013T_Manual_Programador_Servicios_SCSP_CATASTRO_0110.pdf)
- **[VERIFICADO EN VIVO, solo que la página carga] Descarga masiva.** `https://www.sedecatastro.gob.es/Accesos/SECAccDescargaDatos.aspx` responde 200. No he verificado en vivo las condiciones de cada descarga.

### Inferences
- El agente puede obtener gratis y sin límite contractual conocido los m² construidos "oficiales", el año, el uso y el número de unidades de una finca. Es la base para contrastar los m² y el año de un anuncio.
- El valor de referencia no se puede automatizar sin la identidad del usuario. Alternativas: (a) pedirle al usuario el PDF o certificado; (b) aproximarlo con los ficheros públicos de módulos de valor de referencia por ámbito; esto último está sin verificar.
- La RC conecta casi todas las fuentes: CartoCiudad la devuelve, los certificados energéticos de Cataluña la incluyen y SERPAVI se consulta por ella.

### Gaps
- No he verificado límites de uso de los servicios libres. No he encontrado una cifra oficial de cuota; conviene limitar la frecuencia de peticiones.
- No he confirmado que el valor de referencia por ámbito o los módulos se publiquen como fichero descargable (MBR/ámbitos homogéneos).
- Las condiciones de la descarga masiva alfanumérica (si exige certificado) siguen sin verificar.

## 2. CartoCiudad (IGN/CNIG): geocodificador

### Takeaway
Es un geocodificador libre y sin clave que, además de las coordenadas, devuelve el código INE del municipio, el código postal y **la referencia catastral de la parcela del portal**. Es la pasarela natural entre la dirección de un anuncio, el Catastro, la sección censal y SERPAVI.

### Cited Findings
- **[VERIFICADO EN VIVO] Geocodificación directa.** `GET https://www.cartociudad.es/geocoder/api/geocoder/findJsonp?q=Calle%20Alcala%2050%20Madrid` → 200 en JSONP: `muniCode` "28079", `postalCode` "28014", `lat` 40.4194, `lng` -3.6916, `type` "portal", `portalNumber` 50, `refCatastral` "1446401VK4714E".
- **[VERIFICADO EN VIVO] Geocodificación inversa.** `GET https://www.cartociudad.es/geocoder/api/geocoder/reverseGeocode?lon=-3.7038&lat=40.4168` → JSON: PLAZA PUERTA DEL SOL 7, CP 28012, `refCatastral` "0444101VK4704C".
- El visor de SERPAVI usa este mismo geocodificador: en su JavaScript aparece `https://www.cartociudad.es/geocoder/api/geocoder` (comprobado en vivo descargando `https://serpavi.mivau.gob.es/_root_*.min.js`).

### Inferences
- La sección censal no viene en la respuesta. Para obtenerla, se cruza el punto con el shapefile de secciones del INE, que el MIVAU redistribuye como `SECC_CE_20210101_INE_WM.zip` (ver §3).

### Gaps
- No he encontrado una cuota publicada para CartoCiudad.

## 3. SERPAVI (MIVAU): Sistema Estatal de Referencia del Precio del Alquiler de Vivienda

### Takeaway
Hay una **descarga oficial en Excel con todos los niveles territoriales, hasta la sección censal, para 2011-2024**, publicada en marzo de 2026, más los shapefiles de secciones y distritos. Es el dato con el que se calcula el tope legal en zonas tensionadas. El visor (`serpavi.mivau.gob.es`) usa una API interna sin documentar; no hay una API pública ni un WMS documentados.

### Cited Findings
- **[VERIFICADO EN VIVO] Excel con la base de datos 2011-2024** (71 MB): `https://cdn.mivau.gob.es/portal-web-mivau/vivienda/serpavi/2026-03_09_bd_SERPAVI_2011-2024%20-%20DEFINITIVO%20WEB_v2.xlsx`. Hojas: `Metadatos`, `CCAA`, `Provincias`, `Municipios`, `Distritos`, `Secciones censales`. Las claves son las del Censo 2021 del INE (`CUSEC`, `CUMUN`, `CUDIS`…). Variables por año (sufijo `_AA`), separadas en vivienda colectiva (`VC`) y unifamiliar (`VU`):
  - `ALQM2mes_LV_M/25/75`: mediana, p25 y p75 del alquiler en €/m²/mes.
  - `ALQTBID12_M/25/75`: alquiler mensual en €.
  - `SLVM2_*`: superficie.
  - `BI_ALVHEPCO_*`: número de viviendas (testigos).
  
  Encabezado de la hoja de metadatos: "Sistema Estatal Índices Alquiler de Vivienda (Explotación estadística de fuentes tributarias)". Enlace a la descarga en la [página SERPAVI del MIVAU](https://www.mivau.gob.es/vivienda/alquila-bien-es-tu-derecho/serpavi).
- **[VERIFICADO EN VIVO] Otros ficheros enlazados desde la misma página:** la metodología `2026-03-18_Metodologia_SERPAVI.pdf`; los shapefiles `SECC_CE_20210101_INE_WM.zip` (secciones censales) y `DISTRITOS_20111101_01_R_INE_WM.zip`; y `EGRN_Municipios/Provincias/CCAA_WM_20201021.zip`. Todos están en `https://cdn.mivau.gob.es/portal-web-mivau/vivienda/serpavi/`. — [MIVAU SERPAVI](https://www.mivau.gob.es/vivienda/alquila-bien-es-tu-derecho/serpavi)
- **[VERIFICADO EN VIVO] Visor.** `https://serpavi.mivau.gob.es/` es una SPA; en su JS aparece la base `https://serpavi.mivau.gob.es/api`, que da 404 en la raíz. No tiene documentación pública y usarla sería ingeniería inversa.
- La WebFetch normal recibe un 403 en mivau.gob.es; con `curl` y un User-Agent de navegador responde 200.
- SERPAVI se consulta por dirección o RC y es gratuito. — [La Moncloa](https://www.lamoncloa.gob.es/serviciosdeprensa/notasprensa/vivienda-agenda-urbana/paginas/2024/indice-referencia-precio-alquiler-vivienda-sepavi.aspx)
- SERPAVI usa medianas y la AEAT medias, a partir de la misma base de datos tributaria. — [AEAT FAQ](https://sede.agenciatributaria.gob.es/Sede/eu_es/estadisticas/estadisticas-impuesto/estadistica-viviendas-declaradas-irpf/metodologia/preguntas-frecuentes.html)
- Hay críticas metodológicas: el Banco de España advierte de que no es un índice de precios de mercado, y Asval y ACI piden más transparencia. — [brainsre.news](https://brainsre.news/asval-aci-alertan-indice-precios-alquiler-serpavi/)
- Hay una petición ciudadana en datos.gob.es pidiendo SERPAVI en API/CSV/JSON. Indica que no existe API oficial. — [datos.gob.es solicitud](https://datos.gob.es/es/solicitud-de-datos/ser-de-precios-de-alquiler-eum2-codigo-ine-periodicidad-historico-diccionario)
- La metodología y los datos se actualizaron por resolución en el BOE (abril de 2025) — [BOE-A-2025-7279](https://www.boe.es/boe/dias/2025/04/10/pdfs/BOE-A-2025-7279.pdf). Hay otra resolución de 2026 que menciona el ámbito por secciones censales — [BOE-A-2026-8691](https://boe.es/boe/dias/2026/04/20/pdfs/BOE-A-2026-8691.pdf).

### Inferences
- Último año con datos en el fichero: **2024**. Los datos llegan con unos dos años de retraso porque salen de las declaraciones del IRPF.
- El agente puede cargar el Excel una vez, indexarlo por `CUSEC` y responder sin red. Así tiene la mediana y la banda p25-p75 en €/m² de su sección censal para cualquier vivienda geocodificada.
- El tope legal concreto en zona tensionada (art. 17.7 de la Ley 12/2023, para grandes tenedores o vivienda nueva en alquiler) se calcula con el índice y sus rangos según las características de la vivienda. La aproximación por sección censal no es el cálculo oficial, que necesita el visor con la RC.

### Gaps
- No he comprobado en vivo los endpoints de `serpavi.mivau.gob.es/api`. No hay WMS documentado.
- La licencia de reutilización del Excel no está explícita en la página; según la solicitud ciudadana, la reutilización está limitada.

## 4. Zonas de mercado residencial tensionado (ZMRT)

### Takeaway
No hay un dataset estructurado oficial. La fuente oficial es una página del MIVAU con enlaces a las **resoluciones trimestrales del BOE** que recogen las zonas declaradas (art. 18 de la Ley 12/2023) y a las memorias en PDF de cada declaración. Hay que mantener una tabla propia a mano o parsear el BOE.

### Cited Findings
- **[VERIFICADO EN VIVO]** La página `https://www.mivau.gob.es/vivienda/alquila-bien-es-tu-derecho/serpavi/consultar-zonas-de-mercado-residencial-tensionado` enlaza las resoluciones BOE-A-2024-5214, BOE-A-2024-20576, BOE-A-2025-1721, BOE-A-2025-8636, BOE-A-2025-15728, BOE-A-2025-21901, BOE-A-2026-2448, BOE-A-2026-9175, BOE-A-2026-16532 y **BOE-A-2026-23088** (la más reciente enlazada). También enlaza las resoluciones de A Coruña y Santiago (abril de 2026, PDF).
- La resolución de julio de 2026 (BOE-A-2026-16532) recoge las declaraciones, incluidas las primeras de Asturias (desde el 30-07-2026, 12 ámbitos en 5 concejos). — [BOE-A-2026-16532](https://boe.es/boe/dias/2026/07/29/pdfs/BOE-A-2026-16532.pdf); [taxdown](https://taxdown.es/propietario/zonas-tensionadas)
- Cataluña prorrogó la declaración y amplió la lista hasta **302 municipios** (julio de 2026). — [Última Hora](https://www.ultimahora.es/noticias/comunidades/2026/07/28/2678719/catalunya-prorroga-ano-declaracion-zona-vivienda-tensionada-llega-302-municipios.html)
- País Vasco: Hernani, Lezo y Tolosa están declarados desde el 03-02-2026. — [Última Hora](https://www.ultimahora.es/noticias/comunidades/2026/01/29/2559297/euskadi-consolida-despliegue-zonas-tensionadas-gipuzkoa-declaracion-hernani-tolosa-lezo.html)
- Un portal secundario contaba 317 municipios con zona tensionada a 30-09-2026; la cifra no cuadra exactamente con otras fuentes. — [taxdown](https://taxdown.es/propietario/zonas-tensionadas)

### Inferences
- Las declaraciones pueden afectar solo a parte de un municipio (por ejemplo, ámbitos o barrios en Asturias). Una tabla a nivel municipal no basta: a veces hace falta la geometría o la lista de secciones de la memoria.
- La API del BOE (§7) permite recuperar el texto de cada resolución por su identificador y mantener la tabla con un proceso semiautomático.

### Gaps
- No he encontrado un CSV, GeoJSON o WMS oficial de las ZMRT.
- La consulta del texto consolidado de `BOE-A-2026-23088` en la API de legislación consolidada dio 404. Es lógico: es una resolución del diario, no una norma consolidada; para el diario hay que usar el sumario y el XML del documento.

## 5. INE: API Tempus (JSON) y operaciones relevantes

### Takeaway
La API Tempus es REST/JSON, sin clave, y funciona. Cubre el IPV, el IRAV (actualización de rentas), el IPVA (índice de precios de vivienda en alquiler, ya publicado como operación), el Atlas de Distribución de Renta por sección censal (ADRH), las viviendas turísticas (VTE) y el padrón.

### Cited Findings
- **[VERIFICADO EN VIVO]** `https://servicios.ine.es/wstempus/js/ES/OPERACIONES_DISPONIBLES` → 200 en JSON. Operaciones encontradas (Id, código):
  - 15 IPV (Índice de Precios de la Vivienda)
  - 432 IPVA (Índice de Precios de Vivienda en Alquiler)
  - 481 IRAV (Índice de Referencia de Arrendamientos de Vivienda)
  - 353 ADRH (Atlas de distribución de renta de los hogares)
  - 410 VTE (Viviendas turísticas en España)
  - 22 DPOP (Cifras oficiales de población, padrón)
  - 189 NOM (Nomenclátor)
  - 8 CENSOPV (Censos)
- **[VERIFICADO EN VIVO] IRAV.** `https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IRAV1?nult=1` → "Total Nacional. Índice general. Variación anual": **2,57 en el periodo 10 de 2026 (octubre de 2026)**. El IRAV es el índice que sustituye al IPC para actualizar la renta de los contratos firmados desde el 26-05-2023.
- **[VERIFICADO EN VIVO] IPV.** `DATOS_SERIE/IPV769?nult=1` (base 2015, nacional, general, índice) devolvió como último dato **2025, periodo 22 = 186,75**. Que el último dato sea de 2025 en noviembre de 2026 sugiere que la serie IPV769 está congelada, quizá por un cambio de base, o que el código de periodo no es el que yo creo. **Antes de usarla, comprobar en INEbase qué serie es la vigente.** `SERIES_OPERACION/IPV` lista aún series "Base 2007".
- **[VERIFICADO EN VIVO] IPVA.** `SERIES_OPERACION/IPVA?page=1` devuelve series del tipo "Castilla-La Mancha. (120-150]. Índice. Total viviendas", con periodicidad anual (FK_Periodicidad 12) y desglose por CCAA y tramos de superficie.
- **[VERIFICADO EN VIVO] ADRH.** `SERIES_OPERACION/ADRH?page=1` devuelve series como "Garcibuey sección 01001. Dato base. Renta neta media por hogar". Hay una serie Tempus por sección censal.
- **[VERIFICADO EN VIVO] VTE.** `SERIES_OPERACION/VTE` da el número de viviendas turísticas por municipio.
- La edición del ADRH con datos de 2024 se publicó el 19-10-2026: renta neta media por persona de 15.948 €, un 6,1 % más. La de 2023 se publicó el 21-10-2025. — [INE nota ADRH2024](https://ine.es/dyngs/Prensa/en/ADRH2024.htm), [INE ADRH2023](https://ine.es/dyngs/Prensa/ADRH2023.htm)
- Otros patrones de URL: `DATOS_TABLA/{id}?nult=N`, `DATOS_SERIE/{cod}?nult=N` o `?date=AAAAMMDD:AAAAMMDD`, `SERIES_OPERACION/{op}?page=N` (se pagina de 500 en 500).

### Inferences
- Para el ADRH por sección es más práctico descargar el fichero completo (pc-axis/CSV) de INEbase que llamar a una serie por sección; hay unas 36.000 secciones.
- El IRAV mensual es el dato que el agente necesita para proyectar la renta de contratos nuevos. El IPVA da la evolución de las rentas por CCAA o municipio grande.

### Gaps
- No he identificado el código de la serie IPV vigente en 2026 ni los códigos de tabla del IPVA municipal.
- El INE no publica límites de uso de Tempus.

## 6. Banco de España: API de estadísticas (BIEST)

### Takeaway
La API REST/JSON funciona sin clave ni cabeceras especiales; basta con un `rango` válido. El Euríbor 12M de octubre de 2026 está disponible.

### Cited Findings
- **[VERIFICADO EN VIVO] Último valor.** `GET https://app.bde.es/bierest/resources/srdatosapp/favoritas?idioma=es&series=D_1NBAF472` → `{"serie":"D_1NBAF472","descripcionCorta":"Euribor a un año","codFrecuencia":"M","fechaValor":"2026-10-01T08:15:00Z","valor":3.239}`.
- **[VERIFICADO EN VIVO] Histórico.** `GET https://app.bde.es/bierest/resources/srdatosapp/listaSeries?idioma=es&series=D_1NBAF472&rango=30M` → 200. También aceptan `60M` y `MAX`; `12M` y `36M` dan **412 "El rango … no es correcto"** para una serie mensual. Los rangos válidos dependen de la frecuencia de la serie.
- **[VERIFICADO EN VIVO]** La respuesta viene comprimida (gzip): usar `curl --compressed`. Si se pide un código de serie inexistente, el error es 412 "La serie … no existe".
- Documentación oficial: los parámetros son `idioma` (`es`/`en`), `series` (separadas por comas) y `rango`; sin `rango` se devuelve el mínimo de la frecuencia (30M para las mensuales); un `%` en un código se escribe `%25`. Los códigos de serie salen de BIEST o de los CSV de cada tabla. — [BdE API](https://www.bde.es/webbe/es/estadisticas/recursos/api-estadisticas-bde.html)

### Inferences
- Los tipos hipotecarios medios (TAE de vivienda de entidades de crédito, tabla 19.x del Boletín Estadístico) necesitan su código BIEST. No lo he localizado; el código que probé (`BE_19_6.1`) no existe.

### Gaps
- Falta el código de la serie del tipo medio de préstamos hipotecarios de vivienda a más de 3 años.

## 7. BOE: API de datos abiertos y Portal de Subastas

### Takeaway
La API de datos abiertos del BOE funciona sin clave, pero **exige la cabecera `Accept: application/json` o `Accept: application/xml`**; sin ella devuelve 400. El Portal de Subastas (subastas.boe.es) **no tiene API**: su `robots.txt` lo prohíbe todo (`Disallow: /`) y las páginas llevan `noindex, nofollow`. Para subastas judiciales hay un CSV semanal del Ministerio de Justicia, con datos agregados por subasta y sin ubicación.

### Cited Findings
- **[VERIFICADO EN VIVO] Sumario.** `curl -H "Accept: application/json" https://www.boe.es/datosabiertos/api/boe/sumario/20261116` → 200 (BOE-S-2026-285, unos 380 KB), con las secciones I a V.C. Sin la cabecera: 400 "No soportado ningún mime type de la cabecera Accept".
- **[VERIFICADO EN VIVO] Legislación consolidada.** `curl -H "Accept: application/json" "https://www.boe.es/datosabiertos/api/legislacion-consolidada?limit=2"` → 200, con metadatos de normas (identificador, ámbito, departamento, rango, fecha_actualizacion 20261117). Sirve para seguir la LAU, la Ley 12/2023 y las normas autonómicas de ITP.
- **[VERIFICADO EN VIVO] Portal de Subastas.** `https://subastas.boe.es/subastas_ava.php` → 200 en HTML; `robots.txt` → `User-agent: * / Disallow: /`; `rss.php` → 404. Una búsqueda por GET con parámetros no devolvió identificadores SUB-… en el HTML (puede necesitar sesión o POST).
- El portal único de subastas judiciales y administrativas (Ley 19/2015) funciona desde octubre de 2015 y también aloja las subastas de la AEAT. — [datos.gob.es / fuentes en la búsqueda](https://datos.gob.es/es/catalogo/e05228601-subastas-judiciales), [AEAT FAQ](https://sede.agenciatributaria.gob.es/Sede/deudas-apremios-embargos-subastas/subastas/preguntas-frecuentes/pujas.html)
- Solo hay servicios de scraping de terceros (actores de Apify), no una API oficial. — [Apify BOE auctions](https://apify.com/jdepablos/spain-boe-auctions)
- **[VERIFICADO EN VIVO] CSV de subastas judiciales (Justicia).** La entrada `e05228601-subastas-judiciales` de datos.gob.es (actualización semanal, modificada el 10-08-2026) apunta a `https://catalogodatos.justicia.es/csv/Subastas_Judiciales.csv`. Columnas: `CantidadReclamada; TipoSubasta; Procedimiento; principalReclamado; importeSubasta; importeTasacion; Estado; Fecha_Estado; Fecha_Publicada; Inmuebles; Muebles; Vehiculos; Acreedores; Representantes`. **No incluye ubicación ni RC del bien**: sirve para estadística (por ejemplo, la relación entre el valor de subasta y la deuda), no para localizar oportunidades. — [datos.gob.es](https://datos.gob.es/es/catalogo/e05228601-subastas-judiciales)

### Inferences
- Para un agente legal y de buena fe, las subastas se pueden tratar como **enlace que el usuario consulta** o como entrada manual (pega el identificador SUB-… o la RC). Automatizar el scraping va contra el `robots.txt`.
- Las subastas que se publican como anuncio en el BOE (sección V.B, otros anuncios oficiales: notariales, de la AEAT o de la Seguridad Social en algunos casos) sí se pueden filtrar con la API del sumario. No he verificado que lleguen allí.

### Gaps
- Subastas de la Seguridad Social: no he confirmado si siguen en su propia sede o ya están en el portal del BOE.
- No he encontrado condiciones de reutilización específicas de subastas.boe.es.

## 8. Precios de transacción: Notariado, Registradores, MIVAU y AEAT

### Takeaway
Los precios reales de compraventa existen a nivel de código postal (Notariado) y de municipio o provincia (Registradores, MIVAU), pero **ninguno ofrece una API**. Notariado tiene un mapa interactivo; Registradores publica PDF trimestrales y un dataset anual en datos.gob.es; los microdatos registrales (PROP) solo están disponibles para investigadores a través de BELab, en el Banco de España.

### Cited Findings
- **Portal del Notariado** (`penotariado.com/inmobiliario`), lanzado el 23-10-2025 y gratuito. Da el precio medio por m², la superficie media, el importe medio y el número de compraventas por CCAA, provincia, municipio y **código postal**, o en un área dibujada de hasta 5 km², con filtros por tipo de finca y construcción. Fuente: el Índice Único Informatizado Notarial, con datos de 2007 a 2025. — [Vozpópuli](https://www.vozpopuli.com/economia/el-portal-estadistico-del-notariado-supera-el-medio-millon-de-usuarios-en-su-primer-ano.html), [Genbeta](https://www.genbeta.com/web/este-mapa-notarios-muestra-gratis-precio-real-viviendas-tu-codigo-postal-cualquier-parte-espana/amp), [Spanish Property Insight](https://www.spanishpropertyinsight.com/2025/10/27/notaries-launch-new-portal-giving-deeper-insight-into-spains-property-market/). **[VERIFICADO EN VIVO]** la página responde 200 (aplicación Next.js); no he buscado su API interna.
- **Registradores.** Estadística Registral Inmobiliaria trimestral; la última localizada es la del 2T 2026 (publicación nº 89, agosto de 2026), en PDF. También está el IRAI 1T 2026. — [ERI 2T 2026](https://www.registradores.org/documents/d/guest/eri_2t_2026), [IRAI 1T 2026](https://www.registradores.org/documents/d/guest/irai_2026_1t). **[VERIFICADO EN VIVO]** El Portal Estadístico Registral responde 200.
- datos.gob.es tiene el conjunto "Estadística Registral Inmobiliaria 2025" (trimestral, transmisiones e hipotecas). — [datos.gob.es](https://datos.gob.es/es/catalogo/a16003011-estadistica-registral-inmobiliaria-2025)
- Los microdatos de la Estadística Registral (PROP, 2013-2025, extracción de abril de 2026) están en BELab, con acceso restringido a investigadores. — [BdE BELab](https://www.bde.es/wbe/es/punto-informacion/contenidos/servicios/belab/contenido/microdatos-disponibles/microdatos-de-la-estadistica-registral-inmobiliaria-prop.html)
- Euskadi publica la Estadística de Compraventa de Inmuebles (ECVI) en tablas. — [Eustat/Euskadi ECVI](https://www.euskadi.eus/estadistica/tablas-estadisticas-estadistica-de-compraventa-de-inmuebles-ecvi/y22-bilaar/es/)

### Inferences
- Para un TFG o práctica, el Notariado por código postal es la mejor referencia de "precio real" frente al precio de anuncio, aunque obtenerlo exige consulta manual o ingeniería inversa del portal, cuyos términos habría que revisar.
- Como BELab es la única vía a microdatos de transacciones, un investigador universitario podría solicitar acceso.

### Gaps
- No he encontrado la página actual del valor tasado del MIVAU (la URL que probé no tenía enlaces a ficheros), ni la serie trimestral en xls.
- No he verificado si penotariado ofrece descarga o API.
- La estadística de la AEAT de viviendas declaradas en el IRPF existe (ver la FAQ citada en §3), pero no he revisado su formato de descarga.

## 9. Idealista API y otros portales

### Takeaway
Idealista tiene una API oficial ("idealista Search API") con OAuth2 client credentials, pero el acceso es **por solicitud con formulario y no está garantizado**. El endpoint de token existe y responde 401 sin credenciales. Las condiciones generales de idealista prohíben el scraping. No he encontrado APIs públicas de Fotocasa ni de Habitaclia.

### Cited Findings
- **[VERIFICADO EN VIVO]** `https://api.idealista.com/oauth/token` → 401 `{"error":"unauthorized","error_description":"Full authentication is required to access this resource"}`. El servicio OAuth2 está activo.
- **[VERIFICADO EN VIVO]** En `https://developers.idealista.com/access-request` se lee: "idealista Search API … Search API lets you integrate property information published on idealista into your site or app. To receive an API key get in touch and tell us a bit about your project." La solicitud se hace mediante un formulario (`api/clients`).
- Según un resumen secundario, las condiciones generales de idealista (actualizadas el 30-04-2025) prohíben acceder, monitorizar o copiar contenido con robots o scrapers sin permiso escrito. No lo he verificado en el texto original. — [ScrapingBee (secundaria)](https://www.scrapingbee.com/scrapers/idealista-api/)
- **[DOCUMENTADO, sin fuente primaria verificada en esta sesión]** Lo siguiente lo dicen manuales de terceros y clientes de código abierto y procede de mi conocimiento previo:
  - Búsqueda: `POST https://api.idealista.com/3.5/{es|it|pt}/search`.
  - Token: Basic auth con apikey:secret y `grant_type=client_credentials&scope=read`.
  - Parámetros: `operation` (`sale`/`rent`), `propertyType` (`homes`, `offices`, `premises`, `garages`, `bedrooms`), `center` (lat,lon), `distance`, `locationId`, `maxItems` (≤50), `numPage`, filtros de precio, tamaño y habitaciones.
  - Campos devueltos: `propertyCode`, `price`, `size`, `rooms`, `bathrooms`, `floor`, `latitude`, `longitude`, `address`, `district`, `neighborhood`, `priceByArea`, `status`, `newDevelopment`, `url`, entre otros.
  - Cuota típica: unas 100 peticiones al mes y 1 por segundo.
  
  **La cifra de 100 al mes no la he podido confirmar** con una fuente primaria. — búsqueda sin resultado primario: [lobehub (terceros)](https://lobehub.com/skills/openclaw-skills-idealista)

### Inferences
- Con unas 100 peticiones al mes, un agente no puede barrer el mercado. Como mucho puede hacer consultas puntuales (por ejemplo, comparables en un radio) y debe cachear con prudencia, siempre según los términos que firme el cliente.
- La alternativa legal más robusta es que el usuario pegue el anuncio (URL o texto) y el agente lo enriquezca con fuentes públicas.

### Gaps
- No he encontrado los términos de la API (almacenamiento, caché, atribución) en una fuente primaria.
- No he investigado Fotocasa, Habitaclia ni pisos.com en detalle; no he encontrado APIs públicas suyas.

## 10. Datos abiertos regionales y municipales: alquileres por fianzas, viviendas turísticas, certificados energéticos

### Takeaway
Cataluña (Socrata, con API SODA en JSON) y la Comunidad de Madrid (CKAN) tienen APIs abiertas que funcionan y que incluyen **rentas medias por fianzas** (Cataluña, semestral, por municipio y por ámbitos inferiores), **registros de viviendas turísticas** (Madrid) y **certificados energéticos con referencia catastral** (Cataluña).

### Cited Findings
- **[VERIFICADO EN VIVO] Cataluña, alquiler medio por municipio** (fianzas del INCASÒL). `https://analisi.transparenciacatalunya.cat/resource/qww9-bvhh.json?$limit=2` devuelve registros como `{"ambit_territorial":"Municipi","codi_territorial":"08001","nom_territori":"Abrera","any":"2026","periode":"gener-juny","habitatges":"62","renda":"783.62","tram_preus":"> 600 euros/mes"}`. Actualizado el 02-11-2026; último año 2026 (primer semestre); 47.541 filas. El dataset hermano `hepw-33ik` da los ámbitos supramunicipales. La API SODA admite `$select`, `$where`, `$group`; sin token, Socrata limita el ritmo de peticiones.
- **[VERIFICADO EN VIVO] Cataluña, certificados energéticos.** `https://analisi.transparenciacatalunya.cat/resource/j6ii-t3w2.json?$limit=1` devuelve dirección, código postal, **`referencia_cadastral`**, `metres_cadastre`, `us_edifici`, la calificación de consumo y de emisiones, la energía primaria no renovable, el coste anual aproximado, valores de aislamiento y ventanas, `motiu_de_la_certificacio` y las instalaciones renovables.
- **[VERIFICADO EN VIVO] Comunidad de Madrid (CKAN).** `https://datos.comunidad.madrid/api/3/action/package_search?q=…`:
  - `registro_certificados_eficiencia_energetica`: modificado el 02-11-2026, recursos en ZIP y CSV.
  - `declaraciones_actividad_viviendas_uso_turistico`: modificado el 16-11-2026, en CSV, JSON y ZIP histórico. URL CSV: `https://datos.comunidad.madrid/dataset/914c95d2-455e-4797-893f-97b1e2b2426e/resource/41072914-3b76-46b2-bfff-4afdd48ed3cc/download/declaraciones_actividad_viviendas_uso_turistico.csv`.
- Ficha de datos.gob.es del registro de certificados energéticos (a13002908, Madrid): actualización mensual; el año en curso en CSV y 2024-2025 en ZIP. — [datos.gob.es](https://datos.gob.es/es/catalogo/a13002908-registro-de-certificados-de-eficiencia-energetica-de-edificios)
- La Comunidad Valenciana (IVACE) publica los certificados en abierto desde 2011. — [eseficiencia](https://www.eseficiencia.es/2022/06/27/ivace-abre-portal-datos-abiertos-certificacion-energetica-edificios-desde-2011)
- El RD 390/2021 obliga a publicar en abierto la información básica de los certificados; los campos mínimos están en BOE-A-2022-1833. — [BOE-A-2022-1833](https://boe.gob.es/boe/dias/2022/02/04/pdfs/BOE-A-2022-1833.pdf)
- **[VERIFICADO EN VIVO] Catálogo nacional.** `https://datos.gob.es/apidata/catalog/dataset/title/alquiler?_pageSize=5` → 200 (Linked Data API en JSON). Sirve para descubrir datasets de otras CCAA.

### Inferences
- Cataluña es la única CCAA en la que el agente puede comparar una renta pedida con **rentas reales de contratos** (fianzas) de 2026, y no solo con el SERPAVI de 2024.
- Los certificados energéticos con RC permiten unir eficiencia, Catastro y anuncio. Una calificación E/F/G señala posible obra o reforma y riesgo de normativa futura.

### Gaps
- No he verificado datasets de fianzas de Madrid (Agencia de Vivienda Social), Euskadi (Etxebide/Observatorio Vasco de la Vivienda), Andalucía ni Valencia.
- No he verificado los registros municipales de licencias turísticas (Barcelona HUT, Ayuntamiento de Madrid) ni el registro único estatal de arrendamientos de corta duración (vigente desde 2025).
- No he encontrado un registro abierto de ITE/IEE a nivel estatal.

## 11. ITP por comunidad autónoma

### Takeaway
No he encontrado una fuente oficial legible por máquina. La referencia oficial es el informe anual "Tributación Autonómica" del Ministerio de Hacienda (PDF); las tablas de terceros se contradicen entre sí. Conviene mantener una tabla propia versionada y verificada contra la norma de cada CCAA.

### Cited Findings
- El tipo supletorio estatal es del 6 %, pero todas las CCAA tienen tipos propios. Las fuentes secundarias dan rangos distintos (6-13 %, 4-13 %, 4-10 %). — [Gibobs ITP 2026](https://www.gibobs.com/blog/itp-2026/), [Raisin](https://www.raisin.com/es-es/tributacion/que-impuestos-se-pagan-al-comprar-una-vivienda-en-espana/)
- Ejemplos de tipos de 2026 según fuentes secundarias:
  - Andalucía: 7 % de ITP y 1,2 % de AJD. — [idealista news](https://www.idealista.com/news/node/880585)
  - Extremadura: TPO del 8-11 % por tramos y 1,5 % de AJD. — [guiafiscal](https://guiafiscal.es/patrimonio/itp/extremadura/)
- Castilla-La Mancha publica consultas y criterios de ITP en PDF (2026). — [JCCM](https://portaltributario.jccm.es/sites/portaltributario.castillalamancha.es/files/documentos/pdf/20260511/c-76-2026-itpajd-tpo.pdf)

### Inferences
- El agente debería tratar el ITP como regla de dominio (con fecha de vigencia y fuente) y no como dato vivo. La API de legislación consolidada del BOE (§7) permite detectar si se actualizan las leyes autonómicas de tributos cedidos.

### Gaps
- No he localizado el PDF de "Tributación Autonómica 2026" del Ministerio de Hacienda.

## 12. Ideas de asimetría de información: cruces que un inversor normalmente no ve

### Takeaway
Las asimetrías más potentes y factibles con fuentes abiertas verificadas se apoyan en la cadena **dirección → CartoCiudad (RC + coordenadas) → Catastro (m², año, uso) + sección censal (shapefile) → SERPAVI/ADRH/fianzas**. El valor de referencia y el Notariado por código postal añaden mucho, pero necesitan intervención del usuario o trabajo manual.

### Cited Findings (fuentes de cada pieza, ya citadas arriba)
1. **m² del anuncio frente a m² del Catastro.** CartoCiudad da la RC del portal; Consulta_DNPRC da `sfc` y `lcons` por inmueble. Si el anuncio declara bastantes más m² que el Catastro, puede haber superficie inflada (cuenta zonas comunes o terrazas) o una ampliación sin regularizar, que es un riesgo registral y fiscal. El €/m² "real" sube. — [§1](https://www.catastro.hacienda.gob.es/ws/WCFservices_Consulta.pdf), [§2](https://www.cartociudad.es/geocoder/api/geocoder/findJsonp?q=Calle%20Alcala%2050%20Madrid)
2. **Año de construcción del anuncio frente al del Catastro (`ant`) y certificado energético.** Detecta "reformado" frente a "original" y los edificios anteriores a 1980 (ITE, amianto, eficiencia). En Cataluña el certificado energético se une por RC. — [Cataluña j6ii-t3w2](https://analisi.transparenciacatalunya.cat/resource/j6ii-t3w2.json)
3. **Renta pedida frente a SERPAVI p25/mediana/p75 por sección censal.** Identifica alquileres que quedarían por encima del índice; en ZMRT, con tope para grandes tenedores o primer alquiler, la renta del business plan no sería legal. También detecta lo contrario: zonas donde el índice está muy por debajo del mercado, con el riesgo regulatorio que eso supone si se declara la zona. — [SERPAVI xlsx](https://www.mivau.gob.es/vivienda/alquila-bien-es-tu-derecho/serpavi)
4. **Mapa de rentabilidad bruta por sección censal.** Alquiler SERPAVI (€/m²·12) dividido entre el precio de compra €/m² (Notariado por código postal o comparables de anuncios). Muestra bolsas de yield alto que los portales, agregados por barrio, no enseñan. Se puede ponderar con la renta del ADRH (solvencia del inquilino) y el número de testigos (`BI_ALVHEPCO`) como fiabilidad. — [INE ADRH](https://ine.es/dyngs/Prensa/en/ADRH2024.htm)
5. **Precio pedido frente a valor de referencia.** Si el precio es menor que el valor de referencia, el ITP se paga sobre el valor de referencia y el coste real de compra sube. Si es mucho mayor, hay sobreprecio respecto a la media de transacciones. Requiere que el usuario aporte el valor (Sede con Cl@ve). — [Xataka](https://www.xataka.com/basics/como-saber-valor-casa-piso-valor-referencia-catastro)
6. **Precio pedido frente a precio notarial del código postal.** El gap entre oferta y cierre por código postal indica margen de negociación. — [penotariado](https://www.genbeta.com/web/este-mapa-notarios-muestra-gratis-precio-real-viviendas-tu-codigo-postal-cualquier-parte-espana/amp)
7. **Renta pedida frente a fianzas reales del INCASÒL (Cataluña, semestral, 2026).** Es más reciente que SERPAVI (2024) y refleja contratos, no anuncios. — [qww9-bvhh](https://analisi.transparenciacatalunya.cat/resource/qww9-bvhh.json)
8. **Riesgo de "ZMRT próxima".** Municipios aún no declarados con un crecimiento fuerte del IPVA o SERPAVI y un esfuerzo alto (renta frente a ADRH) son candidatos a declaración. Se puede seguir con la API del sumario del BOE. — [§4](https://www.mivau.gob.es/vivienda/alquila-bien-es-tu-derecho/serpavi/consultar-zonas-de-mercado-residencial-tensionado)
9. **Densidad de viviendas turísticas por municipio o portal.** VTE del INE y registros de Madrid indican presión turística y posible competencia o regulación futura; en un edificio con muchas VUT, puede haber conflicto vecinal. — [INE VTE](https://servicios.ine.es/wstempus/js/ES/SERIES_OPERACION/VTE?page=1), [Madrid VUT](https://datos.comunidad.madrid/api/3/action/package_show?id=declaraciones_actividad_viviendas_uso_turistico)
10. **Proyección de la renta con el IRAV y la cuota con el Euríbor del BdE.** Cash-on-cash con datos vivos (IRAV 2,57 % en octubre de 2026; Euríbor 12M 3,239 % en octubre de 2026). — [INE IRAV](https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IRAV1?nult=1), [BdE](https://app.bde.es/bierest/resources/srdatosapp/favoritas?idioma=es&series=D_1NBAF472)
11. **Subastas por debajo de mercado.** El CSV de Justicia da la relación entre importe de subasta, tasación y deuda (estadística de descuentos). La localización individual exige que el usuario aporte el identificador de la subasta, porque el `robots.txt` del portal prohíbe automatizar. — [Subastas_Judiciales.csv](https://catalogodatos.justicia.es/csv/Subastas_Judiciales.csv)

### Inferences
- Las ideas 1, 2, 3, 4, 7, 9 y 10 son totalmente automatizables hoy con fuentes verificadas en vivo, sin clave y sin coste.
- Las ideas 5 y 6 aportan mucho valor, pero tienen fricción: identificación del usuario y portal sin API.
- La idea 11 es la más delicada legalmente; conviene limitarse a enriquecer subastas que aporte el usuario.

### Gaps
- No he validado empíricamente la magnitud de estas asimetrías (por ejemplo, la diferencia media entre m² de anuncio y de Catastro); haría falta una muestra de anuncios.
- Licencias: el INE, el BdE, el BOE, el Catastro (servicios libres) y los portales autonómicos suelen permitir la reutilización con cita de la fuente (Ley 37/2007 y licencias tipo CC-BY). No lo he verificado fuente por fuente en esta sesión.
