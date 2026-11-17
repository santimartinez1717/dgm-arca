#!/bin/bash
# ¿Dan señal las pistas? Muestreo del SFT 2 en irpf_rental y cash_on_cash con pista de nivel 1 y 2,
# cuando termine la evaluación a 2048. Uso: nohup bash pistas_check.sh > pistas_check.log 2>&1 &
cd ~/clusters/dgx/dgm-arca
while ps -eo args | grep -v grep | grep -qE "bash (sesion3|eval_sft2_2048).sh"; do sleep 30; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
for level in 2 1; do
    echo "=== Pista de nivel $level ($(date +%H:%M))"
    uv run python -m rlm.sample_check --adapter rlm/weights/sft2_lora \
        --families irpf_rental cash_on_cash --n-per-family 8 --hint-level $level \
        --out reports/sample_check_sft2_pista$level.json
done
echo "=== TODO TERMINADO ($(date +%H:%M))"
