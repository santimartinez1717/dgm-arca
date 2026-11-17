# Phase 2 bench on the GPU, in order of importance. Waits for the phase 1 chain to finish.
# Each run saves after every case, so a run cut by the end of the session keeps its rows.
cd ~/clusters/dgx/dgm-arca-fase2
while ps -eo args | grep -v grep | grep -qE "bash (sft3|sesion3)\.sh|python -m rlm\."; do sleep 30; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
ADAPTER=/home/202201278/clusters/dgx/dgm-arca/rlm/weights/final_rlm_lora

echo "=== Banco: Qwen3-1.7B base, sin thinking ($(date +%H:%M))"
uv run python -m tool_use.evaluate --out reports/phase2_bench_base.json

echo "=== Banco: Qwen3-1.7B + GRPO fase 1, sin thinking ($(date +%H:%M))"
uv run python -m tool_use.evaluate --adapter "$ADAPTER" --out reports/phase2_bench_grpo.json

echo "=== Banco: Qwen3-1.7B base, con thinking ($(date +%H:%M))"
uv run python -m tool_use.evaluate --thinking --out reports/phase2_bench_base_thinking.json

echo "=== TODO TERMINADO ($(date +%H:%M))"

# After the fixes to region, zero loan fields and the system prompt (same model as the first run).
echo "=== Banco: Qwen3-1.7B base, sin thinking, tras los arreglos ($(date +%H:%M))"
uv run python -m tool_use.evaluate --out reports/phase2_bench_base_v2.json
echo "=== TODO TERMINADO v2 ($(date +%H:%M))"
