#!/usr/bin/env bash
# The same gate CI runs, reported by exit code rather than by trailing output.
#
# Exists because a `ruff check . | tail -1` once showed "No fixes available" and
# hid the "Found 2 errors" line above it, so a red build was pushed. Read the
# exit status, not the last line.
set -uo pipefail

failed=0
run() {
  local name="$1"; shift
  if "$@" > /tmp/pc_check.log 2>&1; then
    printf '  %-8s OK\n' "$name"
  else
    printf '  %-8s FAIL\n' "$name"
    tail -20 /tmp/pc_check.log | sed 's/^/      /'
    failed=1
  fi
}

echo "PlantCare AI - checks"
run "format" uv run ruff format --check .
run "lint"   uv run ruff check .
run "mypy"   uv run mypy app
run "tests"  uv run pytest -q -m "not integration and not live"

if [ "${1:-}" = "--integration" ]; then
  run "integration" uv run pytest -q -m integration
fi

rm -f /tmp/pc_check.log
exit "$failed"
