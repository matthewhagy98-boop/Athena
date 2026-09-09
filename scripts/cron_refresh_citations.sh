#!/bin/bash
# Daily citation snapshot collection, intended to be driven by cron.
#
# Cron runs with a minimal environment and an arbitrary working directory, which
# this job cannot tolerate for three separate reasons:
#
#   1. Settings load from a RELATIVE env_file (".env" in evidence_engine/config.py),
#      so DATABASE_URL is only found when the cwd is the repo root.
#   2. scripts/ is not a package entry point -- `python scripts/refresh_citations.py`
#      raises ModuleNotFoundError because sys.path[0] becomes scripts/ rather than
#      the repo root. It must be invoked as `python -m scripts.refresh_citations`.
#   3. The venv's pydantic_core is x86_64-only, so it needs the arch prefix on
#      Apple Silicon.
#
# Each of those fails silently-ish under cron (no tty, output discarded), which is
# why everything below is explicit and every run is logged with a timestamp.
#
# Collection is gated by CITATION_TRACKING_ENABLED. Set it to false to stop the
# feature; do NOT roll back the migration, which destroys irreplaceable history.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
LOG_DIR="${HOME}/Library/Logs"
LOG_FILE="${LOG_DIR}/athena-citations.log"
MAX_LOG_BYTES=$((5 * 1024 * 1024))

mkdir -p "${LOG_DIR}"

# Keep one previous generation so a daily append cannot grow without bound.
if [ -f "${LOG_FILE}" ]; then
  log_size=$(wc -c < "${LOG_FILE}" | tr -d ' ')
  if [ "${log_size}" -gt "${MAX_LOG_BYTES}" ]; then
    mv -f "${LOG_FILE}" "${LOG_FILE}.1"
  fi
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "${LOG_FILE}"; }

cd "${REPO_ROOT}" || { log "FATAL: cannot cd to ${REPO_ROOT}"; exit 1; }

if [ ! -f .env ]; then
  log "FATAL: no .env at ${REPO_ROOT}; DATABASE_URL would be unresolvable"
  exit 1
fi

PYTHON="${REPO_ROOT}/.venv/bin/python"
if [ ! -x "${PYTHON}" ]; then
  log "FATAL: no venv python at ${PYTHON}"
  exit 1
fi

ARCH_PREFIX=()
if [ "$(uname -m)" = "arm64" ]; then
  ARCH_PREFIX=(arch -x86_64)
fi

log "starting citation refresh"
output=$(CITATION_TRACKING_ENABLED=true "${ARCH_PREFIX[@]}" "${PYTHON}" \
  -m scripts.refresh_citations 2>&1)
status=$?

while IFS= read -r line; do
  [ -n "${line}" ] && log "  ${line}"
done <<< "${output}"

if [ "${status}" -ne 0 ]; then
  # Most likely cause is Postgres being unreachable. Snapshots are append-only and
  # idempotent per day, so a failed run is safely retried by tomorrow's run -- or
  # by invoking this script by hand once the database is back.
  log "FAILED (exit ${status})"
  exit "${status}"
fi

log "completed successfully"
