"""Fail if the frozen tree still contains a file the spec was supposed to drop."""

from __future__ import annotations

import sys
from pathlib import Path

from ekisui.bundle_filter import excluded_bundle_dest

_REQUIRED = (
    "opengl32sw.dll",
    "qt6core.dll",
    "qt6gui.dll",
    "qt6widgets.dll",
    "qwindows.dll",
    "qoffscreen.dll",
    "icudtl.dat",
    "ch_pp-ocrv5_det_mobile.onnx",
    "mupdfcpp64.dll",
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: check_bundle.py DIST", file=sys.stderr)
        return 2
    root = Path(args[0])
    if not root.is_dir():
        print(f"missing dist: {root}", file=sys.stderr)
        return 2
    files = [path for path in root.rglob("*") if path.is_file()]
    forbidden = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if excluded_bundle_dest(rel):
            forbidden.append(rel)
    names = {path.name.lower() for path in files}
    missing = [name for name in _REQUIRED if name not in names]
    styles = [
        path
        for path in files
        if "/plugins/styles/" in path.relative_to(root).as_posix().lower()
    ]
    if not styles:
        missing.append("plugins/styles")
    total = sum(path.stat().st_size for path in files)
    print(f"DIST_BYTES {total}")
    print(f"DIST_FILES {len(files)}")
    if forbidden:
        print(f"forbidden {len(forbidden)}")
        for rel in forbidden[:40]:
            print(rel)
        return 1
    if missing:
        print("missing " + ", ".join(missing))
        return 1
    print("BUNDLE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
