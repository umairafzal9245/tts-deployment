#!/usr/bin/env bash
# Benchmark all TTS models on the L40S.
# Usage: bash tests/benchmark_all_models.sh
set -euo pipefail

cd /root/tts-deployment

MODELS=(
  "higgs_tts|bosonai/higgs-tts-3-4b|higgs-tts"
  "qwen3_tts_1_7b|Qwen/Qwen3-TTS-12Hz-1.7B-Base|qwen3-tts"
  "qwen3_tts_0_6b|Qwen/Qwen3-TTS-12Hz-0.6B-Base|qwen3-tts"
  "s2pro_tts|fishaudio/s2-pro|s2-pro"
  "voxtral_tts|mistralai/Voxtral-4B-TTS-2603|voxtral-tts"
  "moss_tts_local|OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5|moss-tts"
)

REF_AUDIO="/app/sglang-omni/docs/_static/audio/ref_voice.wav"
REF_TEXT="It was the night before my birthday. Hooray! It\u2019s almost here! It may not be a holiday, but it\u2019s the best day of the year."
INPUT_TEXT="Hello world test."

echo "model,concurrency,ttft_min,ttft_median,ttft_mean,ttft_p95,ttft_max,total_median,wall_time,throughput,success,engine_time,prompt_tokens,completion_tokens"

for entry in "${MODELS[@]}"; do
  IFS='|' read -r CONFIG MODEL_PATH MODEL_NAME <<< "$entry"
  echo "=== Starting $MODEL_NAME ($MODEL_PATH) ===" >&2

  # Update .env
  sed -i "s|^SGLANG_OMNI_MODEL_PATH=.*|SGLANG_OMNI_MODEL_PATH=$MODEL_PATH|" .env
  sed -i "s|^SGLANG_OMNI_CONFIG=.*|SGLANG_OMNI_CONFIG=/app/config/${CONFIG}.yaml|" .env

  # Restart container
  docker compose down 2>&1 | tail -1 >&2
  docker compose up -d 2>&1 | tail -1 >&2

  # Wait for healthy (up to 10 min)
  HEALTHY=0
  for i in $(seq 1 60); do
    if curl -fsS http://localhost:8000/health 2>/dev/null | grep -q healthy; then
      HEALTHY=1
      break
    fi
    sleep 10
  done

  if [ "$HEALTHY" -eq 0 ]; then
    echo "$MODEL_NAME,0,FAIL,FAIL,FAIL,FAIL,FAIL,FAIL,FAIL,FAIL,0,FAIL,FAIL,FAIL"
    echo "=== $MODEL_NAME FAILED to start ===" >&2
    docker compose logs --tail=20 qwen3-tts 2>&1 | tail -10 >&2
    continue
  fi
  echo "=== $MODEL_NAME healthy ===" >&2

  # Wait for warmup
  for i in $(seq 1 30); do
    if docker exec qwen3-tts-server tail -3 /data/logs/server.log 2>&1 | grep -q "Server is running. Waiting for shutdown"; then
      break
    fi
    sleep 5
  done

  # Single request for engine time
  ENGINE_INFO=$(curl -s -X POST http://localhost:8000/v1/audio/speech \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$MODEL_NAME\",\"input\":\"$INPUT_TEXT\",\"voice\":\"default\",\"response_format\":\"wav\",\"ref_audio\":\"$REF_AUDIO\",\"ref_text\":\"$REF_TEXT\",\"max_new_tokens\":200,\"repetition_penalty\":1.1}" \
    -D - -o /dev/null 2>&1)
  ENGINE_TIME=$(echo "$ENGINE_INFO" | grep -i "x-engine-time" | awk '{print $2}' | tr -d '\r')
  PROMPT_TOK=$(echo "$ENGINE_INFO" | grep -i "x-prompt-tokens" | awk '{print $2}' | tr -d '\r')
  COMPLETION_TOK=$(echo "$ENGINE_INFO" | grep -i "x-completion-tokens" | awk '{print $2}' | tr -d '\r')

  # Run benchmarks at different concurrency levels
  for N in 1 4 16; do
    RESULT=$(python3 tests/test_ttft_24.py --url http://localhost:8000 --concurrency $N 2>&1)
    TTFT_MIN=$(echo "$RESULT" | grep "min:" | head -1 | awk '{print $2}')
    TTFT_MED=$(echo "$RESULT" | grep "median:" | head -1 | awk '{print $2}')
    TTFT_MEAN=$(echo "$RESULT" | grep "mean:" | head -1 | awk '{print $2}')
    TTFT_P95=$(echo "$RESULT" | grep "p95:" | head -1 | awk '{print $2}')
    TTFT_MAX=$(echo "$RESULT" | grep "max:" | head -1 | awk '{print $2}')
    TOTAL_MED=$(echo "$RESULT" | grep "median:" | tail -1 | awk '{print $2}')
    WALL=$(echo "$RESULT" | grep "Wall time:" | awk '{print $3}')
    THROUGHPUT=$(echo "$RESULT" | grep "Throughput:" | awk '{print $2}')
    SUCCESS=$(echo "$RESULT" | grep "Successes:" | awk '{print $2}')

    echo "$MODEL_NAME,$N,$TTFT_MIN,$TTFT_MED,$TTFT_MEAN,$TTFT_P95,$TTFT_MAX,$TOTAL_MED,$WALL,$THROUGHPUT,$SUCCESS,$ENGINE_TIME,$PROMPT_TOK,$COMPLETION_TOK"
  done

  echo "=== $MODEL_NAME done ===" >&2
  sleep 5
done

# Restore Higgs as default
sed -i "s|^SGLANG_OMNI_MODEL_PATH=.*|SGLANG_OMNI_MODEL_PATH=bosonai/higgs-tts-3-4b|" .env
sed -i "s|^SGLANG_OMNI_CONFIG=.*|SGLANG_OMNI_CONFIG=/app/config/higgs_tts.yaml|" .env
echo "=== Restored Higgs TTS as default ===" >&2
