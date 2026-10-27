"""Check the bundled PP-OCRv5 files. This does not download anything."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "ppocrv5"
SUMS = ROOT / "models" / "SHA256SUMS"


def main() -> int:
    if not SUMS.exists():
        print(f"missing {SUMS}", file=sys.stderr)
        return 1
    bad = False
    for line in SUMS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, name = line.split()
        path = MODEL_DIR / name
        if not path.exists():
            print(f"missing {path}", file=sys.stderr)
            bad = True
            continue
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            extra = ""
            if name.endswith(".txt") and b"\r\n" in data:
                extra = "（改行が CRLF です。このファイルは LF のままにしてください）"
            print(f"hash mismatch {name}{extra}", file=sys.stderr)
            bad = True
        else:
            print(f"ok {name}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
