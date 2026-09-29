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

---

### 2026-09-29 · Fase 1 · Smoke test en la DGX (GRPO sobre GSM8K)

**Qué queríamos saber.** Si el bucle de GRPO con TRL funciona en la partición MIG de la DGX
(H200 1g.18gb, 17,2 GB), cuánto tarda y cuánta memoria usa, antes de lanzar nada del dominio.

**Qué hicimos.** `nohup uv run arca-smoke > smoke.log 2>&1 &`: Qwen3-0.6B con LoRA de rango
16 (10,1 M parámetros entrenables, un 1,67 %), 40 pasos, grupo de 8 generaciones, 384 tokens
como máximo, lr 1e-5, 256 problemas de GSM8K, semilla 0.

**Qué pasó.** Termina sin errores en 11,9 min (~18 s por paso), con un pico de 7,3 GB de GPU.
Adaptador guardado en `rlm/weights/smoke_lora/`. Cada paso usa un único problema, así que la
recompensa por paso es muy ruidosa; comparamos medias de 10 pasos:

| Métrica (recompensa máx. 2) | Pasos 1-10 | Pasos 31-40 |
|---|---|---|
| Recompensa total | 0,29 | 0,69 |
| Formato | 0,08 | 0,41 |
| Exactitud | 0,21 | 0,28 |
| Fracción truncada a 384 tokens | 0,76 | 0,59 |

**Qué concluimos.**
- El bucle funciona: sube sobre todo la recompensa de formato, y lo hace a la vez que baja
  la fracción truncada. Casi todo el formato perdido viene de respuestas cortadas antes de
  `</think>`, no de que el modelo ignore las etiquetas.
- La tabla "first step / last step" del resumen del smoke engaña, porque compara dos pasos de
  un solo problema cada uno. En nuestros informes usaremos medias móviles.
- Consecuencia para el dominio: la longitud máxima es el hiperparámetro crítico. Qwen3 en
  modo thinking se extiende mucho; en la línea base mediremos la fracción truncada junto al
  pass@1, y por eso GRPO usará 1024 tokens y un arranque en frío con trazas compactas.
- Margen de memoria: 7,3 de 17,2 GB con 0,6B y 384 tokens. Con 1,7B y 1024 tokens no
  cabe dar nada por hecho: se medirá con una prueba corta antes de lanzarlo.
- Aviso en el log: no hay `HF_TOKEN` (no existe `.env`). Hará falta para subir adaptadores
  al Hub.
