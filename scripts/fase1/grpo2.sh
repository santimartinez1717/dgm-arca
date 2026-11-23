#!/bin/bash
# GRPO 2 desde el SFT 3: 2048 tokens, recompensa por pasos, learning rate 2e-5 constante
# (4 veces el del GRPO 1; constante para que las dos etapas lo compartan) y pistas de nivel 2
# en irpf_rental y cash_on_cash (rlm/hints.py) los 250 primeros pasos; los 150 últimos sin
# pistas. Después, evaluación en test a 2048. ~80 s por paso: unas 9 h en total.
# Uso: nohup bash scripts/fase1/grpo2.sh > logs/fase1/grpo2.log 2>&1 &
# Si la sesión se corta, el mismo comando continúa desde el último checkpoint (cada 25 pasos).
set -e
cd ~/clusters/dgx/dgm-arca
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
OUT=rlm/weights/grpo2_lora
G="uv run python -m rlm.train_grpo --data rlm/data/train.jsonl --model Qwen/Qwen3-1.7B
   --init-adapter rlm/weights/sft3_lora --output $OUT --max-completion-length 2048
   --learning-rate 2e-5 --lr-scheduler constant --third-reward process --save-steps 25"

if [ ! -d "$OUT/checkpoint-250" ]; then
    echo "=== GRPO 2, etapa 1: con pistas, hasta el paso 250 ($(date +%H:%M))"
    last=$(ls -d $OUT/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1)
    $G --steps 250 --hint-families irpf_rental cash_on_cash --hint-share 1.0 --hint-level 2 \
       ${last:+--resume-from-checkpoint $last}
fi
echo "=== GRPO 2, etapa 2: sin pistas, hasta el paso 400 ($(date +%H:%M))"
last=$(ls -d $OUT/checkpoint-* | sort -t- -k2 -n | tail -1)
$G --steps 400 --resume-from-checkpoint "$last"

echo "=== Evaluación GRPO 2, 2048 tokens ($(date +%H:%M))"
uv run python -m rlm.evaluate --data rlm/data/test.jsonl --model Qwen/Qwen3-1.7B \
    --adapters grpo2=$OUT --max-new-tokens 2048 --out reports/fase1/eval_grpo2_17b_2048.json
echo "=== TODO TERMINADO ($(date +%H:%M))"
