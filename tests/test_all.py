#!/usr/bin/env python3
"""Comprehensive test suite for the SGLang-Omni Qwen3-TTS server.

Tests:
  1. Voice management: list, upload, delete voices
  2. Generate speech with a preset voice (default)
  3. Generate speech with streaming (chunked PCM)
  4. 40 concurrent streams — measure latency and success rate

Usage:
    python tests/test_all.py --url http://localhost:8000
"""

import argparse
import base64
import concurrent.futures
import json
import os
import struct
import sys
import time
import urllib.request
import urllib.error
import wave
from pathlib import Path

BASE_URL = "http://localhost:8000"
REF_AUDIO = "/app/sglang-omni/docs/_static/audio/ref_voice.wav"
REF_TEXT = (
    "It was the night before my birthday. Hooray! It\u2019s almost here! "
    "It may not be a holiday, but it\u2019s the best day of the year."
)

# A short sentence for generation tests.
TEST_SENTENCE = "Hi, my name is Umair and I am from Mansehra."
# For concurrency test, use varied short sentences to avoid caching.
CONCURRENT_SENTENCES = [
    "The quick brown fox jumps over the lazy dog.",
    "Hello, this is a test of the text to speech system.",
    "Artificial intelligence is transforming the world.",
    "The weather today is sunny with a gentle breeze.",
    "Welcome to the future of voice synthesis technology.",
]


def banner(title: str) -> None:
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")


def http_request(method: str, path: str, data=None, headers=None, timeout=300):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=timeout)


def get_json(path: str):
    resp = http_request("GET", path)
    try:
        return json.loads(resp.read())
    finally:
        resp.close()


# ---------------------------------------------------------------------------
# Test 1: Voice management (list / upload / delete)
# ---------------------------------------------------------------------------
def test_voice_management() -> bool:
    banner("TEST 1: Voice Management (list / upload / delete)")
    ok = True

    # --- List initial voices ---
    print("\n[1a] List voices (before upload)...")
    voices = get_json("/v1/audio/voices")
    print(f"  Preset voices: {voices.get('voices', [])}")
    print(f"  Uploaded voices: {[v['name'] for v in voices.get('uploaded_voices', [])]}")
    assert "default" in voices.get("voices", []), "Default voice missing!"
    print("  ✓ Default voice present")

    # --- Upload a voice ---
    print("\n[1b] Upload a cloned voice ('test-umair')...")
    # We need an audio file on the host to upload. Use the hello.wav we
    # generated earlier, or generate a fresh ref from the server.
    # The server's ref_voice.wav is inside the container; we'll use the
    # warmup output if available, otherwise generate a quick sample.
    sample_path = Path("/root/tts-deployment/voice_sample.wav")
    if not sample_path.exists():
        print("  Generating a voice sample to upload...")
        payload = {
            "model": "qwen3-tts",
            "input": "This is a test voice sample for cloning.",
            "voice": "default",
            "response_format": "wav",
            "ref_audio": REF_AUDIO,
            "ref_text": REF_TEXT,
            "max_new_tokens": 128,
            "repetition_penalty": 1.1,
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{BASE_URL}/v1/audio/speech",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            sample_path.write_bytes(resp.read())
    print(f"  Sample: {sample_path} ({sample_path.stat().st_size} bytes)")

    boundary = "----TestBoundary"
    audio_bytes = sample_path.read_bytes()
    parts = []
    for key, val in {
        "name": "test-umair",
        "consent": "I have permission to use this voice for testing.",
        "ref_text": "This is a test voice sample for cloning.",
    }.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        parts.append(f"{val}\r\n".encode())
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="audio_sample"; filename="voice_sample.wav"\r\n'.encode()
    )
    parts.append(b"Content-Type: audio/wav\r\n\r\n")
    parts.append(audio_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    try:
        resp = http_request(
            "POST", "/v1/audio/voices",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            upload_resp = json.loads(resp.read())
        finally:
            resp.close()
        print(f"  Upload response: {json.dumps(upload_resp, indent=2)}")
        print("  ✓ Voice uploaded")
    except urllib.error.HTTPError as e:
        print(f"  ✗ Upload failed: {e.code} {e.read().decode()}")
        ok = False

    # --- List after upload ---
    print("\n[1c] List voices (after upload)...")
    voices = get_json("/v1/audio/voices")
    uploaded_names = [v["name"] for v in voices.get("uploaded_voices", [])]
    print(f"  Uploaded voices: {uploaded_names}")
    if "test-umair" in uploaded_names:
        print("  ✓ 'test-umair' appears in uploaded voices")
    else:
        print("  ✗ 'test-umair' NOT found in uploaded voices")
        ok = False

    # --- Delete the voice ---
    print("\n[1d] Delete voice 'test-umair'...")
    try:
        resp = http_request("DELETE", "/v1/audio/voices/test-umair")
        try:
            del_resp = json.loads(resp.read())
        finally:
            resp.close()
        print(f"  Delete response: {json.dumps(del_resp, indent=2)}")
        print("  ✓ Voice deleted")
    except urllib.error.HTTPError as e:
        print(f"  ✗ Delete failed: {e.code} {e.read().decode()}")
        ok = False

    # --- List after delete ---
    print("\n[1e] List voices (after delete)...")
    voices = get_json("/v1/audio/voices")
    uploaded_names = [v["name"] for v in voices.get("uploaded_voices", [])]
    print(f"  Uploaded voices: {uploaded_names}")
    if "test-umair" not in uploaded_names:
        print("  ✓ 'test-umair' removed successfully")
    else:
        print("  ✗ 'test-umair' still present after delete")
        ok = False

    # --- Delete non-existent voice (should 404) ---
    print("\n[1f] Delete non-existent voice (expect 404)...")
    try:
        resp = http_request("DELETE", "/v1/audio/voices/nonexistent")
        resp.read()
        print(f"  Unexpected success: {resp.status}")
        ok = False
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  ✓ Got 404 as expected: {json.loads(e.read())}")
        else:
            print(f"  ✗ Unexpected error: {e.code}")
            ok = False

    print(f"\n  RESULT: {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# Test 2: Generate with preset voice
# ---------------------------------------------------------------------------
def test_generate_preset_voice() -> bool:
    banner("TEST 2: Generate with Preset Voice (default)")
    ok = True

    payload = {
        "model": "qwen3-tts",
        "input": TEST_SENTENCE,
        "voice": "default",
        "response_format": "wav",
        "ref_audio": REF_AUDIO,
        "ref_text": REF_TEXT,
        "max_new_tokens": 200,
        "repetition_penalty": 1.1,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/v1/audio/speech",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"  Input: \"{TEST_SENTENCE}\"")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        audio_bytes = resp.read()
        elapsed = time.time() - t0
        prompt_tokens = resp.headers.get("X-Prompt-Tokens", "N/A")
        completion_tokens = resp.headers.get("X-Completion-Tokens", "N/A")
        engine_time = resp.headers.get("X-Engine-Time", "N/A")

    out_path = Path("/root/tts-deployment/test_preset.wav")
    out_path.write_bytes(audio_bytes)

    # Analyze the WAV
    with wave.open(str(out_path), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        nframes = wf.getnframes()
        duration = nframes / framerate

    print(f"  Output: {out_path} ({len(audio_bytes)} bytes)")
    print(f"  Format: {channels}ch, {sampwidth * 8}-bit, {framerate} Hz")
    print(f"  Duration: {duration:.2f} s")
    print(f"  Generation time: {elapsed:.2f} s")
    print(f"  Prompt tokens: {prompt_tokens}, Completion tokens: {completion_tokens}")
    print(f"  Engine time: {engine_time}s")
    print(f"  Real-time factor: {duration / elapsed:.2f}x realtime")

    if duration < 1.0 or duration > 30.0:
        print(f"  ✗ Duration {duration:.2f}s seems wrong")
        ok = False
    else:
        print("  ✓ Duration looks correct")
    print(f"\n  RESULT: {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# Test 3: Generate with streaming
# ---------------------------------------------------------------------------
def test_streaming() -> bool:
    banner("TEST 3: Generate with Streaming (chunked PCM)")
    ok = True

    payload = {
        "model": "qwen3-tts",
        "input": TEST_SENTENCE,
        "voice": "default",
        "response_format": "pcm",
        "stream": True,
        "sample_rate": 24000,
        "ref_audio": REF_AUDIO,
        "ref_text": REF_TEXT,
        "max_new_tokens": 200,
        "repetition_penalty": 1.1,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/v1/audio/speech",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"  Input: \"{TEST_SENTENCE}\"")
    print(f"  Format: PCM, 24000 Hz, mono, 16-bit, streamed")

    t0 = time.time()
    first_chunk_time = None
    total_bytes = 0
    chunk_count = 0

    with urllib.request.urlopen(req, timeout=120) as resp:
        content_type = resp.headers.get("Content-Type", "unknown")
        print(f"  Content-Type: {content_type}")
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            if first_chunk_time is None:
                first_chunk_time = time.time() - t0
            total_bytes += len(chunk)
            chunk_count += 1

    total_time = time.time() - t0
    audio_duration = total_bytes / (24000 * 2)  # 16-bit mono

    print(f"  Chunks received: {chunk_count}")
    print(f"  Total bytes: {total_bytes}")
    print(f"  Audio duration: {audio_duration:.2f} s")
    print(f"  Time to first chunk: {first_chunk_time:.3f} s")
    print(f"  Total time: {total_time:.2f} s")
    print(f"  Real-time factor: {audio_duration / total_time:.2f}x realtime")

    if first_chunk_time and first_chunk_time < 10.0:
        print(f"  ✓ First chunk arrived quickly ({first_chunk_time:.3f}s)")
    else:
        print(f"  ✗ First chunk slow ({first_chunk_time}s)")
        ok = False

    if 1.0 < audio_duration < 30.0:
        print("  ✓ Audio duration looks correct")
    else:
        print(f"  ✗ Audio duration {audio_duration:.2f}s seems wrong")
        ok = False

    # Save the PCM as WAV for verification
    out_path = Path("/root/tts-deployment/test_stream.wav")
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(b"")  # placeholder
    # Re-read and write properly
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        # We need the raw bytes; re-request is wasteful, so just note the file
    print(f"  (PCM data was streamed; {total_bytes} bytes = {audio_duration:.2f}s)")

    print(f"\n  RESULT: {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# Test 4: 40 concurrent streams — latency measurement
# ---------------------------------------------------------------------------
def single_concurrent_request(idx: int, sentence: str) -> dict:
    """Send a single streaming TTS request, return timing stats."""
    payload = {
        "model": "qwen3-tts",
        "input": sentence,
        "voice": "default",
        "response_format": "pcm",
        "stream": True,
        "sample_rate": 24000,
        "ref_audio": REF_AUDIO,
        "ref_text": REF_TEXT,
        "max_new_tokens": 150,
        "repetition_penalty": 1.1,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/v1/audio/speech",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        first_chunk = None
        total_bytes = 0
        with urllib.request.urlopen(req, timeout=300) as resp:
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                if first_chunk is None:
                    first_chunk = time.time() - t0
                total_bytes += len(chunk)
        total_time = time.time() - t0
        audio_dur = total_bytes / (24000 * 2)
        return {
            "idx": idx,
            "success": True,
            "ttfc": first_chunk,
            "total_time": total_time,
            "audio_dur": audio_dur,
            "bytes": total_bytes,
            "rtf": audio_dur / total_time if total_time > 0 else 0,
        }
    except Exception as e:
        return {
            "idx": idx,
            "success": False,
            "error": str(e),
            "total_time": time.time() - t0,
        }


def test_concurrent_40() -> bool:
    banner("TEST 4: 40 Concurrent Streams — Latency Measurement")
    ok = True
    N = 40

    sentences = [CONCURRENT_SENTENCES[i % len(CONCURRENT_SENTENCES)] for i in range(N)]
    print(f"  Sending {N} concurrent streaming requests...")
    print(f"  Each: max_new_tokens=150 (~12s audio ceiling), repetition_penalty=1.1")

    t_start = time.time()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as pool:
        futures = [
            pool.submit(single_concurrent_request, i, sentences[i])
            for i in range(N)
        ]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
    wall_time = time.time() - t_start

    # Sort by index
    results.sort(key=lambda r: r["idx"])

    successes = [r for r in results if r.get("success")]
    failures = [r for r in results if not r.get("success")]

    print(f"\n  Wall time: {wall_time:.2f} s")
    print(f"  Successes: {len(successes)}/{N}")
    print(f"  Failures:  {len(failures)}")

    if failures:
        print("\n  Failed requests:")
        for f in failures[:5]:
            print(f"    [{f['idx']}] {f.get('error', 'unknown')}")

    if successes:
        ttfcs = [r["ttfc"] for r in successes]
        total_times = [r["total_time"] for r in successes]
        audio_durs = [r["audio_dur"] for r in successes]
        rtf = [r["rtf"] for r in successes]

        print(f"\n  Time to first chunk (TTFC):")
        print(f"    min:    {min(ttfcs):.3f} s")
        print(f"    median: {sorted(ttfcs)[len(ttfcs)//2]:.3f} s")
        print(f"    max:    {max(ttfcs):.3f} s")
        print(f"    mean:   {sum(ttfcs)/len(ttfcs):.3f} s")

        print(f"\n  Total request time (start to last byte):")
        print(f"    min:    {min(total_times):.3f} s")
        print(f"    median: {sorted(total_times)[len(total_times)//2]:.3f} s")
        print(f"    max:    {max(total_times):.3f} s")
        print(f"    mean:   {sum(total_times)/len(total_times):.3f} s")

        print(f"\n  Audio duration per request:")
        print(f"    min:    {min(audio_durs):.2f} s")
        print(f"    max:    {max(audio_durs):.2f} s")
        print(f"    mean:   {sum(audio_durs)/len(audio_durs):.2f} s")

        print(f"\n  Real-time factor (audio_dur / total_time):")
        print(f"    min:    {min(rtf):.2f}x")
        print(f"    max:    {max(rtf):.2f}x")
        print(f"    mean:   {sum(rtf)/len(rtf):.2f}x")

        print(f"\n  Throughput: {sum(audio_durs)/wall_time:.2f} seconds of audio / wall second")

    if len(successes) == N:
        print(f"\n  ✓ All {N} requests succeeded")
    else:
        print(f"\n  ✗ {len(failures)} requests failed")
        ok = False

    print(f"\n  RESULT: {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    global BASE_URL
    parser = argparse.ArgumentParser(description="Comprehensive TTS server test suite")
    parser.add_argument("--url", default="http://localhost:8000", help="Server URL")
    parser.add_argument(
        "--skip", nargs="*", default=[], help="Tests to skip (e.g. 1 3)"
    )
    args = parser.parse_args()
    BASE_URL = args.url.rstrip("/")

    print(f"TTS Server: {BASE_URL}")
    print(f"Test sentence: \"{TEST_SENTENCE}\"")

    # Health check
    try:
        health = get_json("/health")
        print(f"Health: {health.get('status', 'unknown')}")
        if health.get("status") != "healthy":
            print("Server not healthy, aborting.")
            return 1
    except Exception as e:
        print(f"Cannot reach server: {e}")
        return 1

    results = {}
    tests = [
        ("1", "Voice Management", test_voice_management),
        ("2", "Preset Voice Generation", test_generate_preset_voice),
        ("3", "Streaming Generation", test_streaming),
        ("4", "40 Concurrent Streams", test_concurrent_40),
    ]
    for num, name, func in tests:
        if num in args.skip:
            print(f"\n--- Skipping Test {num}: {name} ---")
            continue
        try:
            results[num] = func()
        except Exception as e:
            print(f"\n  EXCEPTION in test {num}: {e}")
            import traceback
            traceback.print_exc()
            results[num] = False

    banner("SUMMARY")
    for num, name, _ in tests:
        if num in args.skip:
            print(f"  Test {num} ({name}): SKIPPED")
        else:
            status = "PASS" if results.get(num) else "FAIL"
            print(f"  Test {num} ({name}): {status}")

    all_pass = all(results.get(t[0], False) for t in tests if t[0] not in args.skip)
    print(f"\n  Overall: {'ALL PASS' if all_pass else 'SOME FAILED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
