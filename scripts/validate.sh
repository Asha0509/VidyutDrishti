#!/usr/bin/env bash
# One-command validation: lint -> tests -> held-out detection gate -> AI eval -> frontend build.
# Usage: scripts/validate.sh [--full] [--skip-frontend]
#   --full also re-runs the real-data checks (downloads the London meter data once):
#   simulator realism and the forecast benchmark.
set -uo pipefail
cd "$(dirname "$0")/.."

STAGES=(); FAILED=0
stage() { # name, command...
  local name="$1"; shift
  local t0=$SECONDS
  echo; echo "==> $name"
  if "$@"; then STAGES+=("PASS  $name ($((SECONDS - t0))s)"); else STAGES+=("FAIL  $name ($((SECONDS - t0))s)"); FAILED=1; fi
}
finish() { echo; echo "---- validation summary ----"; printf "%s\n" "${STAGES[@]}"; exit $FAILED; }

FULL=0; SKIP_FE=0
for a in "$@"; do [[ $a == --full ]] && FULL=1; [[ $a == --skip-frontend ]] && SKIP_FE=1; done
stage "lint (ruff)" ruff check .
stage "backend tests" bash -c "cd backend && python -m pytest -q -p no:warnings"
stage "end-to-end tests" python -m pytest tests/e2e -q -p no:warnings
stage "held-out detection (20 unseen networks, recall gate 0.85)" python evals/detection_eval.py --networks 20 --first-seed 1000 --gate-recall 0.85 --out /tmp/detection.json
stage "AI eval, rules baseline" python evals/ai_eval.py --mode rules --out /tmp/ai-rules.json
if [[ -n "${GROQ_API_KEY:-}" ]]; then
  stage "AI eval, agent" python evals/ai_eval.py --mode agent --delay 2 --out /tmp/ai-agent.json
else
  echo "(agent eval skipped: GROQ_API_KEY not set)"
fi
if [[ $FULL == 1 ]]; then
  stage "simulator realism vs real meters" python evals/realism_eval.py
  stage "forecast benchmark" python evals/forecast_benchmark.py
fi
if [[ $SKIP_FE == 0 && -d frontend/node_modules ]]; then
  stage "frontend build" bash -c "cd frontend && npm run build"
fi
finish
