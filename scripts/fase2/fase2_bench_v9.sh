# Bench v9: current code (shared base model, no cuDNN attention), base model vs the phase 1
# GRPO 2 adapter. Same 40 cases as v8.
cd ~/clusters/dgx/dgm-arca-fase2
while ps -eo args | grep -v grep | grep -qE "python -m (rlm|tool_use)\.|arca-api"; do sleep 30; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
echo "=== Banco: Qwen3-1.7B base, sin thinking, $(git log --oneline -1 | cut -c1-7) ($(date +%H:%M))"
uv run python -m tool_use.evaluate --out reports/fase2/phase2_bench_base_v9.json
echo "=== Banco: Qwen3-1.7B + grpo2_lora, sin thinking ($(date +%H:%M))"
uv run python -m tool_use.evaluate --adapter rlm/weights/grpo2_lora --out reports/fase2/phase2_bench_grpo2_v9.json
echo "=== TODO TERMINADO ($(date +%H:%M))"
