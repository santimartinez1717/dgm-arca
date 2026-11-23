#!/bin/bash
# Evaluación tras GRPO. Espera a que termine el proceso cuyo PID se pasa como argumento.
# Orden de prioridad: GRPO final a 1024 y 2048; luego la ablación al mismo número de pasos
# (checkpoint 200 con y sin recompensa del dominio) a 1024.
set -e
cd ~/clusters/dgx/dgm-arca
while kill -0 "$1" 2>/dev/null; do sleep 60; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
E="uv run python -m rlm.evaluate --data rlm/data/test.jsonl --model Qwen/Qwen3-1.7B"
echo "=== GRPO final, 1024 tokens"; $E --adapters grpo=rlm/weights/final_rlm_lora --max-new-tokens 1024 --out reports/fase1/eval_grpo_17b.json
echo "=== GRPO final, 2048 tokens"; $E --adapters grpo=rlm/weights/final_rlm_lora --max-new-tokens 2048 --out reports/fase1/eval_grpo_17b_2048.json
echo "=== Ablación: paso 200 con dominio, 1024"; $E --adapters grpo200=rlm/weights/final_rlm_lora/checkpoint-200 --max-new-tokens 1024 --out reports/fase1/eval_grpo200_dominio.json
echo "=== Ablación: paso 200 sin dominio, 1024"; $E --adapters grpo200=rlm/weights/grpo_sin_dominio_lora/checkpoint-200 --max-new-tokens 1024 --out reports/fase1/eval_grpo200_sin_dominio.json
