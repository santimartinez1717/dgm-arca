# Fase 4 · Diseño del agente

Umbral es un analista de inversión en vivienda para alquilar que se sabe los trucos.
Este documento fija la arquitectura y las interfaces que comparten las piezas. Las issues de
`docs/fase4/issues/` remiten aquí: quien implemente una pieza respeta lo que dice este documento
sobre las demás.

## La idea en una frase

**El LLM decide qué mirar y lo explica; el motor pone todos los números; el corpus justifica.**

Las fases anteriores lo dicen con datos:

- **El motor acierta donde el modelo falla.** En IRPF, el modelo base con tools acierta 12 de 20
  y el GRPO 2 sin ellas, 1 de 20 (EXPERIMENTS.md, fase 2).
- **El mejor generador de RAG es la base con thinking.** Cita el pasaje correcto en 21 de 30
  casos; el RLM cita peor y se trunca (fase 3).
- **El adaptador GRPO 2 rompe el formato de tool call.** En el banco v9, la selección baja de
  39/40 sin adaptador a 27/40 con él (fase 2). Lo arregla un fine-tune de formato antes de
  usarlo como `brain=rlm`.

Así que el agente no pide al cerebro que calcule ni que recuerde la ley. Le pide que **busque
palancas**, es decir, cambios legales en el caso que mejoran la rentabilidad. Cada palanca la
comprueba el motor en contrafactual y cada afirmación legal se apoya en una cita del corpus.
El "listillo" está en los números, no en la labia.

## Arquitectura

```
 tarea (+ session_id) ──► 0. Ingesta determinista de CSV → Expediente (SQLite)
                           (los datos en prosa los guarda el modelo con record_property /
                            record_investor: rellenar argumentos ya lo hace bien, fase 2)
                              │
                              ▼
 ┌─────────── 1. Bucle ReAct (cerebro: base | rlm | thinking) ───────────────────────┐
 │ contexto = sistema + EXPEDIENTE ANCLADO + resumen de lo antiguo + últimos pasos   │
 │ Thought → <tool_call>(s) → Observation                                            │
 │ guardarraíles: max_steps · timeout por tool · detector de bucles ·                │
 │                presupuesto de tokens · confirmación de tools con efecto           │
 └─────────────────────────────┬─────────────────────────────────────────────────────┘
                               ▼ final_answer(propuesta)
 2. Auditor determinista
    · cada cifra de la respuesta sale de una observación del motor
    · cada cita [id] es un pasaje recuperado en esta ejecución
    · una palanca cualitativa no lleva cifra
    · la respuesta incluye el aviso y la remisión a un asesor
    si falla, vuelve al bucle como observación (como mucho dos veces); si no, se entrega
                               ▼
 AgentResponse: el contrato de api/schemas.py más campos opcionales
                (session_id, levers, scenarios, open_questions, audit)
```

Solo hay un bucle. Las etapas 0 y 2 son código, no modelo, y por eso la comparación entre
cerebros sigue siendo limpia: cambia el cerebro y todo lo demás queda igual. El multiagente es un
extra para el final, no el diseño de partida.

## Los tres cerebros

Los tres usan el mismo Qwen3-1.7B, cargado una vez (`api/shared_model.py`); el adaptador se
cambia por petición.

| `brain` | Adaptador | Thinking |
|---|---|---|
| `base` | ninguno | no |
| `rlm` | `ARCA_RLM_ADAPTER` (GRPO 2 con el formato de tool call arreglado) | no |
| `thinking` | ninguno | `enable_thinking=True` |

El RLM nunca es la fuente de una cifra, porque eso lo impide el auditor. La pregunta "¿ayuda
haber entrenado?" se mide en lo que el entrenamiento puede mejorar:

- elegir la palanca y la tool adecuadas;
- dar los argumentos correctos;
- el número de pasos y los tokens;
- la tasa de éxito en el banco.

## El expediente (`agent/case_file.py`)

El expediente es el estado del caso. Vive por `session_id` en SQLite (`ARCA_CASE_DB`, por defecto
`outputs/cases.sqlite`) y va **siempre** al principio del contexto, renderizado en un bloque
compacto. Así se evita el efecto "perdido en el medio".

```python
class InvestorProfile(BaseModel):
    region: str | None = None  # community where they buy (or a city)
    properties_owned: int | None = None  # dwellings already owned (large holder)
    properties_owned_stressed: int | None = None
    area_owned_m2: float | None = None
    financing: bool | None = None
    down_payment_pct: float | None = None  # 20 means 20 %
    interest_rate_pct: float | None = None
    loan_years: int | None = None
    target_net_yield_pct: float | None = None


class Property(BaseModel):
    id: str  # "P1", or the user's label
    municipality: str | None = None
    region: str | None = None
    price: float | None = None
    reference_value: float | None = None
    new_build: bool = False
    area_m2: float | None = None
    monthly_rent: float | None = None  # asking rent
    previous_rent: float | None = None
    stressed_zone: bool | None = None
    cadastral_value: float | None = None
    land_share_pct: float | None = None
    contract_date: date | None = None
    ibi: float = 0.0
    community_monthly: float = 0.0
    insurance: float = 0.0
    renovation: float = 0.0
    rehabilitation_last_2y: bool = False
    tenant_age: int | None = None


class Figure(BaseModel):  # a number the engine produced
    property_id: str | None
    name: str  # "net_yield_pct", "itp", "irpf_net_income"...
    value: float
    unit: str  # "%", "EUR", "EUR/month"
    tool: str  # tool that produced it
    scenario: str = "base"  # or a lever id / "if reference_value=..."


class Assumption(BaseModel):
    property_id: str | None
    field: str
    value: Any
    reason: str


class CaseFile(BaseModel):
    session_id: str
    profile: InvestorProfile
    properties: dict[str, Property]
    figures: list[Figure]
    assumptions: list[Assumption]
    open_questions: list[str]
```

Las tools que trabajan sobre el caso (`analyze_property`, `screen_properties`, `find_levers`,
`what_if`, `write_investment_report`) reciben el `CaseFile` activo con `agent.case_file.current()`,
que es un `contextvar` fijado por el bucle. El modelo solo les pasa ids de piso y parámetros, nunca
el expediente entero. Lo que calculan lo añaden con `case.add_figure(...)`, y así el auditor sabe
de dónde sale cada número.

## Tools del agente

Son unas diez, con nombres y descripciones pensados para un modelo de 1,7B. Las de la fase 2 se
reutilizan tal cual.

| Tool | Quién | Qué hace |
|---|---|---|
| `analyze_property(property_id)` | núcleo | Análisis completo con el motor (coste de compra, renta legal, neto, cash-on-cash, IRPF); escribe las cifras en el expediente |
| `screen_properties(min_net_yield_pct, ...)` | Bernardo | Pasa todos los pisos del expediente por `analyze` y devuelve una tabla con los que pasan, los descartados con su motivo y los que casi pasan |
| `max_offer_price` | fase 2 | Precio máximo para llegar a una rentabilidad objetivo |
| `find_levers(property_id)` | núcleo | Palancas del playbook cuyas condiciones cumple el caso, con su nivel y su cita |
| `what_if(property_id, levers / overrides)` | núcleo | Contrafactual con el motor: diferencia en neto, cash-on-cash e IRPF por palanca y combinadas; también sirve para bifurcar un dato dudoso |
| `search_knowledge_base(query, date?)` | núcleo | Retriever de la fase 3 (semántico p90, λ = 0,2); con fecha, la ley vigente ese día |
| `lookup_property`, `get_market_rates`, `get_rent_reference` | fase 2 | Datos públicos que faltan |
| `get_portfolio` / `save_to_portfolio` | fase 2 | Cartera y gran tenedor; guardar pide confirmación |
| `write_investment_report(property_ids)` | Bernardo | Informe Markdown en `outputs/` con cifras solo del expediente; pide confirmación |
| `final_answer(answer)` | núcleo | Cierra el bucle y pasa por el auditor |

## El playbook de palancas (`agent/playbook/levers.yaml`)

Es un catálogo curado. `find_levers` lo filtra de forma **determinista**, evaluando predicados
sobre el expediente; el RAG queda para justificar, no para descubrir.

```yaml
- id: contract_date_rdl_29_2026
  level: legal            # legal | grey | illegal_warning
  title: Fecha de firma del contrato frente al RDL 29/2026
  applies_when:           # todas se cumplen
    - {field: property.stressed_zone, op: eq, value: true}
  engine:                 # null para palancas cualitativas
    set: {property.contract_date: "2026-11-30"}
  evidence:               # mismo formato que rag/gold: se comprueba con rag.gold.locate
    source: boe/rdl_29_2026.md
    section: Artículo 1
    quote: "texto literal del BOE"
  risk: null              # obligatorio si level != legal
  explanation: >
    Explicación en español para el usuario, sin cifras: las cifras las pone what_if.
```

Hay dos tipos de palancas:

- **Cuantificadas.** Las recalcula el motor:
  - fecha del contrato frente al RDL 29/2026;
  - reducciones del IRPF: inquilino joven, rebaja de renta, rehabilitación;
  - ITP según la comunidad, sus bonificaciones y el valor de referencia;
  - obra nueva frente a segunda mano;
  - amortización y gastos;
  - excepción del 10 % al tope de renta;
  - umbral de gran tenedor;
  - precio máximo de oferta.
- **Cualitativas.** Comprar a través de una sociedad, alquiler de temporada o por habitaciones,
  subastas. Llevan cita y riesgo, pero no cifra.

El nivel `illegal_warning` sirve para **reconocer** trampas y advertir de ellas, por ejemplo
"pagar parte en negro" o "no declarar". El agente nunca las propone.

## Datos dudosos: bifurcar

Si falta un dato que cambia la decisión, o si dos datos chocan (una renta pedida por encima del
tope legal, un valor de referencia desconocido), el agente:

1. llama a `what_if` con los dos valores;
2. responde de forma condicionada, por ejemplo "si el valor de referencia es 180.000 €, el neto es
   4,1 %; si es 150.000 €, 4,6 %";
3. deja la pregunta en `open_questions`.

El siguiente turno de la misma sesión la resuelve y actualiza el expediente. Con una sola llamada
a `/agent`, como en la corrección, la respuesta ya es útil sin esperar.

## Memoria

- El expediente no se resume nunca: ya es el resumen de los hechos.
- Al superar el presupuesto de tokens se resumen las observaciones antiguas con `SUMMARY_PROMPT`.
  Antes se recortan las observaciones largas (tablas de cribado, pasajes) a una línea, porque sus
  cifras ya están en el expediente.
- La tarea original y la pregunta abierta se conservan literales.

## Guardarraíles

| Guardarraíl | Comportamiento |
|---|---|
| `max_steps` | Se respeta; al agotarse se responde con lo que hay y `succeeded=false` |
| Timeout por tool | `ARCA_AGENT_TOOL_TIMEOUT`; el timeout vuelve como observación |
| Tool rota | El error vuelve como observación y el agente decide (reintentar, rodear o decir que no puede) |
| Bucle | La misma llamada con los mismos argumentos dos veces lleva un aviso; a la tercera, se fuerza la respuesta |
| Presupuesto de tokens | Por tarea; al acercarse, se pide `final_answer` |
| Confirmación | Las tools `requires_confirmation` no se ejecutan sin `confirm=true` en la petición; la traza lo muestra |
| Tarea imposible | "No puedo saberlo" más lo que sí puede hacer; nunca una cifra inventada (lo impide el auditor) |

## Evaluación

- **Banco** (`agent/bench/tasks.jsonl`): 20 tareas o más, cada una con al menos dos tools y un
  `check` automático. El banco incluye:
  - el CSV de 15 pisos;
  - palancas con cifra;
  - un dato inconsistente;
  - gran tenedor;
  - la ley en una fecha;
  - una tarea imposible;
  - una tool rota.
- **Métricas** por cerebro: tasa de éxito, pasos medios, tokens y uso de las tools requeridas.
- **Ablaciones**: sin auditor, sin playbook, sin expediente anclado (memoria plana).
- **Contraste con CodeAgent**: el `CodeAgent` de smolagents con las mismas tools.
- **Cierre del círculo** (último hito): un SFT del RLM con las trazas del agente que pasan el
  check y el auditor, sobre tareas generadas con el motor y nunca las del banco. Después se vuelve
  a medir `brain=rlm`.

## Quién hace qué

- **Ya hecho en `fase4`:**
  - expediente, `analyze`, esquema del playbook y palancas semilla;
  - `find_levers`, `what_if` y el auditor;
  - `search_knowledge_base`, prompts y política de memoria.
- **Santiago:** fine-tune de formato del RLM (fase 2), revisión de los PR y la defensa.
- **Bernardo:**
  - el bucle ReAct (issue 11);
  - el playbook (issue 01);
  - `screen_properties` y `write_investment_report` (issues 02 y 03);
  - el corpus (issue 04);
  - el cierre del círculo (issue 09).
- **Kike:**
  - campos de la API e ingesta de CSV (issue 12);
  - el banco (issue 05);
  - la evaluación y las ablaciones (issue 06);
  - el contraste con `CodeAgent` (issue 07);
  - la interfaz de trazas (issue 08);
  - el informe y el README (issue 10).
