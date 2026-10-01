#!/usr/bin/env python3
"""CLI for the independent ordered-prefix blocking-certificate checker."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE / "src") not in sys.path:
    sys.path.insert(0, str(HERE / "src"))

from check_ordered_certificate import InvalidOrderedCertificate, check_ordered_certificate


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python verify_ordered_certificate.py CERTIFICATE.json")
    path = Path(sys.argv[1])
    if path.stat().st_size > 64 * 1024 * 1024:
        raise SystemExit("certificate exceeds 64 MiB parsing bound")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps(check_ordered_certificate(payload), sort_keys=True))
    except (InvalidOrderedCertificate, ValueError, TypeError, KeyError) as exc:
        raise SystemExit(f"INVALID: {exc}")


if __name__ == "__main__":
    main()
