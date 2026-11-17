#!/bin/bash
# Evalúa el SFT 2 con 2048 tokens cuando termine sesion3.sh (para compararlo con el 37,7 % del
# SFT 1 a 2048). Uso: nohup bash eval_sft2_2048.sh > eval_sft2_2048.log 2>&1 &
cd ~/clusters/dgx/dgm-arca
while ps -eo args | grep -v grep | grep -q "bash sesion3.sh"; do sleep 30; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
echo "=== Evaluación SFT 2, 2048 tokens ($(date +%H:%M))"
uv run python -m rlm.evaluate --data rlm/data/test.jsonl --model Qwen/Qwen3-1.7B \
    --adapters sft2=rlm/weights/sft2_lora --max-new-tokens 2048 --out reports/eval_sft2_17b_2048.json
echo "=== TODO TERMINADO ($(date +%H:%M))"
