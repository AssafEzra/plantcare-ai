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
# Run the CI selection from a directory that has no .env, which is the condition
# CI actually runs under. A developer's .env silently satisfies pydantic-settings
# for any test that forgot the `env` fixture, so those tests pass locally and fail
# on push - which is exactly how PR 14 broke the build. cwd is changed rather than
# the file moved: an interrupted script must not be able to delete a real .env.
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run "tests" env -C "${TMPDIR:-/tmp}" uv run --project "$root" pytest -q   -c "$root/pyproject.toml" --rootdir "$root" -m "not integration and not live" "$root/tests"

if [ "${1:-}" = "--integration" ]; then
  run "integration" uv run pytest -q -m integration
fi

rm -f /tmp/pc_check.log
exit "$failed"
