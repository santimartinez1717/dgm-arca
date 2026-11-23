# Fase 4 · Contraste con `CodeAgent` de smolagents (¿se cumple CodeAct?)

**Responsable:** Kike · **Hito:** H3 · **Depende de:** la issue 05 (banco) y las tools del agente

## Contexto

El enunciado pide comparar nuestro agente JSON con un agente de código. Es la única fase en la que
se permite `smolagents`, y solo como contraste. El artículo de CodeAct dice que escribir código
como acción reduce los pasos y mejora el éxito en tareas que encadenan herramientas. Hay que ver
si se cumple con un modelo de 1,7B en nuestro dominio. La tarea del CSV de 15 pisos es el caso
ideal: un bucle `for` frente a muchas tool calls.

## Qué hay que hacer

1. `agent/code_agent.py`:
   - Envuelve **las mismas tools** del registro del agente como tools de smolagents (adaptador desde
     `tool_use.registry.Tool`, sin reescribirlas).
   - Usa el mismo modelo compartido (`api.shared_model.get_model`) a través de un `Model` de
     smolagents.
   - Usa `max_steps` iguales.
   - Para que la comparación sea justa, el `CodeAgent` también trabaja sobre el expediente activo.
     Las tools ya leen `agent.case_file.current()`.
2. Modo `--agent code` en `agent/evaluate.py`, que reutiliza el banco, los `check` y las métricas
   de la issue 06.
3. Medir sobre las 24 tareas con `base` y `thinking`:
   - éxito;
   - pasos;
   - tokens;
   - errores de ejecución del código.
4. Escribir la lectura en EXPERIMENTS.md: ¿gana el código en `screening` y pierde en las tareas
   cortas? ¿Un modelo de 1,7B escribe Python válido con nuestras tools?

## Criterios de aceptación

- `uv run python -m agent.evaluate --agent code ...` funciona.
- La tabla JSON frente a código está en EXPERIMENTS.md, con dos trazas de ejemplo de cada uno.
- `smolagents` solo se importa en `agent/code_agent.py` (dentro del extra `agent`).

## Cómo verificar

```bash
CUDA_VISIBLE_DEVICES="" ARCA_RLM_BASE_MODEL=HuggingFaceTB/SmolLM2-135M-Instruct \
    uv run python -m agent.evaluate --agent code --bench agent/bench/tasks.jsonl --limit 2   # humo
```
