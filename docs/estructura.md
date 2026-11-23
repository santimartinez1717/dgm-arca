# Estructura del repositorio

Dónde está cada cosa. Los nombres de los módulos de `rlm/` y `tool_use/` los fija la plantilla
del profesor (la API los importa por esos nombres), así que no se mueven: aquí se agrupan por
función.

## Raíz

| Carpeta o fichero | Qué hay |
|---|---|
| `EXPERIMENTS.md` | Una entrada por cada cosa lanzada o decidida |
| `rlm/` | Fase 1: razonamiento (dominio, destilación, SFT, GRPO, evaluación) |
| `tool_use/` | Fase 2: herramientas |
| `rag/`, `agent/` | Fases 3 y 4 |
| `api/` | La API de corrección; `shared_model.py` carga una sola copia del modelo base para todas las fases |
| `scripts/fase1/`, `scripts/fase2/` | Los lanzamientos largos en la DGX (destilación, SFT, GRPO, bancos) |
| `scripts/serve_dgx.sh` | Sirve la API en la GPU de la DGX ([servir_api.md](servir_api.md)) |
| `reports/fase1/`, `reports/fase2/` | Resultados: evaluaciones, muestreos, bancos (las `.png` no van a git) |
| `logs/` | Logs de los procesos (fuera de git) |
| `smoke/` | Prueba de humo y entorno de la DGX (del profesor) |
| `tests/` | `uv run pytest -q` |

## `docs/`

| Dónde | Qué |
|---|---|
| raíz de `docs/` | Lo del profesor (enunciado, rúbrica, `dgx.md`, `fase1_plan.md`, plantillas, temas, `github.md`, `datasets.md`), nuestra propuesta (`propuesta.md`, en la ruta que pide la plantilla, y `propuesta_investigacion.md`), `servir_api.md` y este fichero |
| `docs/fase1/` | Análisis de fallos del modelo, guía de la sesión de 24 h |
| `docs/fase2/` | Diseño de la fase 2 y su investigación previa |
| `docs/investigacion/` | El RDL 29/2026 leído en el BOE, el informe de mercado y sus notas |

## `rlm/` (fase 1)

| Grupo | Ficheros |
|---|---|
| Dominio | `realestate_rules.py` (única fuente de verdad), `realestate_problems.py` y `generate_problems.py` (generan los problemas), `realestate_rewards.py`, `rewards.py`, `verifier.py` |
| Datos y destilación | `data.py`, `distill.py` (trazas del profesor), `rewrite_traces.py` (reescritura sin la clave), `hints.py` (pistas para GRPO) |
| Entrenamiento | `train_sft.py`, `train_grpo.py`, `grpo_step.py` (un paso de GRPO a mano) |
| Evaluación | `evaluate.py` (pass@1 y curvas), `sample_check.py` (¿habrá señal para GRPO?), `generation.py`, `eval_mlx.py` |
| Servir y publicar | `inference.py` (detrás de `/reasoning`), `upload_hub.py` |
| Datos y pesos | `data/` (problemas y trazas), `weights/` (adaptadores, fuera de git; los finales en Hugging Face) |

## `tool_use/` (fase 2)

| Grupo | Ficheros |
|---|---|
| El bucle | `executor.py` (los cinco pasos; detrás de `/tools`), `parser.py`, `registry.py` |
| Las herramientas | `tools.py` (registro), `calculators.py` (el motor de reglas de la fase 1), `public_data.py` (Catastro, tipos, alquileres), `portfolio.py` (cartera), `regions.py`, `itp_rates.py` |
| Datos | `build_data.py` (genera los ficheros de datos públicos), `bench/` (casos de prueba) |
| Evaluación | `evaluate.py` (selección y argumentos), `phase1_compare.py` (con y sin herramientas sobre el test de la fase 1) |
