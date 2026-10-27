from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from ekisui_pdf.gui.main_window import MainWindow
from ekisui_pdf.gui.style import STYLE
from ekisui_pdf.network_guard import install_network_guard


def main() -> int:
    install_network_guard()
    app = QApplication(sys.argv)
    app.setApplicationName("易水PDF")
    app.setStyleSheet(STYLE)

    def report(etype, value, tb) -> None:
        text = "".join(traceback.format_exception(etype, value, tb))
        log = Path.home() / "ekisui-pdf-error.log"
        try:
            log.write_text(text, encoding="utf-8")
        except OSError:
            log = None
        QMessageBox.critical(None, "易水PDF", f"{value}\n\n詳細: {log or 'ログを書けませんでした'}")

    sys.excepthook = report
    window = MainWindow()
    window.show()
    return app.exec()
