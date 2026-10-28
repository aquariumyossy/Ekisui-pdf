"""Offscreen grabs for the end-user guide. Fake names only.

Usage: python tools/screenshot_guide.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ekisui.gui.theme import QSS  # noqa: E402
from ekisui.gui.window import MainWindow  # noqa: E402
from screenshot_ui import build_demo, grab  # noqa: E402


def show_top(window: MainWindow) -> None:
    window.view.verticalScrollBar().setValue(0)
    window.view.horizontalScrollBar().setValue(0)
    QApplication.processEvents()


def main() -> None:
    out = ROOT / "docs" / "images"
    out.mkdir(parents=True, exist_ok=True)
    demo = Path("/tmp/架空_準備書面.pdf")
    build_demo(demo)
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

    window.open_path(str(demo))
    window._fit_width()
    show_top(window)
    grab(window, out / "01-open.png")

    window.ocr_running = True
    window.refresh()
    QApplication.processEvents()
    window._fit_width()
    window.card.show()
    window.card.raise_()
    window.apply_progress(1, 2, "")
    show_top(window)
    grab(window, out / "02-ocr.png")
    window.ocr_running = False
    window.card.hide()
    window.refresh()

    window.start_mask()
    window._fit_width()
    show_top(window)
    grab(window, out / "03-mask.png")

    show_top(window)
    window._open_confirm()
    QApplication.processEvents()
    grab(window, out / "04-confirm.png")
    window._confirm()

    show_top(window)
    window._open_save()
    window.save_path.setText(r"C:\書類\架空_準備書面_Masked.pdf")
    window.save_path.setCursorPosition(0)
    QApplication.processEvents()
    grab(window, out / "05-save.png")

    for name in ("01-open.png", "02-ocr.png", "03-mask.png", "04-confirm.png", "05-save.png"):
        path = out / name
        data = path.read_bytes()
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        if data[1:4] != b"PNG" or (width, height) != (1280, 800) or path.stat().st_size < 50_000:
            raise SystemExit(f"{name} is {width}x{height} and {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
