#!/bin/bash
# Destilación con información privilegiada para los problemas que el profesor no resolvió solo,
# más trazas normales de obra nueva. Cada tanda con clave va seguida de su reescritura.
# Uso: nohup bash scripts/fase1/distill_priv.sh > logs/fase1/distill_priv.log 2>&1 &
# Si se corta, el mismo comando continúa: las destilaciones usan --resume.
set -e
cd ~/clusters/dgx/dgm-arca
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

OLD="rlm/data/sft_traces.jsonl rlm/data/sft_traces_hard.jsonl rlm/data/sft_traces_cash.jsonl rlm/data/sft_traces_irpf.jsonl"
D="uv run python -m rlm.distill --data rlm/data/train.jsonl --teacher Qwen/Qwen3-4B --batch-size 2 --resume"

privileged() {  # familia, tokens
    out=rlm/data/sft_traces_priv_$1.jsonl
    echo "=== Con clave: $1 ($2 tokens)"
    $D --families "$1" --privileged --max-new-tokens "$2" --only-unsolved $OLD \
        --exclude rlm/data/sft_traces_priv_irpf_pilot.jsonl --output "$out"
    echo "=== Reescritura: $1"
    uv run python -m rlm.rewrite_traces --input "$out" --output "${out%.jsonl}.rewritten.jsonl"
}

privileged irpf_rental 2048

echo "=== Obra nueva, sin clave (el profesor la resuelve con la hoja de reglas)"
$D --families acquisition_cost --branch new_build=True --limit 40 --exclude $OLD \
    --output rlm/data/sft_traces_obra_nueva.jsonl

privileged legal_rent 2048
privileged cash_on_cash 3072
echo "=== TODO TERMINADO"
