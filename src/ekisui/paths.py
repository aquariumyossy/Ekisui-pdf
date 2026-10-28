from __future__ import annotations

import os
import sys
from pathlib import Path


def _meipass() -> Path | None:
    raw = getattr(sys, "_MEIPASS", None)
    return Path(raw) if raw else None


def resource_path(*parts: str) -> Path:
    packaged = Path(__file__).resolve().parent / "resources" / Path(*parts)
    if packaged.exists():
        return packaged
    root = _meipass()
    if root is not None:
        bundled = root / "ekisui" / "resources" / Path(*parts)
        if bundled.exists():
            return bundled
    return packaged


def icon_file() -> Path:
    """Multi-size ICO. Dev checkout and the frozen app both keep it."""
    bundled_name = Path("assets") / "icon" / "ekisui.ico"
    root = _meipass()
    if root is not None:
        bundled = root / bundled_name
        if bundled.is_file():
            return bundled
    repo = Path(__file__).resolve().parents[2] / bundled_name
    return repo


def model_dir() -> Path:
    env = os.environ.get("EKISUI_MODEL_DIR")
    if env:
        return Path(env)
    candidates = []
    root = _meipass()
    if root is not None:
        candidates.append(root / "models" / "ppocrv5")
    repo = Path(__file__).resolve().parents[2] / "models" / "ppocrv5"
    candidates.append(repo)
    candidates.append(Path.cwd() / "models" / "ppocrv5")
    for path in candidates:
        if (path / "ch_PP-OCRv5_det_mobile.onnx").exists():
            return path
    return repo
