#!/usr/bin/env bash
# Create the phase-4 GitHub issues from docs/fase4/issues/*.md and assign them.
#
#   gh auth login                     # once
#   git push origin fase4             # the issues link to docs/fase4/ on this branch
#   bash scripts/fase4/crear_issues.sh            # dry run: prints what it would create
#   bash scripts/fase4/crear_issues.sh --create   # creates them
#
# 01-04 go to Bernardo (knowledge), 05-08 to Kike (evaluation). The first line of each file
# ("# Title") is the issue title; the rest is the body.
set -euo pipefail

REPO="santimartinez1717/dgm-arca"
BRANCH="fase4"
LABEL="fase4"
DIR="$(cd "$(dirname "$0")/../.." && pwd)/docs/fase4/issues"

assignee_for() {
  case "$1" in
    0[1-4]-*) echo "berordas" ;;
    0[5-8]-*) echo "enriquerodriguezcamacho" ;;
    *) echo "" ;;
  esac
}

create=false
[[ "${1:-}" == "--create" ]] && create=true

if $create; then
  gh label create "$LABEL" --repo "$REPO" --color 5319e7 \
    --description "Fase 4: agente ReAct" --force >/dev/null
fi

for file in "$DIR"/[0-9][0-9]-*.md; do
  name="$(basename "$file")"
  title="$(head -n 1 "$file" | sed 's/^# //')"
  assignee="$(assignee_for "$name")"
  body="$(tail -n +2 "$file")

---
Diseño: https://github.com/$REPO/blob/$BRANCH/docs/fase4/diseno.md · Fuente: \`docs/fase4/issues/$name\`"
  if $create; then
    gh issue create --repo "$REPO" --title "$title" --body "$body" \
      --label "$LABEL" --assignee "$assignee"
  else
    echo "[dry run] $name -> @$assignee: $title"
  fi
done
