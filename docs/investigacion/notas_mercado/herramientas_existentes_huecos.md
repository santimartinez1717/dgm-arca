# Herramientas existentes para el inversor particular de compra-para-alquilar en España (2025-2026) y huecos

Notas de investigación escritas el 17-11-2026. Se hicieron unas 18 búsquedas y lecturas de páginas. Muchas fichas de producto no publican precios. Distingo así el origen de cada dato:
- **[verificado]**: lo dice la página oficial o la ficha del producto.
- **[marketing]**: afirmación del propio vendedor.
- **[terceros]**: lo dice un medio o un agregador.

## 1. Portales (idealista, Fotocasa, Habitaclia, pisos.com): qué análisis dan gratis y qué hacen con la IA

### Takeaway
Los portales venden datos y búsqueda. No ofrecen análisis fiscal ni legal. idealista tiene una herramienta de "oportunidades de inversión" con rentabilidad estimada y un catálogo B2B (AVM, API, estudios) sin precios públicos. Desde marzo-abril de 2026, idealista y Fotocasa tienen apps dentro de ChatGPT, pero solo para buscar y comparar anuncios. Ninguna fuente indica que calculen impuestos, topes de renta ni rentabilidad neta tras IRPF.

### Cited Findings
- **idealista/inversores ("Oportunidades de inversión")** [verificado]. Filtra por zona, rentabilidad mínima y estado. Estima el coste de la reforma y enlaza con hipotecas. — [idealista data: servicios para inversores](https://www.idealista.com/data/servicios-para-inversores-inmobiliarios); [idealista.com/inversores](https://www.idealista.com/inversores)
- Según un medio, la herramienta permite consultar cualquier anuncio de idealista con datos de demanda, alquiler estimado y rentabilidad estimada, e indica si el precio es un "chollo" o está por encima de la media [terceros]. — [casacochecurro](https://www.casacochecurro.com/idealista-presenta-una-herramienta-para-inversores-que-quieran-comprar-pisos-para-alquilar.html)
- **Catálogo B2B de idealista/data** [verificado]:
  - datos energéticos y ESG;
  - estudios de mercado a medida;
  - Market Navigator (valoración individual o masiva por AVM, con datos sociodemográficos);
  - datos por API, widgets o ficheros (España, Portugal e Italia);
  - AVM de carteras por el método de comparación de la Orden ECO 805/2003.
  
  La página no da precios ni plan gratuito y no menciona impuestos, IRPF ni topes de alquiler. — [idealista data](https://www.idealista.com/data/servicios-para-inversores-inmobiliarios)
- **API de idealista.** No encontré la página oficial de desarrolladores ni la cuota de peticiones. Varios proveedores de scraping (Apify, ScrapingBee, Zenrows, Oxylabs) afirman que idealista no tiene una API pública abierta y que su feed es solo para socios [terceros, no verificado]. — [Apify](https://apify.com/blackfalcondata/idealista-scraper/api); [ScrapingBee](https://www.scrapingbee.com/scrapers/idealista-api/)
- **Rentabilidad bruta agregada de idealista.** La calcula como precio de alquiler ofertado frente a precio de venta ofertado. Cifras publicadas:

  | Periodo | Rentabilidad bruta |
  |---|---|
  | 1T 2025 | 7,3 % |
  | 3T 2025 | 6,9 % |
  | 2T 2026 | 6,5 % |

  Es bruta y se basa en precios de oferta. — [idealista news 1T25](https://www.idealista.com/news/inmobiliario/vivienda/2025/04/08/839989-la-rentabilidad-de-la-vivienda-se-mantiene-en-el-7-3-en-el-primer-trimestre-de-2025); [idealista etiqueta rentabilidad](https://www.idealista.com/news/etiquetas/rentabilidad-vivienda); [Bolsamanía 3T25](https://www.bolsamania.com/noticias/empresas/economia--la-rentabilidad-del-alquiler-de-vivienda-cae-hasta-el-69-en-el-tercer-trimestre-segun-idealista--21003605.html)
- **App de idealista en ChatGPT** (nota del 13-03-2026) [verificado]:
  - busca viviendas, habitaciones, garajes, locales y terrenos en lenguaje natural;
  - muestra fotos, precios y mapa, compara anuncios y resume sus características.
  
  La nota no menciona rentabilidad, impuestos, topes legales ni valoración. Un rastreador de apps da como fecha de alta el 21-04-2026, lo que no encaja con la nota. — [idealista news](https://www.idealista.com/en/news/property-for-sale-in-spain/2026/03/13/887103-idealista-launches-its-app-on-chatgpt); [getdrio](https://www.getdrio.com/app-tracker/idealista)
- **Fotocasa** [terceros]:
  - "Fotocasa brAIn" (2024): chatbot de dudas sobre vivienda;
  - búsqueda asistida por IA tras un hackathon de octubre de 2025;
  - app en ChatGPT (abril de 2026) para buscar alquiler o compra por conversación.
  
  — [OnlineMarketplaces brAIn](https://www.onlinemarketplaces.com/articles/fotocasa-launches-brain-ai-chatbot-to-answer-property-queries/); [OnlineMarketplaces Fotocasa ChatGPT](https://www.onlinemarketplaces.com/articles/product-and-services-roundup-fotocasa-launches-chatgpt-app)
- Fotocasa publica la rentabilidad bruta media: 6,2 % en el 3T de 2025 [terceros, vía resumen de búsqueda]. — [Observatorio Inmobiliario](https://observatorioinmobiliario.es/noticias/inversion-inmobiliaria/la-rentabilidad-de-la-vivienda-en-alquiler-cae-al-72-en-el-segundo-trimestre/)
- **Otros buscadores con IA** [terceros]:
  - Kelify, portal "AI-native" lanzado en España en 2025;
  - PisosGPT, buscador independiente que agrega anuncios de idealista y Fotocasa.
  
  Ninguno se presenta como herramienta de análisis de inversión. — [OnlineMarketplaces](https://www.onlinemarketplaces.com/articles/product-and-services-roundup-chatgpt-additions-for-rightmove-idealista-and-hepsiemlak/); [trabajarporelmundo PisosGPT](https://trabajarporelmundo.org/pisosgpt-ia-busca-casa/); [Genbeta](https://www.genbeta.com/a-fondo/despues-probar-chatgpt-para-buscar-comprar-piso-paso-idealista-solo-hay-algo-que-echo)

### Inferences
- La IA de los portales se ha centrado en la búsqueda conversacional (encontrar el piso), no en el análisis (si conviene comprarlo y qué rinde neto). Las apps de ChatGPT de idealista y Fotocasa dejan al LLM genérico la parte de razonar, sin un motor fiscal o legal detrás.
- El dato de rentabilidad de los portales es bruto y se calcula con precios de oferta. El inversor se queda sin la rentabilidad neta, sin el efecto de la financiación y sin la fiscalidad.

### Gaps
- No pude verificar las condiciones ni las cuotas de la API oficial de idealista (en developers.idealista.com no se encontró nada en la búsqueda). Hay que consultarlo directamente.
- No investigué las funciones para inversores de Habitaclia y pisos.com: no salieron en los resultados.
- No conozco el precio de idealista/data ni de la herramienta de inversores. No sé si es gratuita para particulares.

## 2. Proptech y herramientas especializadas: quién hace qué

### Takeaway
El ecosistema español es amplio pero está fragmentado:
- inversión indirecta: Urbanitae (crowdfunding), Reental (tokenización);
- datos y valoración profesional: Casafari, Tinsa, idealista/data;
- gestión del alquiler: Rentier, Vivara, Housfy;
- un analista de anuncios con IA: Invisor.

Solo Invisor se acerca a "analizar si un anuncio concreto es buena inversión", y su página no menciona ITP, IRPF ni zona tensionada.

### Cited Findings
- **Invisor (invisor.es, © 2026)** [verificado en su web]:
  - el usuario define una "tesis" de inversión;
  - pega el enlace de un anuncio (idealista, Fotocasa, Habitaclia, pisos.com, Milanuncios o Wallapop) y recibe una puntuación de 0 a 100 con la rentabilidad bruta y neta, el cash flow, el precio frente a la zona, el impacto de la reforma, el entorno y los riesgos;
  - modo mercado: aplica la tesis a todos los anuncios, agrupa duplicados y avisa de los candidatos.
  
  Plan gratuito: 1 tesis y 5 análisis manuales; prueba de 24 h con tarjeta (100 análisis). Los precios de pago no aparecen en esa página, que tampoco menciona ITP, IRPF ni zona tensionada. Se anuncia como "calculadora con IA" en el título de búsqueda, pero la página no explica qué tecnología usa. — [Invisor](https://invisor.es/analisis-inmueble/)
- **Rentier (rentier.es)**: software de gestión de alquileres para inversores, con un "copiloto" y planes desde 9 €/mes [marketing, vía resumen de búsqueda]. — [Rentier](https://www.rentier.es/)
- **Vivara (iniciativa de GCO Ventures)** [verificado en su web]:
  - negocio: gestión integral con renta garantizada y seguros;
  - herramientas gratuitas: comprobador de zona tensionada por municipio (sin registro, da el límite general), calculadora de "rentabilidad tras IRPF" con las reducciones del 90 % y del 70 %, revisor de contratos y calculadora de actualización de renta.
  
  La propia página remite al SERPAVI para la cifra exacta de cada vivienda y no dice si usa IA. — [Vivara](https://www.vivara.io/blog/innovacion/precio-alquiler-zona-tensionada-serpavi/)
- **Brickbro**: en la búsqueda solo aparece como intermediario de locales comerciales (por ejemplo, gestiona los locales de Ralco Capital, un vehículo de 20 M€). No aparece como herramienta de análisis de vivienda para particulares. — [idealista news](https://www.idealista.com/news/node/809366)
- **Casafari**: se presenta como "la mayor base de datos inmobiliaria de Europa" [marketing]. BBVA le atribuye más de 60.000 usuarios en PT, ES, IT, FR y DE [terceros]. Va dirigida a profesionales; no encontré precio. — [Urbanitae blog/entrevista](https://blog.urbanitae.com/en/?p=31516); [BBVA](https://www.bbva.com/es/innovacion/big-data-apps-o-blockchain-la-tecnologia-innovadora-que-revoluciona-el-sector-inmobiliario/)
- **Urbanitae**: crowdfunding de grandes proyectos; ha creado una gestora autorizada por la CNMV. Anuncia proyectos con TIR objetivo (por ejemplo, 10 %) [marketing]. Es inversión indirecta: no analiza la compra directa de un piso. — [Alimarket](https://www.alimarket.es/construccion/noticia_amp/419877/urbanitae-crea-una-gestora-de-fondos-propios); [Urbanitae informe 1T26](https://blog.urbanitae.com/wp-content/uploads/2026/05/informe_vivienda_urbanitae_2026_q1_es.pdf)
- **Tinsa** publica valores medios (2.066 €/m² de media nacional en el 2T de 2026). No encontré el precio de Tinsa Digital para particulares. — [Urbanitae informe 2T26](https://blog.urbanitae.com/wp-content/uploads/2026/09/informe_vivienda_2026_q2_urbanitae_es.pdf)
- **Reental**: solo aparece en listados de startups, sin detalle. — [Seedtable](https://seedtable.com/best-proptech-startups-in-spain)
- **Normatia**: aparece una "API legal" en normatia.com, sin detalle verificado. — [Normatia](https://normatia.com/es/legal/api)

### Inferences
- Nadie en España parece combinar las tres piezas en una sola herramienta para particulares:
  1. el dato del anuncio (precio y alquiler estimado);
  2. la fiscalidad real (ITP por CCAA con valor de referencia e IRPF del rendimiento);
  3. la legalidad de la renta (tope en zona tensionada, gran tenedor).
  
  Lo más cercano son Invisor en el análisis del anuncio y Vivara o TaxDown en el cálculo fiscal y legal, pero por separado.
- Varias herramientas gratuitas (Vivara, TaxDown, Housfy) sirven para captar clientes de un servicio de pago (gestión o declaración). Esto sesga el análisis y explica que sean calculadoras genéricas.

### Gaps
- No verifiqué Housell, Inversis, Alquiler Seguro, Arrenta, Sociedad de Tasación, Invesmart, Inmoanalisis ni Bcas, por falta de presupuesto de búsquedas.
- No leí el "primer mapa de IA del sector inmobiliario español" de BrainsRE, que podría listar más asistentes de IA. — [BrainsRE](https://brainsre.news/primer-mapa-ia-el-sector-inmobiliario-espanol/)
- No encontré precios de Casafari, Tinsa Digital, Reental ni de los planes de pago de Invisor.

## 3. Calculadoras, Excel y herramientas fiscales: ¿modelan el art. 23.2, la amortización y los topes?

### Takeaway
Hay muchas calculadoras gratuitas (TaxDown, Taxfix, Housfy, Bankinter, El Club de Inversión, Omni, Rankia, Vivara). La más completa que encontré es la de TaxDown. Aun así, el porcentaje de reducción del art. 23.2 lo elige el usuario y la calculadora no comprueba si se cumplen los requisitos. Tampoco calcula el ITP: pide un porcentaje genérico de "impuestos de compra".

### Cited Findings
- **Calculadora de TaxDown** [verificado en su web].
  - Entradas: obra nueva o segunda mano; precio; alquiler; porcentaje de impuestos de compra; notaría, registro y gestoría; reforma; hipoteca opcional (importe, TIN, plazo); IBI; comunidad; seguro; reparaciones; meses vacíos; IRPF opcional (otros ingresos, reducción aplicable de 0 a 100 % en un desplegable, valores catastrales del suelo y de la construcción).
  - La página no describe el formato de salida ni confirma de forma explícita la amortización (los valores catastrales sugieren que sí la calcula).
  - Es gratuita. Los planes de declaración para propietarios cuestan desde 35, 45 o 65 €/año (PRO, LIVE, FULL); el FULL no está disponible en régimen foral.
  
  — [TaxDown calculadora](https://taxdown.es/propietario/calculadora-rentabilidad-alquiler)
- TaxDown tiene además un buscador de zonas tensionadas por dirección. — [TaxDown zonas tensionadas](https://taxdown.es/propietario/zonas-tensionadas)
- **Calculadora de Taxfix**: según el resumen de búsqueda, la rentabilidad bruta solo usa alquiler y precio de compra, sin más gastos [terceros]. — [Taxfix](https://taxfix.com/es-es/calculadoras/calculadora-de-rentabilidad-de-un-alquiler/)
- **El Club de Inversión**: calcula ROCE, cash flow y rentabilidad bruta y neta [terceros]. — [El Club de Inversión](https://www.elclubdeinversion.com/calculadora-rentabilidad-alquiler/)
- **Otras calculadoras y plantillas**: Housfy (calculadora web y guía para usar un Excel), Bankinter, Omni y una calculadora en Rankia. — [Housfy](https://housfy.com/alquileres/calculadora-rentabilidad); [Housfy Excel](https://housfy.com/blog/como-calcular-la-rentabilidad-de-un-alquiler-con-un-excel/); [Bankinter](https://www.bankinter.com/blog/finanzas-personales/calculadora-rentabilidad-alquiler); [Omni](https://www.omnicalculator.com/es/finanzas/calculadora-de-la-rentabilidad-neta-del-alquiler); [Rankia](https://www.rankia.com/promociones/hipotecas/calculadora-rentabilidad-inversion-inmueble)
- **Vivara**: su calculadora "tras IRPF" contempla las reducciones del 90 % y del 70 %. El comprobador de zona tensionada da el límite general y remite al SERPAVI para la cifra exacta. — [Vivara](https://www.vivara.io/blog/innovacion/precio-alquiler-zona-tensionada-serpavi/)

### Inferences
- El patrón común es que las calculadoras piden al usuario los datos más difíciles: el tipo de ITP de su CCAA, la base (valor de referencia frente a precio) y el porcentaje de reducción del art. 23.2. Justo ahí es donde se equivoca el inversor novel.
- No encontré ninguna que encadene las reglas: si el contrato es posterior al 26-05-2023 en zona tensionada y la renta baja un 5 %, corresponde el 90 %, etc.

### Gaps
- No revisé en detalle Renta WEB (AEAT) ni Declarando. Se sabe que Renta WEB pide las cifras del inmueble, pero no lo verifiqué en esta sesión.
- No encontré ningún Excel concreto recomendado en Rankia, Forocoches ni Reddit.

## 4. ¿Alguna herramienta comprueba la legalidad de la renta, calcula el ITP con valor de referencia, simula el IRPF o analiza subastas del BOE?

### Takeaway
Solo de forma parcial y en herramientas separadas:
- **legalidad de la renta**: comprobadores por municipio (Vivara, TaxDown) y el SERPAVI oficial;
- **IRPF**: estimación con la reducción elegida por el usuario (TaxDown, Vivara);
- **ITP**: no encontré ninguna herramienta privada que aplique automáticamente el tipo de la CCAA y el valor de referencia del Catastro;
- **subastas**: la app de la AEAT (buscador y alertas) y un proyecto académico ("BOESubastas AI", TFM de la UB) que propone cruzar con el Catastro y detectar cargas con OCR, sin producto verificado.

### Cited Findings
- **SERPAVI** es la fuente oficial del índice de referencia, consultable por dirección o referencia catastral. Fuera de zona tensionada el índice es solo informativo. Para los grandes tenedores (10 o más viviendas), la renta no puede superar el índice en zona tensionada. — [La Moncloa](https://www.lamoncloa.gob.es/serviciosdeprensa/notasprensa/vivienda-agenda-urbana/paginas/2024/indice-referencia-precio-alquiler-vivienda-sepavi.aspx)
- **Reglas de tope que resume Vivara**:
  - pequeño propietario con contrato en los últimos 5 años: la renta anterior actualizada;
  - sin contrato previo o gran tenedor: el índice SERPAVI;
  - gran tenedor: 5 o más viviendas en la zona en Cataluña, 10 o más en el resto;
  - multas de 9.001 a 90.000 €.
  
  — [Vivara](https://www.vivara.io/blog/innovacion/precio-alquiler-zona-tensionada-serpavi/)
- **App de subastas de la AEAT (nov. 2022)**: buscador de inmuebles con mapa y alertas por preferencias. — [AEAT nota](https://sede.agenciatributaria.gob.es/Sede/en_gb/notas-prensa/notas-prensa/2022/noviembre/25/agencia-tributaria-pone-marcha-aplicacion-subastas.html)
- **"BOESubastas AI"** (pitch deck de un TFM de la UB, oct. 2026): notificaciones por zona y precio, cruce con el Catastro (metros, uso, antigüedad, valor de referencia), OCR para cargas ocultas y calculadora de ROI. Es una propuesta, no un producto verificado. — [UB Fintech PDF](https://www.ub.edu/fintech/wp-content/uploads/2026/10/1788378936344_BOESubastas_AI_Pitch_Deck_TFM_Entregable.pdf)

### Inferences
- Que un TFM de 2026 proponga precisamente "subastas + Catastro + ROI" indica que el hueco sigue abierto y que hay interés.
- La verificación de legalidad que existe es a nivel de municipio. Para una vivienda concreta nadie combina el índice SERPAVI, la condición de gran tenedor y el historial del contrato con la rentabilidad resultante.

### Gaps
- No encontré ninguna calculadora privada de ITP con valor de referencia por CCAA (puede existir y no haber salido).
- No conozco la calidad ni la precisión de los comprobadores de Vivara y TaxDown: no hay evaluaciones independientes.

## 5. Comparables internacionales: funciones que aún no existen en España

### Takeaway
En EE. UU. el análisis de operaciones es una categoría madura y barata: DealCheck cuesta de 10 a 29 $/mes, y hay "AI underwriters" (BNBCalc, CanaryAI, DealWise). Allí se combinan comparables automáticos, financiación y proyecciones. Sin embargo, DealCheck no se presenta como IA y ninguna de estas herramientas modela la fiscalidad ni la regulación españolas.

### Cited Findings
- **DealCheck**: Plus a 10 $/mes y Pro a 20 $/mes en facturación anual (14 y 29 $ en mensual); plan gratuito con hasta 15 inmuebles; una revisión de julio de 2026 dice "No AI" [terceros]. — [BNBCalc review DealCheck 2026](https://www.bnbcalc.com/reviews/dealcheck-review-2026-what-airbnb-investors-need-to-know); [Layer3labs](https://www.layer3labs.io/guides/ai-tools-for-real-estate-investors)
- **Mashvisor**: las fuentes no coinciden. Una da de 17,99 a 74,99 $/mes; una captura de octubre de 2026 da Lite 39,99, Standard 74,99 y Professional 99,99 $/mes en anual [terceros]. — [batchdata](https://batchdata.io/blog/best-ai-tools-real-estate-investors); [aitoolsbakery](https://aitoolsbakery.com/blog/best-ai-tools-for-real-estate-investors/)
- **"AI underwriters"**: BNBCalc AI Underwriter (alquiler vacacional; informes, comparables y datos de préstamo), HouseCanary CanaryAI (desde unos 19 $/mes) y DealWise AI (comercial, 178 $/mes) [terceros]. — [BNBCalc pricing](https://www.bnbcalc.com/es/pricing); [Capterra DealWise](https://www.capterra.com/p/10042001/DealWise-AI/); [gravity.fast agentes IA](https://gravity.fast/blog/ai-agents-for-real-estate-investors/)

### Inferences
- Funciones de EE. UU. sin equivalente claro para el particular español:
  - análisis de una operación con un clic a partir del anuncio, con comparables de alquiler (aquí solo Invisor y, en parte, idealista/inversores);
  - informes descargables para el banco o para socios;
  - escenarios de financiación y proyección a 5-10 años.
- La pieza que el modelo de EE. UU. no necesita y en España es crítica es la capa normativa: los topes de renta, las reducciones del IRPF condicionadas al contrato y el ITP autonómico.

### Gaps
- No investigué el Reino Unido (Rightmove, PropertyData, calculadoras de stamp duty y Section 24).
- Los precios de EE. UU. vienen de agregadores, no de las páginas oficiales.

## 6. Quejas de los usuarios

### Takeaway
Encontré poca evidencia directa en foros (Rankia, Forocoches, Reddit no salieron en la búsqueda). La única valoración cualitativa relevante es la de La Fiebre del Ladrillo, de octubre de 2024 (dato antiguo): ChatGPT es superficial, "se pierde" al profundizar, su Excel no es profesional y usa un tipo impositivo fijo del 20 % sin justificarlo.

### Cited Findings
- **La Fiebre del Ladrillo (14-10-2024)**:
  - ChatGPT da un plan de partida válido, pero "una vez que intentas profundizar sobre un tema, se pierde" y "opta siempre por la opción básica";
  - la plantilla Excel que genera no es profesional;
  - el ejemplo aplica un tipo impositivo plano del 20 %;
  - "No creo que estemos todavía listos para dejarnos asesorar por una inteligencia artificial".
  
  — [La Fiebre del Ladrillo](https://lafiebredelladrillo.substack.com/p/uso-chatgpt-para-comprar-un-piso)
- Las fuentes no coinciden en las cifras: rentabilidad bruta de idealista 6,5-7,3 % según el trimestre, Fotocasa 6,2 % en el 3T25, y una web atribuye un 4-4,5 % al Banco de España (sin verificar). Para el usuario esto genera confusión sobre qué cifra creer. — [idealista](https://www.idealista.com/news/inmobiliario/vivienda/2025/04/08/839989-la-rentabilidad-de-la-vivienda-se-mantiene-en-el-7-3-en-el-primer-trimestre-de-2025); [OCU mapa rentabilidades 2026](https://www.ocu.org/fincas-y-casas/gestion/gestion-patrimonial/analisis/2026/02/mapa-de-rentabilidades)

### Inferences
- La queja sobre los LLM genéricos (superficiales, con tipos fiscales inventados o planos) es justo lo que resolvería un agente con un motor de reglas determinista.

### Gaps
- No encontré hilos de Rankia, Forocoches ni r/SpainFIRE con quejas concretas sobre herramientas. No hay reseñas de las tiendas de apps. Haría falta una búsqueda dentro de cada foro.

---

### Síntesis: necesidades no cubiertas donde un agente con herramientas aporta algo que nada más ofrece
Cada punto es una inferencia a partir de lo anterior.
1. **Análisis de punta a punta de un anuncio concreto**: precio, ITP real (tipo de la CCAA × máx(precio, valor de referencia)) o IVA y AJD en obra nueva, gastos, hipoteca, y rentabilidad bruta, neta y tras IRPF. Hoy se reparte entre Invisor (anuncio), TaxDown o Vivara (fiscal) y el SERPAVI (legal).
2. **Legalidad de la renta de esa vivienda**: zona tensionada, índice SERPAVI, gran tenedor según la CCAA y renta del contrato anterior. Hoy solo hay comprobadores por municipio.
3. **Reducción del art. 23.2 deducida, no elegida**: el agente determina si corresponde el 50, 60, 70 o 90 % según la fecha del contrato, la zona, la bajada de renta o el inquilino joven. Hoy el usuario elige el porcentaje en un desplegable.
4. **Amortización correcta**: el 3 % sobre el mayor entre el coste de adquisición y el valor catastral, excluido el suelo, con la proporción catastral del suelo. Ninguna calculadora la muestra de forma explícita y verificable.
5. **Explicaciones con trazas verificables**: cada cifra con la regla y la norma que la justifican, frente a los LLM genéricos que dan tipos planos (la queja de La Fiebre del Ladrillo).
6. **Subastas del BOE con cálculo de rentabilidad y riesgos (cargas, ocupación)**: existe la app de búsqueda de la AEAT y un TFM, pero ningún producto verificado.
7. **Comparar escenarios** (comprar aquí o allí, larga estancia o temporada con la ley vigente, ser o no gran tenedor) en lenguaje natural, sobre datos públicos (Catastro, SERPAVI, INE). Las apps de los portales en ChatGPT solo buscan anuncios.
