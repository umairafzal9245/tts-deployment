# SGLang-Omni Qwen3-TTS 0.6B Production Deployment

A production-ready, Docker-based deployment of the [SGLang-Omni](https://github.com/sgl-project/sglang-omni) Qwen3-TTS 0.6B text-to-speech server.

## Features

- **Model**: `Qwen/Qwen3-TTS-12Hz-0.6B-Base`
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

   First startup downloads the model from Hugging Face (~1.2 GB), which can take several minutes depending on your connection. The startup timeout is 600 seconds by default.

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
       "input": "Hello from Qwen3 TTS",
       "ref_audio": "/app/sglang-omni/docs/_static/audio/ref_voice.wav",
       "ref_text": "This is a reference voice sample.",
       "response_format": "wav"
     }' \
     --output hello.wav
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
| `ref_text` | string | No | `null` | Transcript of the reference audio |
| `language` | string | No | `null` | Language code (e.g., `"en"`, `"zh"`) |
| `instructions` | string | No | `null` | Style/emotion instructions |
| `temperature` | float | No | `null` | Sampling temperature |
| `top_p` | float | No | `null` | Top-p sampling |
| `top_k` | int | No | `null` | Top-k sampling |
| `seed` | int | No | `null` | Random seed for reproducibility |

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
    "input": "Hello, this is a test of the text to speech system.",
    "ref_audio": "/path/to/reference.wav",
    "ref_text": "This is the transcript of the reference audio.",
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
| `SGLANG_OMNI_MODEL_PATH` | `Qwen/Qwen3-TTS-12Hz-0.6B-Base` | Hugging Face model ID |
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
│   └── qwen3_tts_0_6b.yaml # SGLang-Omni pipeline config
├── scripts/
│   ├── start-server.sh     # Server startup wrapper
│   ├── warmup.py           # Warmup request script
│   ├── healthcheck.sh      # Health check script
│   ├── graceful-shutdown.sh # Shutdown handler
│   └── generate-openapi.py # OpenAPI spec fetcher
└── tests/
    └── test_client.py      # Test client
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
