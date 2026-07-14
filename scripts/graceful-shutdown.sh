#!/usr/bin/env bash
# Graceful shutdown helper for the SGLang-Omni Qwen3-TTS container.
# Can be invoked manually or as a pre-stop hook.
set -euo pipefail

: "${SGLANG_OMNI_TMP_DIR:=/data/tmp}"
PID_FILE="$SGLANG_OMNI_TMP_DIR/sglang-omni.pid"
GRACEFUL_TIMEOUT="${SGLANG_OMNI_GRACEFUL_TIMEOUT:-60}"

if [[ ! -s "$PID_FILE" ]]; then
    echo "No PID file found at $PID_FILE; server may not be running."
    exit 0
fi

PID=$(cat "$PID_FILE")
if ! kill -0 "$PID" 2>/dev/null; then
    echo "Server process $PID is not running."
    rm -f "$PID_FILE"
    exit 0
fi

echo "Sending SIGTERM to server process $PID..."
kill -TERM "$PID"

for _ in $(seq 1 "$GRACEFUL_TIMEOUT"); do
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "Server stopped gracefully."
        rm -f "$PID_FILE"
        exit 0
    fi
    sleep 1
done

echo "Server did not stop within ${GRACEFUL_TIMEOUT}s; forcing shutdown."
kill -9 "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
