"""manifest.json のモデルを models/ に置く。実行時ではなく、開発とビルドのときだけ使う。"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "models" / "manifest.json"
DEST = ROOT / "models"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    DEST.mkdir(parents=True, exist_ok=True)
    for item in manifest["models"]:
        target = DEST / item["filename"]
        expected = item["sha256"]
        if target.is_file() and _sha256(target) == expected:
            print(f"ok {target.name}")
            continue
        print(f"download {item['url']}")
        urllib.request.urlretrieve(item["url"], target)
        actual = _sha256(target)
        if actual != expected:
            target.unlink(missing_ok=True)
            raise SystemExit(f"SHA-256 mismatch for {target.name}: {actual}")
        print(f"saved {target.name} {target.stat().st_size} bytes")


if __name__ == "__main__":
    fetch()
