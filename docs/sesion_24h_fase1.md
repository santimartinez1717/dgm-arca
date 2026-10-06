# Sesión de 24 h (71 GiB): destilación, SFT, evaluación y GRPO

Guía para la sesión larga de la fase 1. Cada paso dice qué ejecutar, qué hace y cómo saber
que ha ido bien. Contexto y números en `EXPERIMENTS.md` (entradas del 2026-10-06).

Orden: comprobar la sesión → token → prueba de profesores → destilación → SFT → evaluación
→ prueba de memoria de GRPO → GRPO. Los procesos largos se lanzan con `nohup` y escriben su
progreso en un `.log`; para verlo, `tail -f <log>` (`Ctrl+C` sale sin pararlo).

## 0 · Antes de cerrar la sesión anterior

```bash
git push origin main          # sube los commits pendientes
```

## 1 · Comprobar la sesión

```bash
cd ~/clusters/dgx/dgm-arca
source smoke/dgx_env.sh
git pull
nvidia-smi -L                 # qué partición MIG toca (esperamos una de ~71 GiB)
nproc                         # CPUs de la sesión
echo "quedan $(( (SLURM_JOB_END_TIME - $(date +%s)) / 3600 )) h"
```

## 2 · Token de Hugging Face (una sola vez)

Hace falta para subir los adaptadores al Hub (la DGX no tiene copias de seguridad).

```bash
cp .env.example .env
nano .env                     # pon tu token en HF_TOKEN=... y BORRA la línea HF_HOME=./hf_cache
source smoke/dgx_env.sh       # vuelve a cargar el entorno con el token
```

Borrar `HF_HOME` es importante: `dgx_env.sh` carga el `.env`, y esa línea mandaría los
modelos a una carpeta nueva en vez de a la caché del clúster, donde ya están descargados.

## 3 · Prueba de profesores (~30-40 min en total)

Los mismos 20 problemas que las pruebas anteriores, con tope de 2048 tokens. Qwen3-4B con
lotes de 8 (16 GB cabían con lotes de 2; con 71 GiB, 8 deberían caber):

```bash
PYTHONUNBUFFERED=1 nohup uv run python -m rlm.distill --data rlm/data/train.jsonl \
    --teacher Qwen/Qwen3-4B --limit 20 --batch-size 8 \
    --output rlm/data/sft_traces_probe20_4b.jsonl > distill_probe_4b.log 2>&1 &
tail -f distill_probe_4b.log
```

Cuando termine (aparece `PEAK_GPU_GB=`), lo mismo con Qwen3-8B. La primera vez descarga
unos 16 GB:

```bash
PYTHONUNBUFFERED=1 nohup uv run python -m rlm.distill --data rlm/data/train.jsonl \
    --teacher Qwen/Qwen3-8B --limit 20 --batch-size 8 \
    --output rlm/data/sft_traces_probe20_8b.jsonl > distill_probe_8b.log 2>&1 &
tail -f distill_probe_8b.log
```

Si alguna da `OutOfMemoryError`: `mv` del log y repetir con `--batch-size 4 --resume`.

Comparar:

```bash
grep -E "batch 3/|ELAPSED|PEAK|acceptance" distill_probe_4b.log distill_probe_8b.log
cat rlm/data/sft_traces_probe20_4b.report.json rlm/data/sft_traces_probe20_8b.report.json
```

Elegimos el profesor que dé más **trazas aceptadas por hora** (aceptación ÷ minutos por
problema). Referencia del 4B en la MIG pequeña: 37,5 % con 1536 tokens.

## 4 · Destilación grande

Con el profesor y el lote elegidos. `--resume` desde el principio: si algo la corta, el mismo
comando continúa donde se quedó.

```bash
PYTHONUNBUFFERED=1 nohup uv run python -m rlm.distill --data rlm/data/train.jsonl \
    --teacher Qwen/Qwen3-<4B|8B> --limit 400 --batch-size <N> --resume \
    --output rlm/data/sft_traces.jsonl > distill.log 2>&1 &
tail -f distill.log
```

Objetivo: **al menos 1.000 trazas aceptadas**. Con 400 problemas × 4 muestras, eso pide un
62 % de aceptación. Si la prueba del paso 3 da menos, usar `--limit 800`.

## 5 · SFT (< 1 h)

```bash
PYTHONUNBUFFERED=1 nohup uv run python -m rlm.train_sft --data rlm/data/sft_traces.jsonl \
    --model Qwen/Qwen3-1.7B --output rlm/weights/sft_lora > sft.log 2>&1 &
tail -f sft.log
```

Va bien si la `loss` baja cada 10 pasos sin llegar a casi cero (eso sería memorizar).

## 6 · Evaluación tras el SFT (~30 min)

```bash
PYTHONUNBUFFERED=1 nohup uv run python -m rlm.evaluate --data rlm/data/test.jsonl \
    --model Qwen/Qwen3-1.7B --adapters sft=rlm/weights/sft_lora \
    --out reports/eval_sft_17b.json > eval_sft.log 2>&1 &
```

Comparar con la línea base (`reports/eval_base_17b.json`: 3,3 % pass@1, 0,7 % formato,
81 % cortadas).

## 7 · GRPO

Primero una prueba de memoria de 3 pasos (unos minutos):

```bash
PYTHONUNBUFFERED=1 uv run python -m rlm.train_grpo --data rlm/data/train.jsonl \
    --model Qwen/Qwen3-1.7B --init-adapter rlm/weights/sft_lora --steps 3 \
    --max-completion-length 1024 --output rlm/weights/grpo_memtest 2>&1 | tail -20
```

Si termina, el entrenamiento de verdad, con checkpoints cada 50 pasos:

```bash
PYTHONUNBUFFERED=1 nohup uv run python -m rlm.train_grpo --data rlm/data/train.jsonl \
    --model Qwen/Qwen3-1.7B --init-adapter rlm/weights/sft_lora --steps 400 \
    --max-completion-length 1024 --save-steps 50 \
    --output rlm/weights/final_rlm_lora > grpo.log 2>&1 &
```

Si la sesión se acaba antes: en la siguiente, el mismo comando con
`--resume-from-checkpoint rlm/weights/final_rlm_lora/checkpoint-XXX`.

## Después de cada paso

Apuntar el resultado en `EXPERIMENTS.md` (con Claude: skill `registrar-experimento`) y hacer
commit. Los pesos y las trazas no se versionan (`.gitignore`): los adaptadores se suben al
Hub con el token del paso 2.
