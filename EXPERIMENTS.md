# EXPERIMENTS.md — cuaderno de experimentos de Umbral

Una entrada cada vez que lanzamos algo o tomamos una decisión, con fecha y de la más antigua a
la más reciente. Formato en [`docs/EXPERIMENTS_plantilla.md`](docs/EXPERIMENTS_plantilla.md).

---

### 2026-09-29 · Fase 1 · Primera versión del dataset verificable

**Qué queríamos saber.** Si el generador cubre todas las ramas de las reglas con una
frecuencia razonable, y si hay fugas de la respuesta en el enunciado o solapamiento entre
particiones.

**Qué hicimos.** `uv run python -m rlm.realestate_problems --out-dir rlm/data` (semilla 0):
- 400 problemas por familia en train y 50 por familia en test, sobre seis familias;
- 75 por familia fuera de distribución, sobre dos composiciones de reglas;
- deduplicación por huella de parámetros, compartida entre las tres particiones.

**Qué pasó.** 2.400 / 300 / 150 problemas, sin solapamiento (hay un test que lo comprueba).
Cobertura de ramas en train (`rlm/data/dataset_stats.json`):

| Familia | Rama | Reparto |
|---|---|---|
| `acquisition_cost` | base imponible | precio 203 · valor de referencia 197 |
| `acquisition_cost` | tipo de vivienda | usada 319 · obra nueva 81 |
| `legal_rent` | regla que limita | renta anterior 126 · sin zona 74 · índice 79 · zona sin tope 61 · mercado por debajo 60 |
| `legal_rent` | gran tenedor | sí 99 · no 301 |
| `irpf_rental` | reducción | 50 %: 143 · 70 %: 51 · 90 %: 41 · 60 %: 39 · rendimiento negativo (sin reducción): 126 |
| `irpf_rental` | límite intereses + reparaciones activo | 33 |
| `cash_on_cash` | flujo de caja negativo | 115 |
| `net_yield` | con meses vacíos | 268 |

Una fuga en train y otra en test. La primera comprobación, que buscaba el número sin unidad,
daba cinco; eran coincidencias de enteros como "2" o "5" que aparecen en cualquier enunciado.
Ahora buscamos la cifra con su unidad, tal como la escribiría el enunciado (`2,45 %`).

**Qué concluimos.**
- Ninguna rama pasa del 36 % de su familia. La reducción del 90 % salía en el 6,5 % de los
  problemas y subimos la probabilidad de "renta rebajada más de un 5 %" de 0,35 a 0,55; ahora
  sale en el 10 %.
- **Pendiente:** solo hay 2-3 plantillas por familia. Antes de destilar haremos una pasada de
  paráfrasis con el profesor, para que el modelo no aprenda la plantilla en vez de la tarea.
- Auditoría manual: 50 problemas de test repartidos por familias en
  `rlm/data/test_audit.csv`. Cada uno lo firma quien lo revisa.

---

### 2026-09-29 · Fase 1 · Prueba de todo el pipeline en CPU

**Qué queríamos saber.** Si generación, destilación, SFT, GRPO con las tres recompensas y
evaluación funcionan juntos antes de gastar horas de GPU.

**Qué hicimos.** Con `HuggingFaceTB/SmolLM2-135M-Instruct` en un Mac, sobre 3 problemas:
- `distill` con 2 muestras y 16 tokens;
- `train_sft`, 1 época;
- `train_grpo`, 1 paso con 2 generaciones y un 30 % de control GSM8K;
- `evaluate` y `evaluate --history`.

**Qué pasó.** Todo termina y guarda sus salidas. Las tres recompensas aparecen en el registro
de TRL (`rewards/format_reward`, `rewards/euro_accuracy_reward`, `rewards/domain_reward`). La
exactitud es 0, lo esperable con 135M parámetros y 16 tokens.

Encontramos un fallo solo de Mac: sin CUDA, `accelerate` elegía la GPU de Apple (MPS) y la
generación de TRL mezclaba tensores de MPS y CPU. Lo arreglamos con `use_cpu` cuando no hay
CUDA. En la DGX no aplica.

**Qué concluimos.** El código está listo para la DGX. Lo siguiente es el smoke test y la
destilación con Qwen3-4B.
