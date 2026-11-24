# Fase 4 · Cerrar el círculo: SFT del RLM con las trazas del agente

**Responsable:** Bernardo · **Hito:** H4 · **Depende de:**
- el agente funcionando (núcleo, H1/H2);
- el fine-tune de formato del RLM de Santiago;
- la primera medida del banco (issue 06).

## Contexto

Es un extra que el enunciado valora ("usar las trazas exitosas del agente como datos de SFT",
`agent/README.md`). Además responde con datos a la pregunta de la defensa: ¿ayuda entrenar el
cerebro? El RLM de la fase 1 se entrenó para razonar sin tools. Aquí lo entrenamos con trazas
del agente completo que funcionaron, para que aprenda el método: guardar datos, analizar, buscar
palancas, simularlas y citar. Diseño en `docs/fase4/diseno.md`.

## Qué hay que hacer

1. **Generador de tareas** (`agent/bench/generate_tasks.py`). Produce cientos de tareas
   sintéticas con el motor (`rlm/realestate_rules.py`, `agent/analysis.py`), con las mismas
   categorías que el banco, la respuesta esperada y su `check`.
   - **Nunca** reutiliza las tareas de `agent/bench/tasks.jsonl`, que son el test.
   - Para comprobarlo, un test de que no hay solapamiento (mismos pisos y cifras).
2. **Recogida de trazas.** Hay que lanzar el agente sobre esas tareas con el mejor cerebro
   (probablemente `thinking`; lo dirá la issue 06) y quedarse solo con las trazas que:
   - pasan el `check`;
   - pasan el auditor a la primera;
   - no superan la mediana de pasos.
   - Reportad la tasa de aceptación, como en la destilación de la fase 1.
3. **Conversión a SFT.** Las trazas pasan al formato de `rlm/train_sft.py`: mensajes con
   tool calls y observaciones, con pérdida solo en los turnos del asistente. Se pasa
   `scrub_leaks`.
4. **Entrenamiento** en la DGX con la skill `lanzar-dgx`, partiendo del adaptador con el formato
   arreglado. Los parámetros de memoria están en `CLAUDE.md` (batch 2, grad-accum 8).
5. **Nueva medida** de `brain=rlm` en el banco con `agent/evaluate.py`: antes y después, con
   McNemar. Registro en EXPERIMENTS.md.

## Criterios de aceptación

- El generador es reproducible (semilla fija) y tiene test de no solapamiento con el banco.
- La tasa de aceptación de trazas y el tamaño del dataset están en EXPERIMENTS.md.
- La tabla de `brain=rlm` antes y después del SFT está en EXPERIMENTS.md, con su lectura.
  - Si no mejora, también vale: se explica por qué.

## Cómo verificar

```bash
uv run python -m agent.bench.generate_tasks --n 300 --seed 0 --out agent/bench/train_tasks.jsonl
uv run pytest -q tests/test_generate_tasks.py
```
