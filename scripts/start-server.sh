#!/usr/bin/env bash
# Production startup script for SGLang-Omni Qwen3-TTS server.
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
: "${SGLANG_OMNI_HOST:=0.0.0.0}"
: "${SGLANG_OMNI_PORT:=8000}"
: "${SGLANG_OMNI_MODEL_PATH:=Qwen/Qwen3-TTS-12Hz-0.6B-Base}"
: "${SGLANG_OMNI_CONFIG:=/app/config/qwen3_tts_0_6b.yaml}"
: "${SGLANG_OMNI_LOG_LEVEL:=info}"
: "${SGLANG_OMNI_MAX_RUNNING_REQUESTS:=16}"
: "${SGLANG_OMNI_CUDA_GRAPH_MAX_BS:=32}"
: "${SGLANG_OMNI_TTS_BATCH_MAX_ITEMS:=32}"
: "${SGLANG_OMNI_STARTUP_TIMEOUT:=600}"
: "${SGLANG_OMNI_WARMUP_ENABLED:=1}"
: "${SGLANG_OMNI_WARMUP_TIMEOUT:=300}"
: "${SGLANG_OMNI_LOG_DIR:=/data/logs}"
: "${SGLANG_OMNI_TMP_DIR:=/data/tmp}"
: "${SGLANG_OMNI_SPEAKER_SAMPLES_DIR:=/data/voices}"

mkdir -p "$SGLANG_OMNI_LOG_DIR" "$SGLANG_OMNI_TMP_DIR" "$SGLANG_OMNI_SPEAKER_SAMPLES_DIR"

LOG_FILE="$SGLANG_OMNI_LOG_DIR/server.log"
PID_FILE="$SGLANG_OMNI_TMP_DIR/sglang-omni.pid"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"
}

# ---------------------------------------------------------------------------
# Graceful shutdown handler
# ---------------------------------------------------------------------------
cleanup() {
    log "Received shutdown signal, stopping SGLang-Omni server..."
    if [[ -s "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid"
            # Wait up to 60s for graceful shutdown
            for _ in $(seq 1 60); do
                if ! kill -0 "$pid" 2>/dev/null; then
                    break
                fi
                sleep 1
            done
            if kill -0 "$pid" 2>/dev/null; then
                log "Server did not stop gracefully, forcing..."
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
    fi
    log "Shutdown complete."
    exit 0
}
trap cleanup SIGTERM SIGINT

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
log "Starting SGLang-Omni Qwen3-TTS server"
log "Model: $SGLANG_OMNI_MODEL_PATH"
log "Config: $SGLANG_OMNI_CONFIG"
log "Bind: $SGLANG_OMNI_HOST:$SGLANG_OMNI_PORT"

if ! command -v nvidia-smi &>/dev/null; then
    log "WARNING: nvidia-smi not found. GPU may not be available."
else
    log "GPU info:"
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | while read -r line; do
        log "  $line"
    done
fi

# ---------------------------------------------------------------------------
# Build sgl-omni serve command
# ---------------------------------------------------------------------------
# The native CLI is: sgl-omni serve --config <yaml> --host <host> --port <port>
# We rely on the YAML for pipeline/model configuration.
CMD_ARGS=(
    "serve"
    "--config" "$SGLANG_OMNI_CONFIG"
    "--host" "$SGLANG_OMNI_HOST"
    "--port" "$SGLANG_OMNI_PORT"
    "--log-level" "$SGLANG_OMNI_LOG_LEVEL"
)

# Optional: pass model path if the CLI supports --model-path
# (sgl-omni serve uses the YAML; this is a fallback override)
if command -v sgl-omni &>/dev/null; then
    SGLANG_OMNI_BIN="sgl-omni"
else
    SGLANG_OMNI_BIN="python -m sglang_omni.cli"
fi

log "Launching: $SGLANG_OMNI_BIN ${CMD_ARGS[*]}"

# ---------------------------------------------------------------------------
# Start server in background
# ---------------------------------------------------------------------------
$SGLANG_OMNI_BIN "${CMD_ARGS[@]}" >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

log "Server PID: $SERVER_PID"

# ---------------------------------------------------------------------------
# Wait for /health to become ready
# ---------------------------------------------------------------------------
log "Waiting for server to become healthy (timeout ${SGLANG_OMNI_STARTUP_TIMEOUT}s)..."
START_TIME=$(date +%s)
HEALTHY=0
while true; do
    if curl -fsS "http://localhost:$SGLANG_OMNI_PORT/health" >/dev/null 2>&1; then
        HEALTHY=1
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        log "ERROR: Server process exited before becoming healthy."
        wait "$SERVER_PID" || true
        exit 1
    fi
    NOW=$(date +%s)
    if (( NOW - START_TIME > SGLANG_OMNI_STARTUP_TIMEOUT )); then
        log "ERROR: Server did not become healthy within $SGLANG_OMNI_STARTUP_TIMEOUT seconds."
        kill -TERM "$SERVER_PID" 2>/dev/null || true
        exit 1
    fi
    sleep 2
    log "Still waiting for /health..."
done

if [[ "$HEALTHY" -eq 1 ]]; then
    log "Server is healthy."
fi

# ---------------------------------------------------------------------------
# Warmup request (optional)
# ---------------------------------------------------------------------------
if [[ "$SGLANG_OMNI_WARMUP_ENABLED" == "1" ]]; then
    log "Running warmup request..."
    timeout "$SGLANG_OMNI_WARMUP_TIMEOUT" python /app/scripts/warmup.py >> "$LOG_FILE" 2>&1 || log "WARN: Warmup request failed or timed out."
fi

# ---------------------------------------------------------------------------
# Keep script alive and forward signals
# ---------------------------------------------------------------------------
log "Server is running. Waiting for shutdown signal..."
wait "$SERVER_PID" || true
