#!/usr/bin/env python3
"""Measure time-to-first-token (TTFT) with 24 concurrent TTS streams.

Sends 24 simultaneous streaming requests and records:
  - Time to first audio chunk (TTFT) per request
  - Total time per request
  - Aggregate stats (min/median/max/p95/mean)

Usage:
    python tests/test_ttft_24.py --url http://localhost:8000 --concurrency 24
"""

import argparse
import concurrent.futures
import json
import statistics
import sys
import time
import urllib.request

BASE_URL = "http://localhost:8000"
REF_AUDIO = "/app/sglang-omni/docs/_static/audio/ref_voice.wav"
REF_TEXT = (
    "It was the night before my birthday. Hooray! It\u2019s almost here! "
    "It may not be a holiday, but it\u2019s the best day of the year."
)

SENTENCES = [
    "The quick brown fox jumps over the lazy dog.",
    "Hello, this is a test of the text to speech system.",
    "Artificial intelligence is transforming the world.",
    "The weather today is sunny with a gentle breeze.",
    "Welcome to the future of voice synthesis technology.",
    "Pack my box with five dozen liquor jugs.",
    "She sells seashells by the seashore on a sunny day.",
    "Technology connects people across vast distances instantly.",
]


def single_request(idx: int, sentence: str) -> dict:
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
        resp = urllib.request.urlopen(req, timeout=300)
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            if first_chunk is None:
                first_chunk = time.time() - t0
            total_bytes += len(chunk)
        resp.close()
        total_time = time.time() - t0
        audio_dur = total_bytes / (24000 * 2)
        return {
            "idx": idx,
            "success": True,
            "ttft": first_chunk,
            "total_time": total_time,
            "audio_dur": audio_dur,
            "bytes": total_bytes,
        }
    except Exception as e:
        return {
            "idx": idx,
            "success": False,
            "error": str(e),
            "total_time": time.time() - t0,
        }


def pct(values, p):
    """Percentile p of a sorted list."""
    if not values:
        return 0
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def main() -> int:
    global BASE_URL
    parser = argparse.ArgumentParser(description="TTFT test with N concurrent streams")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=24)
    args = parser.parse_args()
    BASE_URL = args.url.rstrip("/")
    N = args.concurrency

    # Health check
    try:
        resp = urllib.request.urlopen(f"{BASE_URL}/health", timeout=10)
        health = json.loads(resp.read())
        resp.close()
        if health.get("status") != "healthy":
            print("Server not healthy, aborting.")
            return 1
        print(f"Server: {BASE_URL}  Status: healthy")
    except Exception as e:
        print(f"Cannot reach server: {e}")
        return 1

    sentences = [SENTENCES[i % len(SENTENCES)] for i in range(N)]
    print(f"Sending {N} concurrent streaming requests...")
    print(f"Each: max_new_tokens=150, repetition_penalty=1.1, stream=pcm@24kHz\n")

    t_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as pool:
        futures = [pool.submit(single_request, i, sentences[i]) for i in range(N)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    wall_time = time.time() - t_start

    results.sort(key=lambda r: r["idx"])
    successes = [r for r in results if r.get("success")]
    failures = [r for r in results if not r.get("success")]

    print(f"{'#':>3}  {'TTFT (s)':>10}  {'Total (s)':>10}  {'Audio (s)':>10}  {'Status':>8}")
    print("-" * 55)
    for r in results:
        if r["success"]:
            print(f"{r['idx']:>3}  {r['ttft']:>10.3f}  {r['total_time']:>10.3f}  "
                  f"{r['audio_dur']:>10.2f}  {'OK':>8}")
        else:
            print(f"{r['idx']:>3}  {'--':>10}  {r['total_time']:>10.3f}  "
                  f"{'--':>10}  {'FAIL':>8}  {r.get('error','')[:40]}")

    print(f"\n{'=' * 55}")
    print(f"  Wall time:           {wall_time:.2f} s")
    print(f"  Successes:           {len(successes)}/{N}")
    if failures:
        print(f"  Failures:            {len(failures)}")

    if successes:
        ttfts = [r["ttft"] for r in successes]
        totals = [r["total_time"] for r in successes]
        audio_durs = [r["audio_dur"] for r in successes]

        print(f"\n  Time to First Token (TTFT):")
        print(f"    min:    {min(ttfts):.3f} s")
        print(f"    median: {statistics.median(ttfts):.3f} s")
        print(f"    mean:   {statistics.mean(ttfts):.3f} s")
        print(f"    p90:    {pct(ttfts, 90):.3f} s")
        print(f"    p95:    {pct(ttfts, 95):.3f} s")
        print(f"    max:    {max(ttfts):.3f} s")

        print(f"\n  Total request time (start to last byte):")
        print(f"    min:    {min(totals):.3f} s")
        print(f"    median: {statistics.median(totals):.3f} s")
        print(f"    mean:   {statistics.mean(totals):.3f} s")
        print(f"    p95:    {pct(totals, 95):.3f} s")
        print(f"    max:    {max(totals):.3f} s")

        print(f"\n  Audio duration per request:")
        print(f"    mean:   {statistics.mean(audio_durs):.2f} s")
        print(f"    total:  {sum(audio_durs):.2f} s")

        print(f"\n  Throughput: {sum(audio_durs) / wall_time:.2f} seconds of audio / wall second")

    return 0 if len(successes) == N else 1


if __name__ == "__main__":
    sys.exit(main())
