# Finish the domain variant with the code it started with (240de15, temporary worktree),
# then measure it again with the current code (annual net income, calls per turn).
# Waits for any phase 1 job on the GPU: two of them do not fit in the 17 GB MIG.
cd ~/clusters/dgx/dgm-arca-fase2
while ps -eo args | grep -v grep | grep -qE "bash (grpo2|eval_ood|sesion[0-9]|sft[0-9])\.sh|python -m rlm\."; do sleep 60; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
REPORT=$PWD/reports/fase2/phase2_vs_phase1.json
echo "=== Variante domain, problemas que faltan, código 240de15 ($(date +%H:%M))"
(cd ../dgm-arca-fase2-old && uv run python -m tool_use.phase1_compare --variants none arithmetic domain \
    --per-family 10 --resume --out "$REPORT")
echo "=== Variante domain con el código actual ($(date +%H:%M))"
uv run python -m tool_use.phase1_compare --variants domain --per-family 10 --resume \
    --out reports/fase2/phase2_vs_phase1_domain_v2.json
echo "=== TODO TERMINADO ($(date +%H:%M))"
