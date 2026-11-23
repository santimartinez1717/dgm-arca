#!/bin/bash
# Pasada extra de destilación solo con las familias difíciles, con problemas nuevos.
# Uso: nohup bash scripts/fase1/distill_hard.sh > logs/fase1/distill_hard.log 2>&1 &
# Si se corta, el mismo comando continúa donde se quedó (--resume en las dos tandas).
set -e
cd ~/clusters/dgx/dgm-arca
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1

echo "=== Tanda 1: legal_rent + irpf_rental, 100 problemas nuevos, 2048 tokens"
uv run python -m rlm.distill --data rlm/data/train.jsonl --teacher Qwen/Qwen3-4B \
    --families legal_rent irpf_rental --limit 100 --batch-size 2 \
    --exclude rlm/data/sft_traces.jsonl --resume \
    --output rlm/data/sft_traces_hard.jsonl

echo "=== Tanda 2: cash_on_cash, 30 problemas nuevos, 3072 tokens"
uv run python -m rlm.distill --data rlm/data/train.jsonl --teacher Qwen/Qwen3-4B \
    --families cash_on_cash --limit 30 --batch-size 2 --max-new-tokens 3072 \
    --exclude rlm/data/sft_traces.jsonl --resume \
    --output rlm/data/sft_traces_cash.jsonl
