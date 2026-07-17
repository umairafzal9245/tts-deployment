# Production Dockerfile for SGLang-Omni Qwen3-TTS 0.6B
# Base image ships UCX, flash-attn, sglang, and CUDA prebuilt.
FROM lmsysorg/sglang-omni:dev

LABEL maintainer="tts-deployment" \
      description="SGLang-Omni Qwen3-TTS 0.6B production serving container" \
      model="Qwen/Qwen3-TTS-12Hz-0.6B-Base"

# Avoid interactive prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies required by Qwen3-TTS (sox binary + Python sox)
RUN apt-get update && apt-get install -y --no-install-recommends \
        sox \
        libsox-dev \
        libsox-fmt-all \
        curl \
        ca-certificates \
        logrotate \
    && rm -rf /var/lib/apt/lists/*

# Set up Python environment and install SGLang-Omni from latest main + Qwen3-TTS deps
WORKDIR /app

# Clone sglang-omni latest main and install with --no-deps to avoid
# pulling duplicate scipy/transformers/numpy into venv (system already has them)
RUN git clone https://github.com/sgl-project/sglang-omni.git /app/sglang-omni && \
    cd /app/sglang-omni && \
    uv venv .venv --system-site-packages -p 3.12 && \
    . .venv/bin/activate && \
    uv pip install --no-deps -e . && \
    uv pip install --no-deps qwen-tts==0.1.1 && \
    uv pip install --no-deps accelerate && \
    uv pip install sox einops onnxruntime librosa audioread && \
    # Pin torch 2.11.0 in venv (system has 2.13.0 which breaks sgl-kernel 0.4.4 ABI).
    # Also install matching torchvision so nms operator works for S2-Pro/Voxtral.
    uv pip install --index-url https://download.pytorch.org/whl/cu130 --index-strategy unsafe-best-match \
        "torch==2.11.0" "torchvision" && \
    # S2-Pro (FishAudio) deps:
    uv pip install hydra-core descript-audiotools && \
    sed -i 's/@check_model_inputs()/# @check_model_inputs()/g' /app/sglang-omni/.venv/lib/python3.12/site-packages/qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py

# Copy deployment helpers into the image
COPY scripts/ /app/scripts/
COPY config/ /app/config/
COPY logging.conf /app/logging.conf

# Make scripts executable
RUN chmod +x /app/scripts/*.sh /app/scripts/*.py

# Persistent directories for production data
RUN mkdir -p /data/hf-cache /data/voices /data/logs /data/tmp && \
    chmod -R 777 /data

# Environment defaults (overridable at runtime)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/data/hf-cache \
    HUGGINGFACE_HUB_CACHE=/data/hf-cache \
    TRANSFORMERS_CACHE=/data/hf-cache \
    SGLANG_OMNI_SPEAKER_SAMPLES_DIR=/data/voices \
    SGLANG_OMNI_LOG_DIR=/data/logs \
    SGLANG_OMNI_TMP_DIR=/data/tmp \
    SGLANG_OMNI_MODEL_PATH=Qwen/Qwen3-TTS-12Hz-0.6B-Base \
    SGLANG_OMNI_CONFIG=/app/config/qwen3_tts_0_6b.yaml \
    SGLANG_OMNI_HOST=0.0.0.0 \
    SGLANG_OMNI_PORT=8000 \
    SGLANG_OMNI_LOG_LEVEL=info \
    SGLANG_OMNI_MAX_RUNNING_REQUESTS=100 \
    SGLANG_OMNI_CUDA_GRAPH_MAX_BS=128 \
    SGLANG_OMNI_MEM_FRACTION_STATIC=0.88 \
    SGLANG_OMNI_ALLOWED_MEDIA_DOMAIN="" \
    SGLANG_OMNI_TTS_BATCH_MAX_ITEMS=32 \
    SGLANG_OMNI_VOCODER_MAX_BATCH_SIZE=64 \
    SGLANG_OMNI_VOCODER_MAX_BATCH_WAIT_MS=5 \
    SGLANG_OMNI_STARTUP_TIMEOUT=600 \
    SGLANG_OMNI_WARMUP_ENABLED=1 \
    SGLANG_OMNI_WARMUP_TIMEOUT=300 \
    PATH="/app/sglang-omni/.venv/bin:${PATH}" \
    VIRTUAL_ENV=/app/sglang-omni/.venv

# Health check using the native /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -fsS http://localhost:${SGLANG_OMNI_PORT}/health || exit 1

# Expose the API port
EXPOSE 8000

# Use tini for proper signal handling and graceful shutdown
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/usr/bin/tini", "--"]

# Start the production server via our wrapper script
CMD ["/app/scripts/start-server.sh"]
