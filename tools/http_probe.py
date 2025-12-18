#!/usr/bin/env python3
"""Simple HTTP probe to support Docker health checks."""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="HTTP probe for health checks")
    parser.add_argument("url", help="URL to probe")
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout in seconds (default: 5)",
    )
    args = parser.parse_args()

    request = urllib.request.Request(
        args.url,
        headers={"User-Agent": "HalalLensHealth/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            status = getattr(response, "status", 200)
            if 200 <= status < 400:
                return 0
            print(f"Probe received HTTP {status}", file=sys.stderr)
            return 1
    except urllib.error.URLError as exc:
        print(f"Probe failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
