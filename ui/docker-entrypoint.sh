#!/bin/sh
set -e

COMPONENT="ui"
LOG_ROOT="${HALAL_LOG_ROOT:-/app/logs}"
YEAR="$(date +%Y)"
MONTH="$(date +%m)"
DAY="$(date +%d)"
LOG_DIR="$LOG_ROOT/$COMPONENT/$YEAR/$MONTH/$DAY"
LOG_FILE="$LOG_DIR/$COMPONENT.log"

mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
echo "[ui] logging to $LOG_FILE"

tail -F "$LOG_FILE" &
TAIL_PID=$!

cleanup() {
  # shellcheck disable=SC2317
  kill "$TAIL_PID" 2>/dev/null || true
  # shellcheck disable=SC2317
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
  fi
}

trap cleanup INT TERM

serve out -l 3000 >>"$LOG_FILE" 2>&1 &
SERVER_PID=$!
wait "$SERVER_PID"
STATUS=$?
kill "$TAIL_PID" 2>/dev/null || true
wait "$TAIL_PID" 2>/dev/null || true
exit "$STATUS"
