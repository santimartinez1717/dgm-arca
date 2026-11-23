#!/bin/bash
# Evaluación tras el SFT: SFT a 1024 y 2048 tokens, y base a 2048 para comparar.
set -e
cd ~/clusters/dgx/dgm-arca
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
E="uv run python -m rlm.evaluate --data rlm/data/test.jsonl --model Qwen/Qwen3-1.7B"
echo "=== SFT, 1024 tokens";  $E --adapters sft=rlm/weights/sft_lora --max-new-tokens 1024 --out reports/fase1/eval_sft_17b.json
echo "=== SFT, 2048 tokens";  $E --adapters sft=rlm/weights/sft_lora --max-new-tokens 2048 --out reports/fase1/eval_sft_17b_2048.json
echo "=== Base, 2048 tokens"; $E --adapters base=none --max-new-tokens 2048 --out reports/fase1/eval_base_17b_2048.json
