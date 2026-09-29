# Propuesta de tema — Umbral: analista de inversión inmobiliaria que no se olvida de la ley

> Investigación de fondo, competencia y comprobación de fuentes en
> [`propuesta_investigacion.md`](propuesta_investigacion.md).

## Equipo

- Bernardo Ordás — _(correo)_
- Enrique Rodríguez — _(correo)_
- Santiago Martínez Díe — sant.martinez2004@gmail.com

## El tema en una frase

Un agente que analiza pisos como inversión para alquilar en España —rentabilidad neta real,
flujo de caja con hipoteca, impuestos y precio máximo a pagar— aplicando los topes de renta de
la ley de vivienda y la fiscalidad del IRPF que las calculadoras de rentabilidad ignoran, y que
filtra y compara candidatos contra los criterios que fija el propio inversor.

## El usuario y su problema

**El pequeño inversor particular**: tiene entre uno y diez pisos, o quiere comprar el primero
para alquilar, y analiza varias operaciones al mes. En España son la inmensa mayoría de los
arrendadores. También el analista junior de una gestora pequeña, que hace lo mismo a escala.

**Qué hace hoy.** Una hoja de cálculo por piso con una "rentabilidad bruta" (renta × 12 /
precio) que se parece poco a la real. Consulta el alquiler de la zona en portales y el Euríbor
en la prensa, y el tema fiscal lo deja para el gestor en la declaración de la renta.

**Qué le cuesta.** Tres errores caros que se repiten:

1. **Ignorar el tope legal de la renta.** En zona tensionada, si el casero es gran tenedor
   o si el piso tuvo contrato en los últimos cinco años, la renta del nuevo contrato está
   limitada (art. 17.6 y 17.7 LAU tras la Ley 12/2023). El 6 % bruto calculado con la renta
   de mercado puede ser un 4 % legal.
2. **No ver el umbral de gran tenedor.** Comprar el quinto piso en una zona tensionada cuya
   declaración rebaje el umbral cambia las reglas para todos los contratos nuevos de esa zona.
3. **Calcular mal los impuestos.** ITP sobre el valor de referencia del Catastro si supera al
   precio. La amortización del 3 % solo sobre la construcción. La reducción del rendimiento
   del alquiler que da el IRPF va del 50 % al 90 % según el contrato (art. 23.2 LIRPF), y cambia
   por completo la rentabilidad después de impuestos.

**Por qué necesita un agente y no una calculadora.** El trabajo real no es calcular un piso,
es **filtrar muchos**. Hay que buscar candidatos, descartar primero con lo barato (precio,
zona), completar lo que falta (metros y año en el Catastro, alquiler de la zona, si está en
zona tensionada), calcular, ordenar y explicar por qué descartó cada uno. El número de pasos
depende de lo que vaya encontrando: eso es un bucle ReAct, no una cadena fija.

## Diez preguntas o tareas reales

1. "¿A cuánto está el Euríbor a 12 meses?"
2. "Compro por 160.000 € y lo alquilo a 850 € al mes. ¿Qué rentabilidad bruta tiene?"
3. "Piso usado en Málaga por 180.000 €, el Catastro dice que su valor de referencia es
   195.000 € y el ITP allí es del 7 %. ¿Cuánto dinero tengo que poner en total con 3.200 € de
   notaría y registro y 12.000 € de reforma?"
4. "¿Cuadra el anuncio con el Catastro? Dice 85 m² y construido en 2005."
5. "Con un IBI de 420 €, comunidad de 60 € al mes, seguro de 180 € y un mes vacío al año,
   ¿qué rentabilidad neta me queda?"
6. "Está en zona tensionada, el anterior inquilino pagaba 780 € ya actualizados y yo tengo
   3 pisos. ¿Cuánto puedo pedir como máximo si el mercado paga 950 €?"
7. "¿Cuánto tributaré en el IRPF por este alquiler si se lo alquilo a una chica de 27 años
   y es la primera vez que se alquila?"
8. "Quiero un 5 % neto. ¿Cuánto es lo máximo que debería pagar por este piso?"
9. "Tengo 4 pisos en Barcelona. Si compro este quinto, ¿paso a ser gran tenedor? ¿Qué me
   cambia en la renta que puedo cobrar en el nuevo contrato?"
10. "Te paso 15 pisos en un CSV. Quédate con los que den más de un 4,5 % neto después de
    impuestos cumpliendo la ley, ordénalos, dime por qué descartas el resto y hazme el informe."

## La tarea verificable (fase 1)

**El tipo de problema.** Cálculos de inversión inmobiliaria bajo la normativa española, con
respuesta numérica en euros o en porcentaje. La dificultad no está en la aritmética sino en
**saber qué regla aplica**:

- qué base imponible: precio o valor de referencia;
- qué tope de renta: ninguno, la renta anterior, la anterior más un 10 % o el índice de
  referencia, según zona, gran tenedor y contratos previos;
- qué reducción del IRPF: 90, 70, 60 o 50 %, y solo si el rendimiento neto es positivo;
- qué gastos tienen límite: intereses más reparaciones, como mucho los ingresos.

**Separamos datos y reglas.** El enunciado da los **datos**, que cambian con el tiempo y en la
fase 4 vendrán de herramientas: tipo de ITP de la comunidad, índice de referencia, valores
catastrales, Euríbor. El modelo tiene que haber **aprendido las reglas**, que son estables:
base = máx(precio, valor de referencia), amortización del 3 % sobre la parte de construcción,
orden de las reducciones, topes de la LAU. Una ablación con las reglas copiadas en el
enunciado (`--with-rules`) mide cuánto de la dificultad es conocimiento y cuánto razonamiento.

**Seis familias en train/test y dos fuera de distribución:**

| Familia | Respuesta | Regla clave |
|---|---|---|
| `acquisition_cost` | Capital total invertido (€) | ITP sobre máx(precio, VR); IVA + AJD en obra nueva |
| `net_yield` | Rentabilidad neta (%) | Meses vacíos, gastos fijos y porcentuales |
| `legal_rent` | Renta mensual máxima (€) | LAU 17.6 y 17.7, definición de gran tenedor (Ley 12/2023, art. 3.k) |
| `irpf_rental` | Rendimiento neto reducido (€) | Amortización 3 % construcción, límite intereses + reparaciones, reducción 23.2 |
| `cash_on_cash` | Rentabilidad sobre capital propio (%) | Cuota francesa, entrada, gastos |
| `max_price` | Precio máximo para una rentabilidad objetivo (€) | Problema inverso: despejar el precio |
| OOD `max_price_capped` | Precio máximo con la renta topada (€) | Composición no vista: tope legal + problema inverso |
| OOD `becomes_large_holder` | Renta máxima tras comprar el N-ésimo piso (€) | Composición no vista: umbral de gran tenedor + tope |

**Tres ejemplos con su respuesta** (salen de la implementación de referencia):

- *"Compro un piso usado en Málaga por 180.000 €. Su valor de referencia es 195.000 € y el
  ITP de la comunidad es del 7 %. Notaría y registro, 3.200 €; reforma, 12.000 €. ¿Cuánto
  capital necesito en total?"* → ITP = 7 % × 195.000 = 13.650 € → **208.850,00 €**. Usar el
  precio en vez del valor de referencia da 207.800 €, y el verificador lo rechaza.
- *"Piso en zona tensionada. El último contrato, de hace dos años, tiene una renta actualizada
  de 780 €. El propietario tiene 3 viviendas. El mercado pagaría 950 €. ¿Qué renta mensual
  máxima puede pactar en el nuevo contrato?"* → no es gran tenedor, así que aplica el 17.6 →
  **780,00 €**.
- *"Ingresos anuales 10.200 €, IBI 420 €, comunidad 720 €, seguro 180 €, intereses 2.900 €,
  reparaciones 400 €. Coste de adquisición con gastos 190.000 €, valor catastral 110.000 €
  (40 % suelo). Nuevo contrato en zona tensionada con una inquilina de 27 años, primera vez que
  se alquila. ¿Rendimiento neto reducido?"* → amortización 3 % × 190.000 × 60 % = 3.420 € →
  neto 10.200 − 1.320 − 3.300 − 3.420 = 2.160 € → reducción del 70 % → **648,00 €**.

**Cómo se verifica.** Un `EuroVerifier` propio que:

- entiende los formatos español e inglés: `208.850,00 €`, `208850`, `208,850.00`,
  `1.050` (mil cincuenta, no uno coma cero cinco) y `4,37 %`;
- aplica una tolerancia por problema, guardada en el JSONL: ±0,01 € más un 0,05 % relativo en
  euros, para no castigar el redondeo intermedio, y ±0,01 puntos en porcentajes;
- rechaza respuestas con dos cifras candidatas.

Los casos límite van a `tests/test_verifier.py`.

**Cómo construimos el conjunto: generador programático (estrategia 1) + control (estrategia 3).**
Un motor de reglas (`rlm/realestate_rules.py`) con cada regla documentada con su artículo y su
fuente oficial. `solve` usa ese motor y es a la vez la implementación de referencia y el
verificador.

- `sample_params` muestrea precios log-normales, valor de referencia entre 0,8 y 1,3 veces el
  precio (para que gane cada uno la mitad de las veces), rentas, gastos, tipos de ITP del 4 al
  10 %, número de viviendas del propietario alrededor de los umbrales (4-6 y 9-12), contrato
  anterior sí/no, edad del inquilino alrededor de 35, rendimientos netos negativos (donde no
  hay reducción), e intereses más reparaciones por encima de los ingresos.
- `render` usa varias plantillas por familia, con datos en orden variable y datos
  irrelevantes de distracción (planta, orientación, barrio).
- Cada fila guarda sus **valores intermedios** (base imponible, amortización, tope aplicado),
  que usa la tercera recompensa.
- **Control:** un 10 % de GSM8K.

**Tamaños:** `train` 2.400 (400 por familia); `test` 300 (50 por familia, 50 auditados a mano);
`test_ood` 150. Deduplicación por hash de parámetros, intersección vacía entre ficheros y tabla
de ramas de `solve` en `EXPERIMENTS.md`.

**Tercera recompensa (`domain_reward`): desglose trazable.**

- 0,5 puntos si la respuesta lleva la unidad correcta (€ o %).
- 0,5 puntos por la fracción de valores intermedios que aparecen en el razonamiento, **solo si
  la respuesta final es correcta**, para no premiar que copie cifras sin resolver.

¿Por qué? Una cifra sin desglose no le sirve al inversor para discutir con el banco o el
gestor. Como ablación compararemos esta recompensa con la versión sin esa condición, que da
crédito parcial al proceso. Vigilaremos el *reward hacking* más esperable: escribir en el
razonamiento todas las cifras posibles.

## Las herramientas (fase 2)

Comprobadas con peticiones reales, sin clave, el 28 y 29/09/2026, salvo donde se indica.

**Consulta fuera del modelo**

- `lookup_property(address | cadastral_ref)`: CartoCiudad geocodifica y devuelve la referencia
  catastral, y los servicios libres del Catastro dan uso, superficie y año de construcción.
  [CartoCiudad](https://www.cartociudad.es/geocoder/api/geocoder/findJsonp) ·
  [Catastro](https://www.catastro.hacienda.gob.es/ws/Webservices_Libres.pdf)
- `get_market_rates()`: Euríbor a 12 meses (API del Banco de España, serie `D_1NBAF472`) e
  IRAV (API JSON del INE).
- `get_rent_index(lat, lon)`: rango del SERPAVI (MIVAU) por sección censal, a partir de las
  capas descargables, y si la zona está declarada tensionada.
- `search_auctions(province)`: subastas de inmuebles a partir del sumario diario de la API de
  datos abiertos del BOE.
- `search_listings(...)`: API de Idealista, **opcional**, si nos conceden acceso.

**Cálculo**

- `analyze_investment(...)`: el mismo motor de reglas de la fase 1. Un modelo de 1,7B no debe
  calcular de cabeza una cuota francesa a 300 meses ni un problema inverso. Que el generador y
  la herramienta compartan código nos permite medir en la fase 4 si el modelo entrenado sigue
  delegando o se fía de sí mismo.

**Acción con efecto observable** (con confirmación)

- `save_to_portfolio(...)`: cartera persistente en SQLite, con estado. Sirve para el
  razonamiento de gran tenedor, que depende de los pisos que ya tienes.
- `write_investment_report(...)`: informe en PDF o Markdown en `outputs/`. Se comprueba que
  sus cifras coinciden con las de las herramientas.

## El corpus (fase 3)

- **De dónde.**
  - Normativa consolidada descargada con la API de datos abiertos del BOE: Ley 12/2023, LAU,
    Ley 35/2006 del IRPF y su reglamento, TRLITPAJD, Ley 11/2021 del valor de referencia,
    Ley 5/2019 de crédito inmobiliario, arts. 104-110 del TRLRHL (plusvalía) y las
    resoluciones de declaración de zonas tensionadas.
  - Manual práctico de Renta de la AEAT, capítulo de rendimientos del capital inmobiliario.
  - Metodologías del SERPAVI (MIVAU), del IRAV (INE) y del valor de referencia (Catastro).
  - Guías hipotecarias del Banco de España.
- **Cuánto.** Unos 50 documentos, del orden de 2.000 páginas.
- **Formato.** XML/HTML del BOE, estructurado por artículos, lo que aprovecharemos en el
  chunking; HTML de la AEAT; PDF del resto.
- **Licencia.** BOE: reutilización con cita de la fuente (Ley 37/2007, RD 1495/2011). AEAT,
  INE, MIVAU, Catastro y BdE permiten reutilizar su información con atribución. El corpus se
  regenera con un script y no se sube al repositorio.
- **Dos preguntas que solo se responden leyendo el corpus.**
  - "Si alquilo a un ayuntamiento para alquiler social, ¿qué reducción tengo en el IRPF?" →
    70 %, art. 23.2.b LIRPF.
  - "¿Cuándo se puede subir un 10 % la renta del contrato anterior en zona tensionada?" →
    rehabilitación o mejora en los dos años previos, o contrato de diez años o más
    (art. 17.6 LAU).

## Qué puede salir mal

1. **No hay API abierta de anuncios.** La de Idealista está restringida a proyectos aprobados
   y la hemos solicitado. Nada depende de ella: el agente trabaja sobre los candidatos que
   aporta el inversor (CSV o texto del anuncio), sobre subastas del BOE y sobre fuentes
   oficiales. No haremos *scraping* de portales.
2. **La normativa cambia a mitad de proyecto.** En 2026 ya han cambiado el ITP valenciano y los
   coeficientes de plusvalía. Las reglas llevan fecha de vigencia y fuente, y la normativa se
   congela a una fecha de corte documentada.
3. **Dependemos de la comprensión jurídica del equipo.** Cada regla del motor tiene un test con
   un caso resuelto a mano citando el artículo. En los casos dudosos (el tope para viviendas
   sin contrato previo depende de cada resolución de zona) el dato va explícito en el
   enunciado.
4. **Un modelo pequeño con aritmética encadenada.** Es precisamente lo que queremos medir:
   pass@1 por familia y análisis de si falla la regla o la cuenta.
5. **Parecer asesoramiento de inversión.** El agente evalúa contra los criterios que da el
   usuario y no recomienda comprar. Cada respuesta indica que es orientativa y remite a un
   asesor fiscal. Todos los datos de los problemas son sintéticos.

## Por qué este tema

Porque la vivienda es el tema de nuestra generación, y porque al investigarlo vimos que el
hueco no está en buscar pisos (eso ya lo hacen Luci y los portales) sino en analizarlos bien.
Las reglas que cambian la rentabilidad están publicadas y casi nadie las aplica. Es un dominio
con verificador exacto, fuentes públicas que funcionan y un corpus legal real, y el filtrado de
candidatos justifica un agente de verdad.
