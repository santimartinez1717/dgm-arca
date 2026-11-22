# Bench with the code chaining fixes with the Euribor description only when no rate is given.
cd ~/clusters/dgx/dgm-arca-fase2
while ps -eo args | grep -v grep | grep -qE "python -m (rlm|tool_use)\."; do sleep 30; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
echo "=== Banco: Qwen3-1.7B base, sin thinking, $(git log --oneline -1 | cut -c1-7) ($(date +%H:%M))"
uv run python -m tool_use.evaluate --out reports/phase2_bench_base_v7.json
echo "=== TODO TERMINADO ($(date +%H:%M))"
