"""Offscreen grabs for the README. The bundled fictitious contract only.

Usage: python tools/screenshot_readme.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ekisui.domain.types import SaveOptions  # noqa: E402
from ekisui.gui.theme import QSS  # noqa: E402
from ekisui.gui.window import MainWindow  # noqa: E402
from ekisui.pdf.export import export_pdf  # noqa: E402
from screenshot_guide import grab, show_top  # noqa: E402

SAMPLE = ROOT / "samples" / "架空契約_テキスト.pdf"
SCAN = ROOT / "samples" / "架空契約_スキャン.pdf"


def main() -> None:
    out = ROOT / "docs" / "images"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    font_file = Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
    if font_file.exists():
        QFontDatabase.addApplicationFont(str(font_file))
    font = QFont("WenQuanYi Micro Hei")
    font.setPixelSize(14)
    app.setFont(font)
    app.setStyleSheet(QSS)
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    QApplication.processEvents()

    window.open_path(str(SAMPLE))
    window.start_mask()
    # Candidates stay in the list. The page shows the black boxes and the names.
    window.preview = True
    window.refresh()
    window._fit_width()
    show_top(window)
    grab(window, out / "readme-hero.png")

    window.preview = False
    window._confirm()
    dest = Path("/tmp/架空契約_テキスト_Masked.pdf")
    export_pdf(
        window.session.document,
        window.session.groups,
        dest,
        SaveOptions(align_box_width=False, strip_metadata=True, export_log=False, export_replacement_table=False),
        window.session.settings,
        archived=window.session.committed,
        prior_boxes=window.session.burned_boxes,
    )
    window.open_path(str(dest))
    window._fit_width()
    show_top(window)
    grab(window, out / "readme-masked.png")

    window.open_path(str(SCAN))
    window.start_ocr()
    deadline = time.monotonic() + 90
    while window.ocr_running:
        QApplication.processEvents()
        if time.monotonic() > deadline:
            raise SystemExit("OCR did not finish")
        time.sleep(0.05)
    window._fit_width()
    show_top(window)
    grab(window, out / "readme-ocr.png")

    for name in ("readme-hero.png", "readme-ocr.png", "readme-masked.png"):
        path = out / name
        data = path.read_bytes()
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        if data[1:4] != b"PNG" or (width, height) != (1280, 800) or path.stat().st_size < 40_000:
            raise SystemExit(f"{name} is {width}x{height} and {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
