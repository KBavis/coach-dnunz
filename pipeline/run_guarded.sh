#!/usr/bin/env bash
# Run a command; kill it (whole process group) if free memory drops below MIN_MB.
MIN_MB=${MIN_MB:-4000}
setsid "$@" &
PID=$!
while kill -0 $PID 2>/dev/null; do
  a=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  if [ "$a" -lt "$MIN_MB" ]; then
    echo "WATCHDOG: MemAvailable=${a}MB < ${MIN_MB}MB, killing job" >&2
    kill -9 -- -$PID 2>/dev/null; exit 137
  fi
  sleep 0.5
done
wait $PID
