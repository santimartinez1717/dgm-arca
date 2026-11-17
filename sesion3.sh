#!/bin/bash
# Próxima sesión de la ronda 2: el muestreo del SFT 2 que no cupo el 17/11 y la destilación con
# clave de cash_on_cash (+ reescritura). Uso: nohup bash sesion3.sh > sesion3.log 2>&1 &
# La destilación usa --resume: si se corta, el mismo comando continúa.
set -e
cd ~/clusters/dgx/dgm-arca
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

echo "=== Muestreo del SFT 2 (k=8)"
uv run python -m rlm.sample_check --adapter rlm/weights/sft2_lora \
    --families irpf_rental legal_rent cash_on_cash --n-per-family 8 --out reports/sample_check_sft2.json
uv run python -m rlm.sample_check --adapter rlm/weights/sft2_lora \
    --families acquisition_cost --branch new_build=True --n-per-family 6 \
    --out reports/sample_check_sft2_obra_nueva.json

OLD="rlm/data/sft_traces.jsonl rlm/data/sft_traces_hard.jsonl rlm/data/sft_traces_cash.jsonl rlm/data/sft_traces_irpf.jsonl"
out=rlm/data/sft_traces_priv_cash_on_cash.jsonl
echo "=== Con clave: cash_on_cash (3072 tokens)"
uv run python -m rlm.distill --data rlm/data/train.jsonl --teacher Qwen/Qwen3-4B --batch-size 2 \
    --resume --families cash_on_cash --privileged --max-new-tokens 3072 --only-unsolved $OLD \
    --exclude rlm/data/sft_traces_priv_irpf_pilot.jsonl --output "$out"
echo "=== Reescritura: cash_on_cash"
uv run python -m rlm.rewrite_traces --input "$out" --output "${out%.jsonl}.rewritten.jsonl"
echo "=== TODO TERMINADO"
