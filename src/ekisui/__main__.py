from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    from ekisui.netguard import install

    install()
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from ekisui.smoke import run

        dest = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("smoke-out")
        return run(dest)
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from ekisui.gui.theme import QSS
    from ekisui.gui.window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("ekisui-pdf")
    app.setOrganizationName("ekisui")
    for candidate in (
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/YuGothR.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
    ):
        if Path(candidate).exists():
            QFontDatabase.addApplicationFont(candidate)
    font = QFont()
    font.setPixelSize(14)
    families = QFontDatabase.families()
    for name in ("Yu Gothic UI", "Yu Gothic", "Meiryo", "Noto Sans CJK JP", "WenQuanYi Micro Hei"):
        if name in families:
            font.setFamily(name)
            break
    app.setFont(font)
    app.setStyleSheet(QSS)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).suffix.lower() in {".pdf", ".doc", ".docx"}:
        window.open_path(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
