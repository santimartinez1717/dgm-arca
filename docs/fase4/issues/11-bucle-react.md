# Fase 4 · El bucle ReAct (`agent/react_agent.py`) con guardarraíles y tres cerebros

**Responsable:** Bernardo · **Hito:** H1 · **Depende de:** nada; las piezas del núcleo ya están
en `fase4`

## Contexto

Es el corazón de la fase 4 y lo que corrige el profesor a través de `POST /agent`. Todas las
piezas que el bucle orquesta ya existen y están probadas (diseño en `docs/fase4/diseno.md`):

| Pieza | Dónde | Qué ofrece |
|---|---|---|
| Expediente | `agent/case_file.py` | `CaseFile`, `active(case)` (context manager), `current()`, `load`/`save` por `session_id`, `render()` |
| Tools del caso | `agent/tools/case_tools.py` | `CASE_TOOLS`: `record_property`, `record_investor`, `analyze_property`, `find_levers`, `what_if` |
| Conocimiento | `agent/tools/knowledge.py` | `search_knowledge_base` (claves `[K1]` en `case.sources`) |
| Auditor | `agent/auditor.py` | `audit(answer, sources, figures, retrieved_ids)` → `AuditResult` (`ok`, `answer` con aviso, `feedback()`) |
| Memoria | `agent/memory.py` | `ConversationMemory` con la política: tarea fija, observaciones viejas recortadas, `render(system_prompt)` |
| Prompts | `agent/prompts.py` | `AGENT_SYSTEM_PROMPT` (con `{max_steps}`), `SUMMARY_PROMPT`, `BUDGET_NUDGE` |
| Fase 2 | `tool_use/` | `parse_tool_calls`, `format_tool_result`, `ToolRegistry.call` (nunca lanza), `HFChatModel` (modelo compartido, adaptador por petición) |

## Qué hay que hacer

### 1. Cerebros

`BRAINS` en `agent/react_agent.py`. Los tres usan el mismo modelo compartido
(`api.shared_model`):

| Cerebro | Modelo | Adaptador | Thinking |
|---|---|---|---|
| `base` | `ARCA_AGENT_MODEL`, por defecto `Qwen/Qwen3-1.7B` | ninguno | no |
| `rlm` | el mismo | `ARCA_AGENT_RLM_ADAPTER`, o si no existe `ARCA_RLM_ADAPTER` | no |
| `thinking` | `ARCA_THINKING_MODEL`, por defecto el mismo | ninguno | sí |

- Generación greedy y formato nativo de tools (`tools=registry.definitions()`), como en la fase 2.
- El modelo se envuelve en un protocolo `generate(messages, tools) -> (text, prompt_tokens,
  completion_tokens)`, para que los tests usen un cerebro falso guionizado sin cargar nada.

### 2. Registro

- Sale de `tool_use.tools.default_registry()` menos las calculadoras sueltas que solapan con
  `analyze_property` (`acquisition_cost`, `rental_returns`, `legal_rent_cap`,
  `rental_income_tax`).
- Más `CASE_TOOLS`, `search_knowledge_base` y `final_answer`.
- Más las tools de las issues 02 y 03 cuando estén.
- Conviene dejar unas 13–15 tools: un 1,7B se pierde con más.

### 3. `run(task, max_steps, brain, session_id=None, confirm=False)`

1. Carga el expediente con `case_file.load(session_id)`, o crea uno nuevo con un uuid. Mete los
   pisos de la ingesta de CSV (issue 12). Todo el run va dentro de `with active(case):`.
2. En cada paso, el sistema es `AGENT_SYSTEM_PROMPT.format(max_steps=...)` + `case.render()`,
   regenerado en cada paso (anclado). La tarea es el primer mensaje `user`, fijado en memoria.
3. **Cada tool call cuenta como un paso.** `n_steps == len(steps) <= max_steps`, incluido el
   `final_answer`. Las llamadas paralelas de una generación se ejecutan en orden hasta agotar
   los pasos; la primera lleva el `thought` y las siguientes, uno vacío.
4. **Timeout por tool:** `ARCA_AGENT_TOOL_TIMEOUT`, 30 s por defecto.
   - Se ejecuta en un hilo con `contextvars.copy_context().run(...)`. Sin eso, la tool no ve el
     expediente.
   - El timeout vuelve como observación.
   - Hay que precargar el RAG en `load()`, o la primera búsqueda superará el timeout.
5. **Detector de bucles:** la misma llamada con los mismos argumentos por segunda vez lleva un
   aviso añadido; a la tercera no se ejecuta y se pide `final_answer`.
6. **Confirmación:** las tools `requires_confirmation` solo se ejecutan con `confirm=True`. Si
   no, la observación dice que hace falta confirmación y se añade a `case.open_questions`.
7. **Presupuesto:** `ARCA_AGENT_TOKEN_BUDGET` en tokens totales (prompt + respuesta, sumados
   en todos los pasos).
   - Al 80 % se añade `BUDGET_NUDGE` a la observación.
   - Al 100 % se corta con una respuesta de reserva.
8. **Memoria:** se llama a `memory.compress(summarize)` después de cada paso. `summarize` usa
   el cerebro `base` con `SUMMARY_PROMPT`, igual para los tres cerebros, para que la comparación
   sea justa.
9. **`final_answer`, o texto sin tool call, que se trata igual y se marca en el `thought`:**
   - Se pasa por `audit(...)`. Las `sources` son la tarea y todas las observaciones; las
     `figures`, los `value` de `case.figures`; los `retrieved_ids`, `case.sources`.
   - Si falla, `feedback()` vuelve como observación, como mucho 2 veces. A la tercera se entrega
     con la auditoría fallida.
   - `succeeded = audit.ok`.
10. **Sin pasos:** respuesta de reserva con lo calculado (`case.render()`), el aviso y
    `succeeded=False`.
11. **Al terminar:** `case_file.save(case)` y se devuelve `AgentResponse` con los campos
    opcionales de la issue 12.

### 4. Interruptores para las ablaciones (issue 06)

`ReActAgent(audit=True, use_playbook=True, anchor_case_file=True)`.

- Sin playbook no se registran `find_levers` ni `what_if`.
- Sin anclaje, el expediente no va en el sistema.

## Criterios de aceptación

`tests/test_react_agent.py` usa un cerebro falso guionizado y comprueba:
- `max_steps` respetado;
- timeout;
- tool rota;
- bucle detectado;
- confirmación denegada;
- auditor que rechaza y luego acepta;
- respuesta sin `final_answer`;
- presupuesto agotado;
- persistencia del expediente entre dos `run` con el mismo `session_id`.

Además, una prueba de humo en CPU:

```bash
CUDA_VISIBLE_DEVICES="" ARCA_AGENT_MODEL=HuggingFaceTB/SmolLM2-135M-Instruct \
  uv run python -c "from agent.react_agent import ReActAgent; print(ReActAgent.from_env().run('Piso en Valencia de 180.000 € alquilado por 850 €/mes, ¿rentabilidad?', max_steps=4, brain='base').model_dump_json(indent=1))"
```

Y `uv run pytest -q` en verde, más `ruff`.
