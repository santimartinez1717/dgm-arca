# Fase 2 · Herramientas: lo que hicimos y por qué

Endpoint: `POST /tools`. Código en [`tool_use/`](../../tool_use), tests en
[`tests/test_domain_tools.py`](../../tests/test_domain_tools.py),
[`tests/test_public_data.py`](../../tests/test_public_data.py) y
[`tests/test_tool_loop.py`](../../tests/test_tool_loop.py). El detalle de cada paso, con fechas,
está en [EXPERIMENTS.md](../../EXPERIMENTS.md).

## 1. Por qué estas herramientas

Antes de escribir código investigamos qué hacen ya los portales, los simuladores fiscales y
los asistentes de IA para el inversor que compra para alquilar
([`investigacion_fase2.md`](investigacion_fase2.md)). Encontramos un hueco claro: **ninguno
aplica la norma por el usuario**. Todos le piden justo lo que no sabe:
- el tipo de ITP de su comunidad;
- si la base del impuesto es el precio o el valor de referencia;
- qué reducción del IRPF le corresponde.

Ninguno dice tampoco si la renta de un piso concreto es legal.

Esos huecos coinciden con los fallos del alumno en la fase 1
([`analisis_fallos_fase1.md`](../fase1/analisis_fallos_fase1.md)):
- en obra nueva se olvida del IVA;
- en el IRPF se salta la amortización;
- en `cash_on_cash` calcula la cuota de la hipoteca a mano y se equivoca.

GRPO no los arregló, y el mismo error en la regla o en la aritmética se repite en cada
problema de esa familia. Por eso decidimos **sacar las reglas y las cuentas de los pesos y
ponerlas en herramientas**.

Construimos 10 herramientas de los tres tipos:

| Tipo | Herramienta | Qué hace |
|---|---|---|
| Consulta (API real) | `lookup_property` | Dirección o referencia catastral → uso, m², año, municipio (código INE) y comunidad. Usa CartoCiudad y el servicio libre del Catastro |
| | `get_market_rates` | Euríbor a 12 meses (Banco de España) e IRAV (INE) |
| | `get_rent_reference` | Si el municipio es zona tensionada, con lo que dice su declaración, y las rentas que se pagan de verdad (SERPAVI) |
| Cálculo (motor de la fase 1) | `acquisition_cost` | Capital necesario para comprar: ITP o IVA + AJD, notaría, agencia, obra |
| | `rental_returns` | Rentabilidad bruta y neta, cuota de la hipoteca, cash-on-cash y estrés de tipos |
| | `max_offer_price` | Precio máximo para llegar a una rentabilidad neta objetivo |
| | `legal_rent_cap` | Renta máxima legal de un contrato nuevo (LAU art. 17.6 y 17.7) |
| | `rental_income_tax` | Rendimiento neto del alquiler en el IRPF, con amortización y la reducción del art. 23.2 |
| Acción con estado | `save_to_portfolio` | Guarda una vivienda en la cartera, en SQLite. Pide confirmación |
| | `get_portfolio` | Lee la cartera y dice si el usuario es gran tenedor |

Tres criterios de diseño:
- **Las calculadoras son una capa fina sobre `rlm/realestate_rules.py`.** El motor sigue
  siendo la única fuente de verdad: lo que entrena la fase 1 y lo que calcula la fase 2 no
  pueden discrepar.
- **Deducen en vez de preguntar.** El ITP sale de la comunidad
  ([`itp_rates.py`](../../tool_use/itp_rates.py)). El régimen de la reducción del IRPF sale de
  la fecha del contrato y de las rentas anterior y nueva. Que sea zona tensionada y lo que dice
  su declaración sale de los datos del BOE. Así el modelo no tiene que saberlo, y el usuario
  tampoco.
- **Cada cifra va con la regla que la produce**, y con avisos cuando el caso se sale de lo
  modelado (un ITP progresivo, una zona tensionada solo en parte del municipio). La respuesta
  puede citarlos.

El RDL 29/2026 es el mejor argumento de que la regla debe vivir en la herramienta. Cambia la
reducción del IRPF para los contratos firmados desde el 01/12/2026
([`rdl_29_2026.md`](../investigacion/rdl_29_2026.md)). El alumno de la fase 1, entrenado con la escala de 2023,
no puede saberlo. La herramienta se actualizó en una tarde, con un test por cada letra del
artículo.

**Lo que no hicimos:**
- **Idealista.** La cuota es de unas 100 llamadas al mes y no aguanta el desarrollo, el banco y
  la corrección a la vez.
- **El valor de referencia del Catastro** no está en abierto.
- **El índice SERPAVI de una vivienda concreta** sale del visor del Ministerio, sin API.
  `get_rent_reference` lo avisa.
- **`calculator`, la calculadora genérica de la plantilla,** sale del registro del endpoint.
  Se queda para una ablación (sección 5).

## 2. Definiciones: qué cambiamos del registro

El registro de la plantilla convierte la firma de la función en un modelo de Pydantic y este en
JSON Schema. Le hicimos tres cambios, pensados para un modelo de 1,7B:

- **Cada argumento lleva su descripción en el esquema.** La plantilla ponía la docstring entera
  en la descripción de la herramienta, y las propiedades del esquema quedaban con tipo pero sin
  significado. Ahora `split_docstring` pasa cada línea de `Args:` a la `description` de su
  propiedad.
- **Sin `title`.** Pydantic añade uno por propiedad que repite su nombre, y se envía en cada
  turno.
- **Las restricciones van en los tipos:**
  - `Annotated[float, Field(ge=0)]` para los euros;
  - `Literal[...]` para las 17 comunidades;
  - rangos en meses, años y edades.

  La validación las comprueba antes de ejecutar nada, y el error vuelve al modelo como
  observación.

Los porcentajes se escriben como los escribe la gente: `8` es un 8 %. Un modelo pequeño copia
números mejor de lo que los convierte.

Las 10 definiciones ocupan **4.767 tokens** con el tokenizador de Qwen3. La más larga es
`rental_income_tax`, con 1.022. Es el precio de poner todo el registro en cada turno.

**Qué funcionó y qué no**, según el banco (sección 4):
- **Un `Literal` con las 17 comunidades no funcionó.** El modelo elegía una al azar:
  Sevilla → `extremadura`, Bilbao → `baleares`. Ahora `region` acepta lo que escribe el
  usuario (comunidad, provincia o municipio) y lo traduce una tabla
  ([`regions.py`](../../tool_use/regions.py)). Los argumentos correctos pasaron de 24 a 32 sobre
  40.
- **Un ejemplo con un valor real se copia.** La descripción de `address` ponía de ejemplo
  "Calle Embajadores 100, Madrid", y el modelo llamó a `lookup_property` con esa dirección en
  un caso que no daba ninguna. Ahora la descripción dice "tal como la escribió el usuario" y
  que nunca se invente una.
- **El modelo rellena todos los opcionales con 0.** Las herramientas lo aceptan donde 0
  significa "no hay" (`loan_years` sin hipoteca). Además, el precio y la inversión tienen que
  ser > 0, para que una llamada que todavía no tiene el valor falle en vez de calcular con 0.
- **Decir en la descripción si una cantidad es mensual o anual** evitó que pusiera la renta
  anual en `monthly_rent`.

## 3. El bucle de cinco pasos

Está en [`tool_use/executor.py`](../../tool_use/executor.py), sin frameworks:

1. **Prompt de sistema con las definiciones.**
2. **Generación.**
3. **Ejecución validada de cada `<tool_call>`.**
4. **Resultado de vuelta como mensaje `tool`.**
5. **Nueva generación.** Si el modelo contesta sin pedir herramientas, se acaba.

- **Encadenado (multi-step):** los pasos 2 a 4 se repiten hasta `max_turns`.
- **Paralelo:** varios `<tool_call>` en una misma generación se ejecutan en el mismo turno,
  en orden.
- **Errores como observación:** si el JSON viene mal formado, la herramienta no existe, la
  validación falla o la herramienta lanza una excepción, el bucle no se rompe. El modelo recibe
  el error y puede corregirse.
- **Dos formatos de prompt** (`ARCA_TOOLS_PROMPT`):
  - `native`: la plantilla de chat de Qwen3, que es con la que se post-entrenó para tool use;
  - `course`: el prompt de sistema de las diapositivas.
- **Confirmación.** `save_to_portfolio` está registrada con `requires_confirmation`. En
  `/tools` se ejecuta (`confirm_policy="auto"`), porque no hay a quién preguntar y el corrector
  tiene que ver el efecto. Con `deny`, el modelo recibe "pide confirmación al usuario". Qué
  hace el agente con esto lo decide la fase 4.
- **El modelo es intercambiable.** El bucle recibe cualquier objeto con
  `generate(messages, tools)`. En los tests es un modelo guionizado, así que el encadenado,
  el paralelo y los errores se prueban en CPU en milisegundos.

El modelo que atiende `/tools` se elige con `ARCA_TOOLS_MODEL`, `ARCA_TOOLS_ADAPTER` y
`ARCA_TOOLS_THINKING` (ver `.env.example`).

## 4. El banco de pruebas

Son 40 casos en [`tool_use/bench/cases.jsonl`](../../tool_use/bench/cases.jsonl):

| Categoría | Casos | Qué mide |
|---|---|---|
| `single` | 20 | Una herramienta, con los argumentos copiados del mensaje |
| `no_tool` | 8 | Preguntas generales que no necesitan herramienta |
| `chain` | 6 | Dos o tres herramientas en orden, usando la salida de una en la siguiente |
| `parallel` | 4 | Llamadas independientes que deberían salir en la misma generación |
| `mapping` | 2 | Traducir lo que dice el usuario a lo que pide el esquema (ciudad → comunidad) |

Las métricas están en [`tool_use/evaluate.py`](../../tool_use/evaluate.py):
- **Selección:** la primera llamada es la esperada, o no hay ninguna si no hace falta.
- **Argumentos:** la primera llamada lleva los argumentos esperados.
  - Los números con un 0,5 % de margen, y el texto sin mayúsculas ni tildes.
  - Un argumento de más solo se acepta si tiene el valor por defecto de la herramienta: un
    modelo que se inventa un IBI falla.
- **Secuencia** (`chain` y `parallel`): están todas las llamadas, en orden y con sus
  argumentos, y las paralelas salieron en la misma generación.
- **Llamadas innecesarias:** la proporción de casos `no_tool` en los que el modelo llamó a una
  herramienta de todas formas.

### Resultados

Casos acertados, de 40. Formato nativo, sin thinking, decodificación voraz.

| Modelo | Selección | Argumentos | Secuencia (10) | Llamadas innecesarias (8) |
|---|---|---|---|---|
| Qwen3-1.7B + GRPO de la fase 1 | 27 | 18 | 2 | 0 |
| Qwen3-1.7B base | 34 | 24 | 4 | 0 |
| Qwen3-1.7B base, tras los arreglos | 37 | 32 | 5 | 0 |
| Qwen3-1.7B base, con los arreglos del encadenado (`eca9bc9`) | **40** | **33** | **6** | 0 |

Informes en `reports/fase2/phase2_bench_*.json`. Detalle y pruebas estadísticas en EXPERIMENTS.md.

- **El modelo base elige bien la herramienta y no llama cuando no hace falta.** Sus errores
  estaban en los argumentos, y la mayoría se arreglaron en las definiciones sin tocar el
  modelo: 8 casos mejoran y ninguno empeora (McNemar exacto, p = 0,008).
- **El adaptador de la fase 1 ha perdido el formato de llamada.** Escribe
  `<function name=…/>`, JSON sin etiquetas o la llamada en prosa, y hace las cuentas él
  mismo. 7 casos empeoran en selección y ninguno mejora (p = 0,016). Por eso `/tools` usa el
  modelo base.
- **Encadenar es lo que sigue fallando:** 1 de 6, y 2 de 6 tras añadir un recordatorio
  después de cada resultado y afinar los errores. El modelo lanza a la vez las llamadas que
  dependen una de otra, o se salta la consulta y se inventa el dato. Las paralelas sí salen
  bien (4 de 4).

### De una llamada a varias

Con una sola herramienta, el modelo acierta 13 de 20 casos tras los arreglos. Con llamadas
independientes en paralelo, 4 de 4. Con llamadas que dependen una de otra, 1 de 6. Lo difícil
no es hacer varias llamadas, sino **esperar** al resultado de una para construir la
siguiente: el modelo planea toda la respuesta en el primer turno. El bucle sí lo permite (el
error "price must be > 0" vuelve como observación), pero el modelo no reintenta con el valor
que ya tiene.

## 5. Con y sin herramientas, sobre el test de la fase 1

[`tool_use/phase1_compare.py`](../../tool_use/phase1_compare.py) usa el mismo modelo, los mismos
problemas y el mismo verificador que la fase 1, en tres variantes:
- `none`: sin herramientas;
- `arithmetic`: solo la calculadora genérica, así que la aritmética está resuelta pero las
  reglas siguen siendo cosa del modelo;
- `domain`: el registro completo.

La diferencia entre `none` y `arithmetic` mide cuánto de los fallos de la fase 1 era
aritmética. La diferencia entre `arithmetic` y `domain` mide cuánto eran reglas.

Medido sobre los 10 primeros problemas de cada familia (60), con Qwen3-1.7B base, sin thinking,
2.048 tokens por turno y hasta 5 turnos. La fase 1 está medida sobre los mismos 60 problemas,
pero con su prompt, thinking y una sola generación.

| | Aciertos (de 60) |
|---|---|
| Base sin herramientas | 1 |
| Base + calculadora | 1 |
| Base + herramientas del dominio (primera versión) | 17 |
| Base + herramientas del dominio (tras ajustar la interfaz) | **20** |
| Fase 1: base con thinking | 5 |
| Fase 1: GRPO | 17 |
| Fase 1: GRPO 2 | 24 |

- **La aritmética no era el problema.** Con la calculadora el resultado no cambia: el modelo
  la usa en 16 de 60 problemas, y cuando la usa aplica igual de mal las reglas.
- **Las reglas, sí.** Con las herramientas del dominio, el modelo base sin entrenar llega al
  nivel de la fase 1 (sin diferencia significativa con GRPO ni GRPO 2). Además, resuelve
  problemas de IRPF (5 de 10), que ningún modelo de la fase 1 resolvía. Le sigue costando el
  precio máximo, que en la fase 1 sí salía.
- **Los fallos que quedan son de interfaz.** El modelo copia una cifra en el argumento
  equivocado (el ingreso neto anual como renta mensual) o se inventa la que no le dan.
  Después, lee mal el resultado: se come el signo de un cash-on-cash negativo. Cambiar el
  orden de dos argumentos movió la rentabilidad neta de 5 a 2 de 10, así que si llegan dos
  cifras incompatibles, la herramienta da error en vez de elegir una.

Hemos ajustado la interfaz mirando estos 60 problemas. Por eso, la última versión (`4e028dd`)
se ha medido también sobre los 10 problemas siguientes de cada familia, que no se habían
usado para ajustar:

| | 60 de ajuste | 60 nuevos | Total (120) |
|---|---|---|---|
| Base + herramientas del dominio (`4e028dd`) | 24 | 27 | **51** |
| Fase 1: SFT 3 | 20 | 26 | 46 |
| Fase 1: GRPO 2 | 24 | 30 | 54 |
| Fase 1: base con thinking | 5 | 9 | 14 |

**El modelo base con herramientas rinde lo mismo que el mejor modelo entrenado de la fase 1**
(McNemar exacto frente a GRPO 2: p = 0,78), pero acierta problemas distintos:
- el IRPF sale con herramientas (12 de 20 frente a 1 de 20), porque la regla vive en el código;
- la renta legal y el precio máximo salen mejor con GRPO 2.

Detalle en EXPERIMENTS.md.

## 6. Limitaciones conocidas

- **La tabla de ITP viene de una fuente secundaria.** Sus 17 filas están marcadas
  `verified=False` hasta contrastarlas con la web de cada comunidad. En las comunidades con
  escala progresiva se usa el tramo general y se avisa.
- **Zonas tensionadas:**
  - Cataluña amplió su lista en julio de 2026, pero la ampliación aún no está en el BOE;
  - las declaraciones parciales se tratan por municipio, sin bajar a sección censal.
- **El IRPF no modela** el reparto entre varios inquilinos de edades distintas, el 80 % de la
  prórroga tácita ni el alquiler por habitaciones.
- **Los tests de las APIs usan respuestas grabadas el 17/11/2026.** Un cambio de formato en
  CartoCiudad o el Catastro no se detectaría sin red.
