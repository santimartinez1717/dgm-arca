#!/bin/bash
# Cuando scripts/fase1/distill_priv.sh llegue a cash_on_cash, lo para y lanza scripts/fase1/sft2.sh en su lugar:
# cash_on_cash (sobre todo aritmética, la tanda más lenta) queda para la próxima sesión.
cd ~/clusters/dgx/dgm-arca
until grep -aq "=== Con clave: cash_on_cash" logs/fase1/distill_priv.log; do
    pgrep -f "bash scripts/fase1/distill_priv.sh" >/dev/null || break
    sleep 20
done
pkill -f "bash scripts/fase1/distill_priv.sh" || true
pkill -f "rlm.distill" || true
sleep 15
echo "relevo: scripts/fase1/distill_priv.sh parado a las $(date +%H:%M), lanzo scripts/fase1/sft2.sh"
nohup bash scripts/fase1/sft2.sh > logs/fase1/sft2.log 2>&1 &
