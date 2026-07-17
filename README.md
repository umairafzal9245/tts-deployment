# SGLang-Omni Qwen3-TTS Production Deployment

A production-ready, Docker-based deployment of the [SGLang-Omni](https://github.com/sgl-project/sglang-omni) Qwen3-TTS text-to-speech server.

## Features

- **Model**: `Qwen/Qwen3-TTS-12Hz-1.7B-Base` (configurable — 0.6B also supported)
- **Runtime**: SGLang-Omni multi-stage pipeline (preprocessing → TTS engine → vocoder)
- **API**: OpenAI-compatible endpoints for speech generation, voice cloning, voice management, streaming, and batch processing
- **Deployment**: Single-command Docker Compose on one GPU
- **Production touches**:
  - Health checks and startup readiness probe
  - Warmup request on startup (uses bundled reference audio)
  - Graceful shutdown handler (SIGTERM/SIGINT)
  - Persistent Hugging Face cache, uploaded voices, and logs
  - `.env` driven configuration

## Architecture

```
┌──────────────────────────────────────────────────┐
│  Docker Container (qwen3-tts-server)             │
│                                                   │
│  ┌────────────────────────────────────────────┐   │
│  │  sgl-omni serve (FastAPI + Uvicorn)        │   │
│  │                                            │   │
│  │  REST Endpoints:                           │   │
│  │    POST   /v1/audio/speech                 │   │
│  │    POST   /v1/audio/speech/batch           │   │
│  │    GET    /v1/audio/voices                 │   │
│  │    POST   /v1/audio/voices                 │   │
│  │    DELETE /v1/audio/voices/{name}          │   │
│  │    POST   /v1/audio/transcriptions         │   │
│  │    GET    /health                          │   │
│  │    GET    /v1/models                       │   │
│  │                                            │   │
│  │  WebSocket Endpoint:                       │   │
│  │    WS     /v1/audio/speech/stream          │   │
│  └────────────────────────────────────────────┘   │
│                                                   │
│  ┌────────────────────────────────────────────┐   │
│  │  Multi-stage Pipeline                      │   │
│  │  preprocessing → tts_engine → vocoder      │   │
│  └────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
         │
         ▼
   NVIDIA GPU (single)
```

## Prerequisites

- Linux host with NVIDIA GPU (minimum 8 GB VRAM)
- NVIDIA driver >= 525.60.13
- Docker >= 24.0
- Docker Compose >= 2.20
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

## Quick Start

1. **Clone or copy this directory to your target host.**

2. **Create your environment file:**

   ```bash
   cp .env.example .env
   # Edit .env if you need to set HF_TOKEN or change the port.
   ```

3. **Build and start the server:**

   ```bash
   make build
   make up
   ```

   Or manually:

   ```bash
   docker compose up -d --build
   ```

4. **Wait for the server to become healthy.**

   First startup downloads the model from Hugging Face (~3.4 GB for 1.7B, ~1.2 GB for 0.6B), which can take several minutes depending on your connection. The startup timeout is 600 seconds by default.

   ```bash
   # Poll until healthy
   curl -s http://localhost:8000/health | jq .

   # Or use the Makefile
   make health
   ```

   The server is ready when you see:

   ```json
   {
     "status": "healthy",
     "running": true,
     "stages": ["preprocessing", "tts_engine", "vocoder"]
   }
   ```

5. **Test the API:**

   ```bash
   # List available voices
   curl -s http://localhost:8000/v1/audio/voices | jq .

   # Generate speech with a reference audio
   curl -s -X POST http://localhost:8000/v1/audio/speech \
     -H "Content-Type: application/json" \
     -d '{
       "model": "qwen3-tts",
       "voice": "default",
       "input": "Hello from Qwen3 TTS",
       "references": [{
         "audio_path": "/app/sglang-omni/docs/_static/audio/ref_voice.wav",
         "text": "It was the night before my birthday. Hooray! It’s almost here! It may not be a holiday, but it’s the best day of the year."
       }],
       "language": "English",
       "max_new_tokens": 256,
       "repetition_penalty": 1.1
     }' \
     --output hello.wav
   ```

   > **Important:** The `text` in `references` (or `ref_text`) must be the
   > **actual transcript** of the reference audio. A mismatched transcript
   > breaks in-context-learning conditioning and can cause runaway generation
   > (up to ~170s of looping audio). Always bound `max_new_tokens` to a sane
   > ceiling for your expected output length (12 codec tokens ≈ 1 second of
   > audio). See [Generation Parameters](#generation-parameters) below.

---

## Quick Recipes

The three most common tasks: generating audio with a named voice via
streaming, cloning/removing voices, and listing all available voices.
All examples use `curl` against a server running at `http://localhost:8000`.

### 1. Generate Audio with a Named Voice (Streaming)

Streaming returns chunked raw PCM audio (16-bit, mono, 24 kHz) as it is
generated, so the client can start playback before the full utterance is
done. Set `"stream": true` and `"response_format": "pcm"`.

#### Using a preset voice (`default`)

The `default` voice requires a reference audio + transcript to condition
the base model. Pass them via `ref_audio` and `ref_text`:

```bash
curl -s -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-tts",
    "input": "Hi, my name is Umair and I am from Mansehra.",
    "voice": "default",
    "response_format": "pcm",
    "stream": true,
    "sample_rate": 24000,
    "ref_audio": "/app/sglang-omni/docs/_static/audio/ref_voice.wav",
    "ref_text": "It was the night before my birthday. Hooray! It\u2019s almost here! It may not be a holiday, but it\u2019s the best day of the year.",
    "max_new_tokens": 200,
    "repetition_penalty": 1.1
  }' \
  --output stream.pcm
```

> **`ref_text` must match the reference audio transcript.** A mismatched
> transcript breaks in-context-learning (ICL) conditioning and can cause
> runaway generation. See [Generation Parameters](#generation-parameters).

#### Using a cloned voice (by name)

Once you have uploaded a voice (see [Clone a Voice](#2-clone-or-remove-a-voice)
below), reference it by name — no `ref_audio`/`ref_text` needed:

```bash
curl -s -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-tts",
    "input": "This is my cloned voice speaking.",
    "voice": "my-voice",
    "response_format": "pcm",
    "stream": true,
    "sample_rate": 24000,
    "max_new_tokens": 200,
    "repetition_penalty": 1.1
  }' \
  --output stream.pcm
```

#### Converting streamed PCM to WAV (Python)

```python
import wave

with open("stream.pcm", "rb") as f:
    pcm = f.read()

with wave.open("stream.wav", "wb") as wf:
    wf.setnchannels(1)       # mono
    wf.setsampwidth(2)       # 16-bit
    wf.setframerate(24000)   # 24 kHz
    wf.writeframes(pcm)
```

#### Streaming with Python (real-time playback)

```python
import json
import urllib.request

payload = {
    "model": "qwen3-tts",
    "input": "Hi, my name is Umair and I am from Mansehra.",
    "voice": "my-voice",
    "response_format": "pcm",
    "stream": True,
    "sample_rate": 24000,
    "max_new_tokens": 200,
    "repetition_penalty": 1.1,
}
req = urllib.request.Request(
    "http://localhost:8000/v1/audio/speech",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(req, timeout=120) as resp:
    total = 0
    while True:
        chunk = resp.read(4096)
        if not chunk:
            break
        total += len(chunk)
        # Feed `chunk` to your audio player here (e.g. pyaudio stream).

print(f"Received {total} bytes ({total / (24000 * 2):.2f}s of audio)")
```

---

### 2. Clone or Remove a Voice

#### Clone (upload) a new voice

Upload an audio sample via `multipart/form-data` to create a named voice
that can be reused in all future speech requests.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `audio_sample` | file | Yes | Audio file (WAV, MP3, FLAC, etc.) |
| `name` | string | Yes | Unique name for the cloned voice |
| `consent` | string | Yes | Consent confirmation (e.g. `"I have permission to clone this voice."`) |
| `ref_text` | string | Recommended | Transcript of the reference audio (improves quality) |
| `speaker_description` | string | No | Optional speaker description |

```bash
curl -s -X POST http://localhost:8000/v1/audio/voices \
  -F "name=my-voice" \
  -F "consent=I have permission to clone this voice." \
  -F "ref_text=This is a reference voice sample for cloning." \
  -F "audio_sample=@sample.wav"
```

**Response:**

```json
{
  "name": "my-voice",
  "consent": "I have permission to clone this voice.",
  "created_at": 1784209788,
  "file_size": 145964,
  "mime_type": "audio/wav",
  "ref_text": "This is a reference voice sample for cloning."
}
```

> **Tip:** For best cloning quality, use a clean 5–15 second recording with
> no background noise, and provide the exact transcript as `ref_text`.

#### Remove (delete) a voice

```bash
curl -s -X DELETE http://localhost:8000/v1/audio/voices/my-voice
```

**Response (success):**

```json
{
  "success": true,
  "message": "Voice 'my-voice' deleted successfully"
}
```

**Response (not found):**

```json
{
  "success": false,
  "error": "Voice 'my-voice' not found"
}
```

---

### 3. List All Voices (Preset + Cloned)

```bash
curl -s http://localhost:8000/v1/audio/voices | jq .
```

**Response:**

```json
{
  "voices": ["default"],
  "uploaded_voices": [
    {
      "name": "my-voice",
      "consent": "I have permission to clone this voice.",
      "created_at": 1784209788,
      "file_size": 145964,
      "mime_type": "audio/wav",
      "ref_text": "This is a reference voice sample for cloning."
    }
  ],
  "cache_stats": {
    "entries": 0,
    "memory_bytes": 0,
    "max_bytes": 536870912,
    "hit_count": 0,
    "miss_count": 0
  }
}
```

| Field | Description |
|-------|-------------|
| `voices` | List of preset (built-in) voice names — always includes `"default"` |
| `uploaded_voices` | List of cloned voices with metadata (name, size, transcript, etc.) |
| `cache_stats` | Internal voice-reference cache statistics |

To list only cloned voice names:

```bash
curl -s http://localhost:8000/v1/audio/voices | jq -r '.uploaded_voices[].name'
```

---

## API Reference

Base URL: `http://localhost:8000`

### Health & Info

#### `GET /health`

Returns the server health status and pipeline stage information.

```bash
curl -s http://localhost:8000/health
```

**Response:**

```json
{
  "status": "healthy",
  "running": true,
  "stages": ["preprocessing", "tts_engine", "vocoder"],
  "entry_stage": "preprocessing",
  "total_requests": 0,
  "pending_completions": 0,
  "request_states": {}
}
```

#### `GET /v1/models`

Lists available models.

```bash
curl -s http://localhost:8000/v1/models
```

---

### Voice Management

#### `GET /v1/audio/voices`

Lists all available voices, including built-in and uploaded (cloned) voices.

```bash
curl -s http://localhost:8000/v1/audio/voices
```

**Response:**

```json
{
  "voices": ["default"],
  "uploaded_voices": [
    {
      "name": "my-voice",
      "consent": "true",
      "created_at": 1784037107,
      "file_size": 896776,
      "mime_type": "audio/wav",
      "ref_text": "This is a reference voice sample."
    }
  ],
  "cache_stats": {
    "entries": 0,
    "memory_bytes": 0,
    "max_bytes": 536870912,
    "hit_count": 0,
    "miss_count": 0
  }
}
```

#### `POST /v1/audio/voices`

Uploads a voice sample for voice cloning. The uploaded voice can then be referenced by name in speech generation requests.

**Content-Type:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `audio_sample` | file | Yes | Audio file (WAV, MP3, FLAC, etc.) |
| `consent` | string | Yes | Consent confirmation (e.g., `"true"`) |
| `name` | string | Yes | Unique name for the cloned voice |
| `ref_text` | string | No | Transcript of the reference audio |
| `speaker_description` | string | No | Optional description of the speaker |

```bash
curl -s -X POST http://localhost:8000/v1/audio/voices \
  -F "name=my-voice" \
  -F "consent=true" \
  -F "ref_text=This is a reference voice sample for cloning." \
  -F "audio_sample=@sample.wav"
```

**Response:**

```json
{
  "name": "my-voice",
  "consent": "true",
  "created_at": 1784037107,
  "file_size": 896776,
  "mime_type": "audio/wav",
  "ref_text": "This is a reference voice sample for cloning."
}
```

#### `DELETE /v1/audio/voices/{name}`

Deletes an uploaded voice by name.

```bash
curl -s -X DELETE http://localhost:8000/v1/audio/voices/my-voice
```

**Response:**

```json
{
  "success": true,
  "message": "Voice 'my-voice' deleted successfully"
}
```

---

### Speech Generation

#### `POST /v1/audio/speech`

Generates speech from text. The base model requires either a cloned voice (uploaded via `/v1/audio/voices`) or a direct reference audio (`ref_audio` + `ref_text`).

**Content-Type:** `application/json`

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `input` | string | Yes | — | The text to synthesize |
| `model` | string | No | `"qwen3-tts"` | Model name |
| `voice` | string | No | `"default"` | Voice name (built-in or uploaded) |
| `response_format` | string | No | `"wav"` | Output format: `wav`, `pcm`, `mp3`, `flac` |
| `stream` | boolean | No | `false` | If `true`, streams raw PCM chunks |
| `speed` | float | No | `1.0` | Playback speed multiplier |
| `ref_audio` | string | No | `null` | Path or URL to reference audio file |
| `ref_text` | string | No | `null` | **Actual transcript** of the reference audio (must match!) |
| `references` | array | No | `null` | List of `{audio_path, text}` — preferred form for cloning |
| `language` | string | No | `"auto"` | Language hint: `English`, `Chinese`, `Japanese`, etc. |
| `instructions` | string | No | `null` | Style/emotion instructions |
| `temperature` | float | No | `0.9` | Sampling temperature |
| `top_p` | float | No | `1.0` | Top-p sampling |
| `top_k` | int | No | `50` | Top-k sampling |
| `repetition_penalty` | float | No | `1.05` | Repetition penalty (raise to `1.1` to suppress loops) |
| `max_new_tokens` | int | No | `2048` | Max codec tokens (12 tokens ≈ 1s audio). **Bound this!** |
| `seed` | int | No | `null` | Random seed for reproducibility |

#### Generation Parameters

Qwen3-TTS generates discrete codec tokens at **12 Hz** (12 tokens ≈ 1 second of
audio). Key tuning tips:

- **`max_new_tokens`**: The default is `2048` (~170s of audio). Always set this
  to a sane ceiling for your expected output length to prevent runaway
  generation. For example, a 10-second utterance needs ~120 tokens; set
  `max_new_tokens: 256` as a safe bound.
- **`repetition_penalty`**: The default `1.05` can allow repetition loops on
  ~0.2% of utterances. Raising to `1.1` mitigates this with minimal quality
  impact.
- **`ref_text` / `references[].text`**: Must be the **actual transcript** of the
  reference audio. A mismatched transcript breaks in-context-learning (ICL)
  conditioning, degrades quality, and increases runaway-generation risk.

**Example 1: Generate with a cloned voice**

```bash
curl -s -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-tts",
    "input": "This is my cloned voice speaking.",
    "voice": "my-voice",
    "response_format": "wav"
  }' \
  --output cloned.wav
```

**Example 2: Generate with direct reference audio**

```bash
curl -s -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-tts",
    "voice": "default",
    "input": "Hello, this is a test of the text to speech system.",
    "references": [{
      "audio_path": "/app/sglang-omni/docs/_static/audio/ref_voice.wav",
      "text": "It was the night before my birthday. Hooray! It’s almost here! It may not be a holiday, but it’s the best day of the year."
    }],
    "language": "English",
    "max_new_tokens": 256,
    "repetition_penalty": 1.1,
    "response_format": "wav"
  }' \
  --output output.wav
```

**Example 3: Generate with streaming (raw PCM)**

When `stream` is `true`, the response is a chunked HTTP stream of raw PCM audio data (16-bit, mono, 24 kHz by default). The first chunk includes a `X-Sample-Rate` header.

```bash
curl -s -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-tts",
    "input": "This is a streaming test.",
    "voice": "my-voice",
    "response_format": "pcm",
    "stream": true
  }' \
  --output stream.pcm
```

**Response (non-streaming):** Binary audio file (`Content-Type: audio/wav` or matching `response_format`).

**Response headers (non-streaming):**

| Header | Description |
|--------|-------------|
| `Content-Disposition` | `attachment; filename="speech.wav"` |
| `X-Prompt-Tokens` | Number of input tokens consumed |
| `X-Completion-Tokens` | Number of output tokens generated |
| `X-Engine-Time` | Engine processing time in seconds |

---

### Batch Speech Generation

#### `POST /v1/audio/speech/batch`

Generates speech for multiple texts in a single request. Items are processed concurrently (up to `SGLANG_OMNI_TTS_BATCH_MAX_ITEMS`).

**Content-Type:** `application/json`

```bash
curl -s -X POST http://localhost:8000/v1/audio/speech/batch \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {
        "model": "qwen3-tts",
        "input": "First sentence.",
        "voice": "my-voice",
        "response_format": "wav"
      },
      {
        "model": "qwen3-tts",
        "input": "Second sentence.",
        "voice": "my-voice",
        "response_format": "wav"
      }
    ]
  }' \
  --output batch.json
```

**Response:** JSON with base64-encoded audio data for each item.

```json
{
  "id": "speech-batch-xxxx",
  "results": [
    {
      "index": 0,
      "status": "success",
      "audio_data": "UklGRiQ...",
      "format": "wav"
    },
    {
      "index": 1,
      "status": "success",
      "audio_data": "UklGRiQ...",
      "format": "wav"
    }
  ]
}
```

---

### WebSocket Streaming

#### `WS /v1/audio/speech/stream`

Stateful WebSocket endpoint for real-time streaming TTS. Supports sending multiple speech requests within a single session.

**Protocol:**

1. **Client sends `session.config` (JSON text frame):**

```json
{
  "type": "session.config",
  "model": "qwen3-tts",
  "voice": "my-voice",
  "response_format": "pcm",
  "stream_audio": true,
  "speed": 1.0
}
```

2. **Server responds with `session.configured`:**

```json
{
  "type": "session.configured",
  "session_id": "speech_ws_xxxx",
  "response_format": "pcm",
  "stream_audio": true,
  "split_granularity": "sentence"
}
```

3. **Client sends speech requests:**

```json
{
  "type": "speech",
  "input": "Hello, this is a WebSocket streaming test."
}
```

4. **Server streams binary frames** (raw PCM audio chunks) followed by a `speech.done` text frame:

```json
{
  "type": "speech.done",
  "finish_reason": "stop"
}
```

**Python example:**

```python
import asyncio
import json
import websockets

async def stream_tts():
    uri = "ws://localhost:8000/v1/audio/speech/stream"
    async with websockets.connect(uri) as ws:
        # Configure session
        await ws.send(json.dumps({
            "type": "session.config",
            "model": "qwen3-tts",
            "voice": "my-voice",
            "response_format": "pcm",
            "stream_audio": True,
        }))
        resp = await ws.recv()
        print(f"Configured: {resp}")

        # Send speech request
        await ws.send(json.dumps({
            "type": "speech",
            "input": "Hello, this is a streaming test."
        }))

        # Receive audio chunks
        total_bytes = 0
        async for msg in ws:
            if isinstance(msg, bytes):
                total_bytes += len(msg)
                # Process PCM chunk (16-bit, mono, 24 kHz)
            else:
                data = json.loads(msg)
                if data.get("type") in ("speech.done", "error"):
                    print(f"Done: {data}")
                    break

        print(f"Received {total_bytes} bytes of audio")

asyncio.run(stream_tts())
```

---

### Audio Transcription

#### `POST /v1/audio/transcriptions`

Transcribes an audio file to text.

**Content-Type:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | Yes | Audio file to transcribe |
| `model` | string | No | Model name |

```bash
curl -s -X POST http://localhost:8000/v1/audio/transcriptions \
  -F "file=@audio.wav" \
  -F "model=qwen3-tts"
```

---

## Configuration

All configuration is done via environment variables in `.env`. See `.env.example` for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `SGLANG_OMNI_MODEL_PATH` | `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | Hugging Face model ID |
| `SGLANG_OMNI_CONFIG` | `/app/config/qwen3_tts_1_7b.yaml` | Pipeline config YAML path |
| `SGLANG_OMNI_PORT` | `8000` | Server port |
| `SGLANG_OMNI_HOST` | `0.0.0.0` | Server bind address |
| `SGLANG_OMNI_LOG_LEVEL` | `info` | Log level (`debug`, `info`, `warning`, `error`) |
| `SGLANG_OMNI_MAX_RUNNING_REQUESTS` | `16` | Max concurrent requests |
| `SGLANG_OMNI_CUDA_GRAPH_MAX_BS` | `32` | CUDA graph max batch size |
| `SGLANG_OMNI_TTS_BATCH_MAX_ITEMS` | `32` | Max items per batch request |
| `SGLANG_OMNI_STARTUP_TIMEOUT` | `600` | Startup timeout in seconds |
| `SGLANG_OMNI_ALLOWED_MEDIA_DOMAIN` | `""` | Restrict reference audio domains (empty = any) |
| `SGLANG_OMNI_WARMUP_ENABLED` | `1` | Run warmup request on startup |
| `SGLANG_OMNI_WARMUP_TIMEOUT` | `300` | Warmup timeout in seconds |
| `HF_TOKEN` | `""` | Hugging Face token for higher download rate limits |

## Makefile Commands

```bash
make build    # Build the Docker image
make up       # Start the server
make down     # Stop the server
make logs     # Tail logs
make shell    # Open a shell in the container
make test     # List voices via test client
make health   # Check /health
make openapi  # Fetch OpenAPI spec to openapi.json
make clean    # Remove containers, volumes, and image
```

## File Structure

```
.
├── Dockerfile              # Docker image build instructions
├── docker-compose.yml      # Docker Compose service definition
├── .env.example            # Example environment variables
├── .dockerignore           # Docker build context exclusions
├── Makefile                # Convenience commands
├── logging.conf            # Python logging configuration
├── README.md               # This file
├── config/
│   ├── qwen3_tts_0_6b.yaml # SGLang-Omni pipeline config (0.6B)
│   └── qwen3_tts_1_7b.yaml # SGLang-Omni pipeline config (1.7B, default)
├── scripts/
│   ├── start-server.sh     # Server startup wrapper
│   ├── warmup.py           # Warmup request script
│   ├── healthcheck.sh      # Health check script
│   ├── graceful-shutdown.sh # Shutdown handler
│   └── generate-openapi.py # OpenAPI spec fetcher
└── tests/
    ├── test_client.py      # Basic test client
    ├── test_all.py         # Comprehensive test suite (voices, streaming, concurrency)
    └── test_ttft_24.py     # Time-to-first-token benchmark (24 streams)
```

## Persistent Data

Docker Compose creates named volumes for:

| Volume | Mount path | Description |
|--------|------------|-------------|
| `hf-cache` | `/data/hf-cache` | Hugging Face model cache (survives restarts) |
| `voices` | `/data/voices` | Uploaded voice profiles |
| `logs` | `/data/logs` | Server logs |
| `tmp` | `/data/tmp` | Temporary workspace |

## Health Checks

- Docker Compose health check polls `GET /health` every 30 seconds (120 second start period).
- The container is considered healthy once the model is loaded and all pipeline stages are running.
- You can also check manually: `curl http://localhost:8000/health`

## Logging

- Server logs are written to `/data/logs/server.log` inside the container.
- Docker Compose logging is configured with 100 MB max file size and 5 backups.
- View logs with: `docker compose logs -f qwen3-tts-server`

## Troubleshooting

### Container fails to start

1. **Check GPU availability:**

   ```bash
   nvidia-smi
   docker run --rm --gpus all nvidia/cuda:12.1-base nvidia-smi
   ```

2. **Check logs:**

   ```bash
   docker compose logs qwen3-tts-server
   # Or inside the container:
   docker exec qwen3-tts-server cat /data/logs/server.log | grep -v "Still waiting"
   ```

3. **Model download issues:**

   - Set `HF_TOKEN` in `.env` for higher download rate limits.
   - The model (~1.2 GB) is downloaded on first run and cached in the `hf-cache` volume.

### First startup is slow

The model is downloaded from Hugging Face on first run. Subsequent starts use the cached files in the `hf-cache` volume. Typical startup times:

- First run (with download): 5–15 minutes depending on network speed
- Subsequent runs (cached): 1–3 minutes for model loading and CUDA graph capture

### Out of memory (OOM)

The model requires ~7.5 GB VRAM on an 8 GB GPU. If you encounter OOM errors:

- Reduce `SGLANG_OMNI_MAX_RUNNING_REQUESTS` (e.g., to `4` or `8`)
- Reduce `SGLANG_OMNI_CUDA_GRAPH_MAX_BS` (e.g., to `8` or `16`)
- Reduce `SGLANG_OMNI_TTS_BATCH_MAX_ITEMS` (e.g., to `8`)

### NumPy / SciPy compatibility

The Dockerfile installs `sglang-omni`, `qwen-tts`, and `accelerate` with `--no-deps` to avoid pulling duplicate NumPy/SciPy into the virtual environment. The base image (`lmsysorg/sglang-omni:dev`) ships compatible versions of NumPy 2.3.5, SciPy 1.17.1, and Numba 0.66.0. Do not override these versions.

### `check_model_inputs` TypeError

The `qwen-tts==0.1.1` package has a decorator bug (`@check_model_inputs()`). The Dockerfile patches this at build time with `sed` to comment out the broken decorator. If you upgrade `qwen-tts`, verify whether this patch is still needed.

## Scaling

This deployment targets a single GPU. For higher throughput, consider:

- **CUDA MPS**: Run multiple replicas on the same GPU (see SGLang-Omni docs).
- **sgl-omni-router**: Add a router in front of multiple single-GPU instances.
- **Multi-GPU / multi-node**: Deploy multiple containers and route traffic with an external load balancer.

## License

This deployment configuration is provided as-is. Please comply with the licenses of SGLang-Omni, Qwen3-TTS, and any voice data you use.
