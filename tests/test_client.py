#!/usr/bin/env python3
"""Simple test client for the SGLang-Omni Qwen3-TTS OpenAI-compatible endpoint.

Supports:
  - Listing voices
  - Uploading a cloned voice
  - Generating speech (default or cloned voice)
  - Streaming PCM audio

Examples:
    # List voices
    python tests/test_client.py --url http://localhost:8000 list

    # Generate speech with default voice, save to WAV
    python tests/test_client.py --url http://localhost:8000 speak \
        --text "Hello from Qwen3 TTS" --output hello.wav

    # Upload a voice sample and generate cloned speech
    python tests/test_client.py --url http://localhost:8000 upload-voice \
        --name my-voice --audio sample.wav --ref-text "Hello world" \
        --consent "I have permission to clone this voice."

    python tests/test_client.py --url http://localhost:8000 speak \
        --voice my-voice --text "This is my cloned voice." --output cloned.wav
"""

import argparse
import base64
import json
import sys
import urllib.request
import wave
from pathlib import Path


class TTSClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, data=None, headers=None):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, data=data, method=method)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.read()

    def list_voices(self):
        return self._request("GET", "/v1/audio/voices")

    def upload_voice(
        self,
        name: str,
        audio_path: str,
        ref_text: str,
        consent: str,
        speaker_description: str | None = None,
    ):
        # Build multipart/form-data manually to avoid extra deps.
        boundary = "----TTSClientBoundary"
        audio_bytes = Path(audio_path).read_bytes()
        filename = Path(audio_path).name

        parts = []
        fields = {
            "name": name,
            "consent": consent,
            "ref_text": ref_text,
        }
        if speaker_description:
            fields["speaker_description"] = speaker_description

        for key, value in fields.items():
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
            )
            parts.append(f"{value}\r\n".encode())

        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="audio_sample"; filename="{filename}"\r\n'.encode()
        )
        parts.append(b"Content-Type: audio/wav\r\n\r\n")
        parts.append(audio_bytes)
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())

        body = b"".join(parts)
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        }
        return self._request("POST", "/v1/audio/voices", data=body, headers=headers)

    def speak(
        self,
        text: str,
        voice: str = "default",
        response_format: str = "wav",
        sample_rate: int = 16000,
        stream: bool = False,
    ):
        payload = {
            "model": "qwen3-tts",
            "input": text,
            "voice": voice,
            "response_format": response_format,
            "sample_rate": sample_rate,
            "stream": stream,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        return self._request("POST", "/v1/audio/speech", data=data, headers=headers)


def cmd_list(client: TTSClient, args: argparse.Namespace) -> int:
    voices = json.loads(client.list_voices())
    print(json.dumps(voices, indent=2))
    return 0


def cmd_upload_voice(client: TTSClient, args: argparse.Namespace) -> int:
    response = client.upload_voice(
        name=args.name,
        audio_path=args.audio,
        ref_text=args.ref_text,
        consent=args.consent,
        speaker_description=args.speaker_description,
    )
    print(response.decode("utf-8"))
    return 0


def cmd_speak(client: TTSClient, args: argparse.Namespace) -> int:
    audio = client.speak(
        text=args.text,
        voice=args.voice,
        response_format=args.format,
        sample_rate=args.sample_rate,
        stream=args.stream,
    )
    output = Path(args.output)
    if args.format == "pcm":
        # Save raw PCM; also write a WAV wrapper for convenience.
        output.write_bytes(audio)
        wav_path = output.with_suffix(".wav")
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(args.sample_rate)
            wf.writeframes(audio)
        print(f"Saved PCM to {output} and WAV to {wav_path}")
    else:
        output.write_bytes(audio)
        print(f"Saved audio to {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SGLang-Omni Qwen3-TTS test client")
    parser.add_argument(
        "--url", default="http://localhost:8000", help="Server base URL"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List available voices")

    upload_parser = subparsers.add_parser("upload-voice", help="Upload a voice sample")
    upload_parser.add_argument("--name", required=True, help="Voice name")
    upload_parser.add_argument("--audio", required=True, help="Path to reference audio")
    upload_parser.add_argument("--ref-text", required=True, help="Reference transcript")
    upload_parser.add_argument("--consent", required=True, help="Consent text")
    upload_parser.add_argument(
        "--speaker-description", default=None, help="Speaker description"
    )

    speak_parser = subparsers.add_parser("speak", help="Generate speech")
    speak_parser.add_argument("--text", required=True, help="Text to synthesize")
    speak_parser.add_argument("--voice", default="default", help="Voice ID or name")
    speak_parser.add_argument("--format", default="wav", choices=["wav", "pcm", "mp3"])
    speak_parser.add_argument("--sample-rate", type=int, default=16000)
    speak_parser.add_argument("--stream", action="store_true", help="Stream audio")
    speak_parser.add_argument("--output", default="output.wav", help="Output file path")

    args = parser.parse_args()
    client = TTSClient(args.url)

    if args.command == "list":
        return cmd_list(client, args)
    if args.command == "upload-voice":
        return cmd_upload_voice(client, args)
    if args.command == "speak":
        return cmd_speak(client, args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
