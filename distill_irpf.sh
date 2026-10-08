#!/bin/bash
# Tanda 3: irpf_rental con 3072 tokens y la hoja con orden fijo de cálculo.
# Espera a que termine distill_hard.sh (PID como primer argumento) para no compartir la GPU.
set -e
cd ~/clusters/dgx/dgm-arca
while kill -0 "$1" 2>/dev/null; do sleep 60; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
echo "=== Tanda 3: irpf_rental, 20 problemas nuevos, 3072 tokens"
uv run python -m rlm.distill --data rlm/data/train.jsonl --teacher Qwen/Qwen3-4B \
    --families irpf_rental --limit 20 --batch-size 2 --max-new-tokens 3072 \
    --exclude rlm/data/sft_traces.jsonl rlm/data/sft_traces_hard.jsonl --resume \
    --output rlm/data/sft_traces_irpf.jsonl
