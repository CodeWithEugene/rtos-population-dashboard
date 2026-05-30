#!/usr/bin/env bash
# One-command, clean-environment entry point:
#   ./run.sh            -> set up env, run pipeline, launch dashboard
#   ./run.sh pipeline   -> set up env + run pipeline only
#   ./run.sh dashboard  -> launch dashboard (assumes data already built)
set -euo pipefail
cd "$(dirname "$0")"

CMD="${1:-all}"

ensure_env() {
  if command -v uv >/dev/null 2>&1; then
    [ -d .venv ] || uv venv --python 3.12
    uv pip install -q -e ".[dev]"
    RUN=(uv run)
  else
    python3 -m venv .venv
    .venv/bin/pip install -q -e ".[dev]"
    RUN=(.venv/bin/python -m)
  fi
}

ensure_env

case "$CMD" in
  pipeline)  "${RUN[@]}" python -m rtos.pipeline ;;
  dashboard) "${RUN[@]}" streamlit run app/dashboard.py ;;
  all)
    "${RUN[@]}" python -m rtos.pipeline
    "${RUN[@]}" streamlit run app/dashboard.py
    ;;
  *) echo "Usage: ./run.sh [pipeline|dashboard|all]" >&2; exit 1 ;;
esac
