# Plan de la fase 1 — Umbral

Qué hay hecho, qué falta, en qué orden y quién lo hace. Los comandos se lanzan desde la raíz
del repositorio. En la DGX, primero `cd ~/clusters/dgx/dgm-arca && source smoke/dgx_env.sh`.

## 0. Antes de nada: la propuesta

1. Rellenad los correos que faltan en `docs/propuesta.md` y leed la propuesta los tres. En la
   defensa os pueden preguntar a cualquiera.
2. Haced push al repositorio del equipo y enviad al profesor el enlace a `docs/propuesta.md`.
3. **La fase 1 no empieza oficialmente hasta que aprueben la propuesta.** Lo que ya está
   programado es la base que la hace creíble: el generador y el verificador existen y tienen
   tests. Si el profesor pide cambios en las reglas o las familias, se tocan
   `realestate_rules.py` y `realestate_problems.py`, y lo demás no cambia.

## 1. Qué hay hecho (y probado en CPU)

| Pieza | Fichero | Estado |
|---|---|---|
| Motor de reglas con fuentes | `rlm/realestate_rules.py` | Hecho, 29 tests con casos resueltos a mano |
| Generador: 6 familias + 2 fuera de distribución | `rlm/realestate_problems.py` | Hecho; dataset en `rlm/data/` |
| Verificador del dominio (formato español, tolerancia por fila) | `rlm/verifier.py` (`EuroVerifier`) | Hecho, con casos límite |
| Recompensas: exactitud en € y "desglose trazable" | `rlm/realestate_rewards.py` | Hecho, con tests |
| GRPO con TRL: 3 recompensas, pesos y control GSM8K | `rlm/train_grpo.py` | Hecho |
| Paso de GRPO a mano | `rlm/grpo_step.py` | Hecho, tests en verde. **Los tres tenéis que saber explicarlo** |
| Destilación con informe de aceptación por familia | `rlm/distill.py` | Hecho |
| Evaluación: pass@1 por familia, gráficas y curvas | `rlm/evaluate.py` | Hecho |
| Verificador registrado para `/reasoning` | `rlm/inference.py` (`euro`) | Hecho |
| Hoja de auditoría de 50 problemas de test | `rlm/data/test_audit.csv` | **Por rellenar** |

## 2. Lo que falta, en orden

### Semana 1 (sin GPU, en paralelo)

- **Auditoría (los tres, unos 17 problemas cada uno).** En `rlm/data/test_audit.csv`, resolved
  cada problema a mano y marcad `enunciado_resoluble` y `respuesta_correcta`, firmando en
  `revisado_por`. Si alguno falla, es un error del generador: se corrige y se regenera.
- **Paráfrasis (1 persona).** Ahora hay 2-3 plantillas por familia, y el profesor mirará la
  diversidad léxica. Opciones:
  - escribir más plantillas en `render`;
  - pasar los enunciados de train por Qwen3-4B pidiéndole que los reescriba sin cambiar
    ningún número, y comprobar con un script que siguen estando todos los números del
    original.

  Anotad cuántas plantillas quedan.
- **Leer el código de `grpo_step.py` (los tres).** Ventajas, ratio, recorte y KL. Es pregunta
  segura en la defensa.

### Primera sesión en la DGX

```bash
uv sync --extra train
uv run pytest                   # todo verde
uv run arca-check-gpu
uv run arca-smoke               # 10-15 min: GRPO de prueba sobre GSM8K
```

### Paso 1 · Línea base (unos 30 min)

```bash
uv run python -m rlm.evaluate --data rlm/data/test.jsonl --model Qwen/Qwen3-0.6B \
    --adapters base=none --out reports/eval_base_06b.json
uv run python -m rlm.evaluate --data rlm/data/test.jsonl --model Qwen/Qwen3-1.7B \
    --adapters base=none --out reports/eval_base_17b.json
```

Con esto elegís el alumno. Si el de 1.7B ya acierta más del 60 %, el dominio le resulta fácil:
subid la dificultad o quedaos con el de 0.6B, donde hay margen para mejorar.

### Paso 2 · Destilación (varias horas; lanzadla con `nohup`)

```bash
nohup uv run python -m rlm.distill --data rlm/data/train.jsonl --teacher Qwen/Qwen3-4B \
    --samples 4 --limit 800 --output rlm/data/sft_traces.jsonl > distill.log 2>&1 &
```

Probad antes con `--limit 20`, para medir la velocidad y ajustar `--batch-size` y
`--max-new-tokens`. La tasa de aceptación por familia sale en `sft_traces.report.json` y va a
`EXPERIMENTS.md`: es la primera medida de qué familias son difíciles. Si alguna familia baja
del 20 %, pedid más muestras solo de esa familia.

### Paso 3 · SFT (menos de 1 hora)

```bash
uv run python -m rlm.train_sft --data rlm/data/sft_traces.jsonl --model Qwen/Qwen3-1.7B \
    --output rlm/weights/sft_lora
```

### Paso 4 · GRPO (varias horas; checkpoints cada 50 pasos)

```bash
nohup uv run python -m rlm.train_grpo --data rlm/data/train.jsonl --model Qwen/Qwen3-1.7B \
    --init-adapter rlm/weights/sft_lora --steps 400 --max-completion-length 1024 \
    --output rlm/weights/final_rlm_lora > grpo.log 2>&1 &
```

Si la sesión de 24 h se corta, se reanuda con
`--resume-from-checkpoint rlm/weights/final_rlm_lora/checkpoint-XXX`. Al terminar, subid el
adaptador a Hugging Face Hub: la DGX no tiene copias de seguridad.

### Paso 5 · Evaluación y curvas

```bash
uv run python -m rlm.evaluate --data rlm/data/test.jsonl --model Qwen/Qwen3-1.7B \
    --adapters base=none sft=rlm/weights/sft_lora grpo=rlm/weights/final_rlm_lora
uv run python -m rlm.evaluate --data rlm/data/test_ood.jsonl --model Qwen/Qwen3-1.7B \
    --adapters base=none sft=rlm/weights/sft_lora grpo=rlm/weights/final_rlm_lora \
    --out reports/phase1_ood.json
uv run python -m rlm.evaluate --history rlm/weights/final_rlm_lora/checkpoint-400/trainer_state.json
```

### Paso 6 · Análisis (lo que más puntúa)

- **Cinco fallos concretos**, sacados de `reports/phase1_eval.json`. Para cada uno: ¿falló la
  regla (por ejemplo, usó el precio en vez del valor de referencia) o la cuenta?
- **"SFT memoriza, RL generaliza":** comparad el pass@1 en `test` y en `test_ood` para SFT y
  para GRPO.
- **Ablaciones**, una cada vez, con 150-200 pasos cada una:
  - recompensa de desglose condicionada frente a no condicionada (`--ungated-breakdown`);
  - con KL frente a sin KL (`--beta 0.04`);
  - con las reglas en el enunciado (`--with-rules` en el generador).
- **Reward hacking:** buscad en `completions/` razonamientos que enumeren muchas cifras para
  acertar alguna de las intermedias.

### Paso 7 · El endpoint

En el `.env`: `ARCA_RLM_ADAPTER=rlm/weights/final_rlm_lora`, `ARCA_RLM_VERIFIER=euro`,
`ARCA_TEAM` y `ARCA_DOMAIN`. Después, `uv run arca-api` y probad `POST /reasoning` desde
`/docs` con un problema de `test.jsonl` y su `expected_answer`.

## 3. Reparto propuesto

| Persona | Responsabilidad principal | Además |
|---|---|---|
| Santiago | Datos: generador, paráfrasis, auditoría, tabla de ramas | Endpoint `/reasoning` |
| Bernardo | Destilación y SFT en la DGX, tasa de aceptación | Subir los adaptadores a HF Hub |
| Enrique | GRPO: entrenamiento, ablaciones y curvas | `grpo_step.py` en la defensa |

El análisis de fallos y `EXPERIMENTS.md` son de los tres. Cada uno escribe las entradas de lo
que lanza, con fecha.

## 4. Lista de comprobación de los mínimos del enunciado

- [x] Dataset verificable propio (cientos de problemas) y verificador determinista con tests
- [ ] Destilación con tasa de aceptación reportada
- [ ] SFT con LoRA sobre las trazas verificadas
- [x] GRPO con tres recompensas (código listo) · [ ] entrenado
- [x] Paso de GRPO a mano con tests en verde
- [ ] pass@1 de base, SFT y GRPO; curvas de recompensa y longitud; cinco fallos analizados
- [ ] `EXPERIMENTS.md` al día y `/reasoning` listo en `/health`
