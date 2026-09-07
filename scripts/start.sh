#!/usr/bin/env bash
# Run both halves of PlantCare AI in one container.
#
# Both binaries come from the virtualenv already on PATH (see the Dockerfile), so
# there is no `uv run` wrapper process in front of either one.
set -euo pipefail

API_PORT=8000
UI_PORT="${PORT:-7860}"

# Loopback, not 0.0.0.0. The container publishes exactly one port and it belongs
# to Streamlit; the API is reachable only from inside. `API_BASE_URL` points here.
uvicorn app.api.main:app --host 127.0.0.1 --port "$API_PORT" &
api=$!

streamlit run app/ui/streamlit_app.py \
  --server.port "$UI_PORT" \
  --server.address 0.0.0.0 \
  --server.headless true &
ui=$!

# If either half dies, take the container down with it. A Streamlit still serving
# pages after the API has gone is worse than an outage: every click fails, while
# the platform sees a healthy process and restarts nothing.
trap 'kill -TERM "$api" "$ui" 2>/dev/null || true' EXIT INT TERM

wait -n "$api" "$ui"
exit 1
