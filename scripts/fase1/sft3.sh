#!/bin/bash
# SFT 3 cuando termine scripts/fase1/sesion3.sh: todas las trazas (las del SFT 2 + cash_on_cash con clave),
# tope de 200 por familia para que entren casi todas las reescritas. Después, evaluación a 2048
# y muestreo con pistas (¿dará señal el GRPO 2 en irpf y cash?).
# Uso: nohup bash scripts/fase1/sft3.sh > logs/fase1/sft3.log 2>&1 &
cd ~/clusters/dgx/dgm-arca
while ps -eo args | grep -v grep | grep -q "bash scripts/fase1/sesion3.sh"; do sleep 30; done
set -e
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

DATA=""
for f in sft_traces sft_traces_hard sft_traces_cash sft_traces_irpf sft_traces_obra_nueva \
         sft_traces_priv_irpf_pilot.rewritten sft_traces_priv_irpf_rental.rewritten \
         sft_traces_priv_legal_rent.rewritten sft_traces_priv_cash_on_cash.rewritten; do
    [ -f "rlm/data/$f.jsonl" ] && DATA="$DATA rlm/data/$f.jsonl"
done
echo "=== SFT 3 ($(date +%H:%M)) con:$DATA"
uv run python -m rlm.train_sft --data $DATA --model Qwen/Qwen3-1.7B \
    --max-per-problem 3 --max-per-family 200 --max-length 3328 --batch-size 2 --grad-accum 8 \
    --output rlm/weights/sft3_lora

echo "=== Evaluación SFT 3, 2048 tokens ($(date +%H:%M))"
uv run python -m rlm.evaluate --data rlm/data/test.jsonl --model Qwen/Qwen3-1.7B \
    --adapters sft3=rlm/weights/sft3_lora --max-new-tokens 2048 --out reports/fase1/eval_sft3_17b_2048.json

for level in 0 2; do
    echo "=== Muestreo SFT 3, pista de nivel $level ($(date +%H:%M))"
    uv run python -m rlm.sample_check --adapter rlm/weights/sft3_lora \
        --families irpf_rental cash_on_cash --n-per-family 8 --hint-level $level \
        --out reports/fase1/sample_check_sft3_pista$level.json
done
echo "=== TODO TERMINADO ($(date +%H:%M))"
