#!/bin/bash
# Segundo SFT con las trazas nuevas (con clave reescritas y obra nueva), su evaluación y el
# muestreo de las familias difíciles. Uso: nohup bash sft2.sh > sft2.log 2>&1 &
set -e
cd ~/clusters/dgx/dgm-arca
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

DATA=""
for f in sft_traces sft_traces_hard sft_traces_cash sft_traces_irpf sft_traces_obra_nueva \
         sft_traces_priv_irpf_pilot.rewritten sft_traces_priv_irpf_rental.rewritten \
         sft_traces_priv_legal_rent.rewritten sft_traces_priv_cash_on_cash.rewritten; do
    [ -f "rlm/data/$f.jsonl" ] && DATA="$DATA rlm/data/$f.jsonl"
done
echo "=== SFT 2 con:$DATA"
uv run python -m rlm.train_sft --data $DATA --model Qwen/Qwen3-1.7B \
    --max-per-problem 3 --max-per-family 150 --max-length 3328 --batch-size 2 --grad-accum 8 \
    --output rlm/weights/sft2_lora

echo "=== Evaluación SFT 2, 1024 tokens"
uv run python -m rlm.evaluate --data rlm/data/test.jsonl --model Qwen/Qwen3-1.7B \
    --adapters sft2=rlm/weights/sft2_lora --max-new-tokens 1024 --out reports/eval_sft2_17b.json

echo "=== Muestreo de las familias difíciles (k=8)"
uv run python -m rlm.sample_check --adapter rlm/weights/sft2_lora \
    --families irpf_rental legal_rent cash_on_cash --n-per-family 12 --out reports/sample_check_sft2.json
uv run python -m rlm.sample_check --adapter rlm/weights/sft2_lora \
    --families acquisition_cost --branch new_build=True --n-per-family 10 \
    --out reports/sample_check_sft2_obra_nueva.json
echo "=== TODO TERMINADO"
