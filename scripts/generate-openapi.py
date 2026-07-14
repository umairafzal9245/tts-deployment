#!/usr/bin/env python3
"""Generate a static OpenAPI/Swagger spec from the running SGLang-Omni server.

Usage:
    python scripts/generate-openapi.py http://localhost:8000 > openapi.json
"""

import argparse
import json
import sys
import urllib.request


def fetch_openapi(base_url: str) -> dict:
    url = base_url.rstrip("/") + "/openapi.json"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch OpenAPI spec from a SGLang-Omni server."
    )
    parser.add_argument(
        "base_url",
        nargs="?",
        default="http://localhost:8000",
        help="Base URL of the running server",
    )
    args = parser.parse_args()

    try:
        spec = fetch_openapi(args.base_url)
    except Exception as exc:
        print(f"Failed to fetch OpenAPI spec: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(spec, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
