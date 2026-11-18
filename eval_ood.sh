#!/bin/bash
# Evaluación fuera de distribución (rlm/data/test_ood.jsonl) a 2048 tokens: "¿SFT memoriza,
# RL generaliza?". Primero el par de la ronda 2 (SFT 3, GRPO 2), luego el de la ronda 1.
# Uso: nohup bash eval_ood.sh > eval_ood.log 2>&1 &
set -e
cd ~/clusters/dgx/dgm-arca
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
E="uv run python -m rlm.evaluate --data rlm/data/test_ood.jsonl --model Qwen/Qwen3-1.7B --max-new-tokens 2048"
for pair in sft3=rlm/weights/sft3_lora grpo2=rlm/weights/grpo2_lora \
            sft=rlm/weights/sft_lora grpo=rlm/weights/final_rlm_lora; do
    echo "=== OOD ${pair%%=*} ($(date +%H:%M))"
    $E --adapters "$pair" --out "reports/eval_ood_${pair%%=*}_2048.json"
done
echo "=== TODO TERMINADO ($(date +%H:%M))"
