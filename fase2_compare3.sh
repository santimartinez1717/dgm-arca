# After fase2_compare2.sh: (1) the 18 domain problems still missing with the code of 240de15,
# using this worktree's venv (the old worktree's has no torch); (2) domain with the current code.
cd ~/clusters/dgx/dgm-arca-fase2
while kill -0 43713 2>/dev/null || ps -eo args | grep -v grep | grep -qE "python -m (rlm|tool_use)\."; do sleep 30; done
source smoke/dgx_env.sh
export PYTHONUNBUFFERED=1
OUT=$PWD/reports
echo "=== Variante domain, problemas que faltan, código 240de15 ($(date +%H:%M))"
(cd ../dgm-arca-fase2-old && ../dgm-arca-fase2/.venv/bin/python -m tool_use.phase1_compare \
    --variants none arithmetic domain --per-family 10 --resume --out "$OUT/phase2_vs_phase1.json")
echo "=== Variante domain con el código actual, $(git log --oneline -1 | cut -c1-7) ($(date +%H:%M))"
uv run python -m tool_use.phase1_compare --variants domain --per-family 10 --resume \
    --out reports/phase2_vs_phase1_domain_v3.json
echo "=== TODO TERMINADO ($(date +%H:%M))"
