#!/usr/bin/env bash
#
# Runs jobs.ingest_bse + jobs.backfill_evaluations in 7-day slices
# from 2025‑01‑01 up to “today”.  Logs land in logs/manual_backfill/.
#

set -euo pipefail

LOG_DIR="logs/manual_backfill"
mkdir -p "$LOG_DIR"

START_DATE="2025-01-01"
END_DATE="$(date +%Y-%m-%d)"  # today
SLICE_DAYS=6                  # 7-day batches inclusive

log() {
  printf '%(%Y-%m-%d %H:%M:%S)T | %s\n' -1 "$1" | tee -a "$LOG_FILE"
}

run_slice() {
  local from="$1" to="$2"
  log "Starting ingest_bse from $from to $to"
  if ! pipenv run python -m jobs.ingest_bse --from-date "$(date -d "$from" +%Y%m%d)" --to-date "$(date -d "$to" +%Y%m%d)" --save-cache >>"$LOG_FILE" 2>&1; then
    log "ingest_bse failed for $from-$to"; return 1
  fi
  log "Starting backfill_evaluations for $from to $to"
  pipenv run python -m jobs.backfill_evaluations --from-date "$(date -d "$from" +%Y%m%d)" --to-date "$(date -d "$to" +%Y%m%d)" >>"$LOG_FILE" 2>&1
  log "Completed slice $from-$to"
}

main() {
  LOG_FILE="$LOG_DIR/backfill_$(date +%Y%m%d_%H%M%S).log"

  local current="$START_DATE"
  while [[ "$current" < "$END_DATE" || "$current" == "$END_DATE" ]]; do
    # shellcheck disable=SC2155
    local slice_end="$(date -d "$current +$SLICE_DAYS days" +%Y-%m-%d)"
    if [[ "$(date -d "$slice_end" +%s)" -gt "$(date -d "$END_DATE" +%s)" ]]; then
      slice_end="$END_DATE"
    fi
    run_slice "$current" "$slice_end" || exit 1
    current="$(date -d "$slice_end +1 day" +%Y-%m-%d)"
  done

  log "Backfill run finished."
}

main "$@"
