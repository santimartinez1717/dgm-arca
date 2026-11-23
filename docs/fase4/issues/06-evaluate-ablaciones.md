# Fase 4 · `agent/evaluate.py`: métricas por cerebro, ablaciones y tool rota

**Responsable:** Kike · **Hito:** H3 · **Depende de:** la issue 05 (banco) y el agente (núcleo, H1/H2)

## Contexto

La interpretación vale un 30 % de la nota de la fase: "qué cerebro gana y por qué; en qué tareas
falla el agente; qué cambió con la memoria; cómo reaccionó ante una herramienta rota"
(`agent/README.md`). `agent/evaluate.py` ya mide la tasa de éxito, los pasos y los tokens por
cerebro. Hay que ampliarlo para contestar esas preguntas con datos.

## Qué hay que hacer

1. **Configuraciones.** `--configs` además de `--brains`. El agente expone estos interruptores en
   `ReActAgent(...)`; el núcleo los deja listos con estos nombres:
   - `full`: todo activado;
   - `no_auditor`: `audit=False`;
   - `no_playbook`: sin `find_levers` ni `what_if`;
   - `flat_memory`: `anchor_case_file=False`, sin expediente anclado, solo el historial.
2. **Tool rota.** Si la tarea trae `break_tool: "get_rent_reference"`, se registra una versión que
   lanza un error o se queda colgada más allá del timeout (`break_mode: error|timeout`). Se mide si
   el agente se recupera.
3. **Métricas** por cerebro, configuración y categoría:
   - tasa de éxito (`check` y `succeeded`);
   - pasos medios;
   - tokens medios;
   - uso de las `required_tools`;
   - tasa de rechazo del auditor;
   - abstención correcta en `impossible`.
   - Intervalo de Wilson en la tasa de éxito y **McNemar** entre cerebros. Ya lo usamos en la
     fase 1: reutiliza el código de `rlm/evaluate.py`.
4. **Salida.**
   - `reports/fase4/phase4_eval.json` con todas las trazas;
   - tabla Markdown `reports/fase4/phase4_eval.md` lista para el informe;
   - **5 trazas seleccionadas** (2 buenas, 2 malas, 1 de tool rota) en
     `reports/fase4/trazas/`.
5. **Ejecución.** Con la skill `lanzar-dgx` (una ejecución en GPU cada vez). El progreso va al
   log, una línea por tarea. Los resultados se registran en EXPERIMENTS.md con
   `registrar-experimento`.

## Criterios de aceptación

- Tests en CPU con un cerebro falso guionizado (lista de salidas predefinidas) que no cargan
  ningún modelo: `tests/test_agent_evaluate.py`.
- La tabla de cerebros × configuraciones está en EXPERIMENTS.md, con una lectura de qué gana y por
  qué.

## Cómo verificar

```bash
uv run pytest -q tests/test_agent_evaluate.py
uv run python -m agent.evaluate --bench agent/bench/tasks.jsonl --brains base rlm thinking \
    --configs full no_auditor no_playbook flat_memory      # en la DGX
```
