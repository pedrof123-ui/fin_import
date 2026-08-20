#!/usr/bin/env bash
# PostToolUse(Write|Edit): flag edits to files gated by the AI Researcher regression harness.
#
# Why: scripts/research_regression.py broke in 7ff1be5 (2026-07-31) and stayed dead 17 days
# because nobody ran it after changing api/research_router.py. Three features shipped without
# the end-to-end gate. This fires once per session, on the first edit to a gated file.
set -euo pipefail

input=$(cat)
f=$(jq -r '.tool_input.file_path // .tool_response.filePath // empty' <<<"$input")

case "$f" in
  */api/research_router.py|*/api/ai_dcf_router.py|*/api/valuation_data.py|*/api/industry_data.py|*/api/prompts/research_*.md) ;;
  *) exit 0 ;;
esac

stamp="/tmp/claude-research-regression-$(jq -r '.session_id // "nosession"' <<<"$input")"
[ -e "$stamp" ] && exit 0
: > "$stamp"

cat <<'EOF'
{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"This file is gated by the AI Researcher regression harness: scripts/research_regression.py. It is the only end-to-end check on the report pipeline, and nothing runs it automatically. Before finishing this change set, run `uv run python scripts/research_regression.py` (5 tickers + a degradation case, ~30-36 min measured 2026-08-20, ~$2-3) and compare against the prior baseline so the diff is attributable. Run `uv run pytest tests/` as the free gate meanwhile. If the change is not report-behavioural (comments, unrelated helper), say so and skip it."},"systemMessage":"Regression-gated file edited: research_regression.py should run before this change set lands."}
EOF
