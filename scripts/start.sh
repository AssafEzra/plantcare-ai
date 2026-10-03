#!/usr/bin/env bash
# Run PlantCare AI: one process, serving the API and the built interface.
#
# uvicorn comes from the virtualenv already on PATH (see the Dockerfile), so there
# is no `uv run` wrapper process in front of it.
#
# This used to start two processes and publish only Streamlit's. Now there is one
# server and it binds 0.0.0.0, because the thing being published *is* the API -
# `app/api/spa.py` serves the interface from the same origin, which is what lets
# the browser call a relative `/v1` with no CORS configuration anywhere.
#
# `exec`, so uvicorn becomes PID 1 and receives SIGTERM directly. Cloud Run sends
# SIGTERM and allows a grace period before killing the instance; with a bash
# parent in the way, the signal would reach the shell and uvicorn would be killed
# mid-request instead of draining.
set -euo pipefail

exec uvicorn app.api.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}"
