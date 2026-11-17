# With vs without tools on the phase 1 test: 10 problems per family x 3 variants.
# Waits for GRPO 2 (and anything else of phase 1) to free the GPU. A cut session keeps its
# rows: the same command continues them (--resume).
# Use: nohup bash fase2_compare.sh > fase2_compare.log 2>&1 &
cd ~/clusters/dgx/dgm-arca-fase2
while ps -eo args | grep -v grep | grep -qE "bash grpo2\.sh|python -m rlm\."; do sleep 60; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
echo "=== Con y sin herramientas sobre el test de la fase 1 ($(date +%H:%M))"
uv run python -m tool_use.phase1_compare --variants none arithmetic domain --per-family 10 \
    --resume --out reports/phase2_vs_phase1.json
echo "=== TODO TERMINADO ($(date +%H:%M))"
