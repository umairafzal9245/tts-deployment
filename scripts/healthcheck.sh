#!/usr/bin/env bash
# Health check used by Docker and external monitors.
set -euo pipefail

: "${SGLANG_OMNI_PORT:=8000}"

if curl -fsS "http://localhost:${SGLANG_OMNI_PORT}/health" >/dev/null 2>&1; then
    echo "healthy"
    exit 0
fi

echo "unhealthy"
exit 1
