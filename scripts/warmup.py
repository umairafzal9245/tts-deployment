#!/usr/bin/env python3
"""Warmup request for SGLang-Omni Qwen3-TTS server.

Sends a tiny TTS request to trigger CUDA graph capture and pipeline
initialization before real traffic arrives.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE_URL = os.environ.get("SGLANG_OMNI_WARMUP_URL", "http://localhost:8000")
TIMEOUT = int(os.environ.get("SGLANG_OMNI_WARMUP_TIMEOUT", "300"))
REF_AUDIO = "/app/sglang-omni/docs/_static/audio/ref_voice.wav"
# The transcript MUST match the reference audio. A mismatched ref_text breaks
# in-context-learning (ICL) conditioning and can trigger runaway generation.
# This is the actual transcript of docs/_static/audio/ref_voice.wav.
REF_TEXT = (
    "It was the night before my birthday. Hooray! It’s almost here! "
    "It may not be a holiday, but it’s the best day of the year."
)


def wait_for_health(timeout: int = TIMEOUT) -> bool:
    """Wait until the server /health endpoint returns 200."""
    deadline = time.time() + timeout
    url = f"{BASE_URL}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def send_warmup_tts() -> None:
    """Send a minimal TTS request to warm up the model.

    The base model requires a reference audio, so we pass a local file path
    via the ref_audio field and a short ref_text.
    """
    url = f"{BASE_URL}/v1/audio/speech"
    payload = {
        "model": "qwen3-tts",
        "input": "Hello, this is a warmup request.",
        "voice": "default",
        "response_format": "wav",
        "ref_audio": REF_AUDIO,
        "ref_text": REF_TEXT,
        # Bound generation so a warmup request can never run away to the
        # 2048-token default (~170s of audio). 256 tokens ~= 21s ceiling.
        "max_new_tokens": 256,
        # Slightly above the 1.05 default to suppress repetition loops.
        "repetition_penalty": 1.1,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        _ = resp.read(1024)


def main() -> int:
    print("Warmup: waiting for /health...")
    if not wait_for_health():
        print("Warmup: server did not become healthy.", file=sys.stderr)
        return 1
    print("Warmup: sending TTS request...")
    try:
        send_warmup_tts()
    except Exception as exc:
        print(f"Warmup: TTS request failed: {exc}", file=sys.stderr)
        return 1
    print("Warmup: complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
