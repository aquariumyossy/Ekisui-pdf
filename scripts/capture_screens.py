"""主要画面のスクリーンショットを docs/screenshots に書き出す。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from ekisui_pdf.core.models import Action, ExportResult, Leftover, VerifyReport
from ekisui_pdf.core.pdfio import export_pdf
from ekisui_pdf.core.models import SaveOptions
from ekisui_pdf.core.table import ReplacementTable
from ekisui_pdf.gui.dialogs import OcrProgressDialog, SaveOptionsDialog, VerifyResultDialog
from ekisui_pdf.gui.main_window import MainWindow
from ekisui_pdf.gui.style import STYLE
from tests.factories import scanned_pdf

OUT = ROOT / "docs" / "screenshots"


def grab(widget, name: str) -> None:
    app = QApplication.instance()
    widget.show()
    widget.raise_()
    app.processEvents()
    widget.repaint()
    app.processEvents()
    pixmap = widget.grab()
    if pixmap.isNull() or pixmap.width() < 80 or pixmap.height() < 80:
        raise SystemExit(f"screenshot failed: {name}")
    path = OUT / name
    if not pixmap.save(str(path)):
        raise SystemExit(f"could not save {path}")
    print(path, pixmap.width(), pixmap.height())


def placeholder(name: str, title: str, body: str) -> None:
    pixmap = QPixmap(720, 420)
    pixmap.fill(QColor("#f3f3f3"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#9b2c2c"))
    painter.setFont(QFont("sans-serif", 14))
    painter.drawText(24, 36, "プレースホルダ（実機の SmartScreen 画面ではありません）")
    painter.setPen(QColor("#1e1a16"))
    painter.setFont(QFont("sans-serif", 18))
    painter.drawText(24, 90, title)
    painter.setFont(QFont("sans-serif", 13))
    y = 140
    for line in body.split("\n"):
        painter.drawText(24, y, line)
        y += 28
    painter.end()
    path = OUT / name
    pixmap.save(str(path))
    print(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyleSheet(STYLE)

    sample = ROOT / "build" / "screenshot-sample.pdf"
    sample.parent.mkdir(parents=True, exist_ok=True)
    lines = scanned_pdf(
        sample,
        [
            [
                "株式会社サンプルは山田太郎を被告とする。",
                "原告は株式会社　ＡＢＣである。",
            ],
            [
                "次のページにも山田太郎がいる。",
                "甲は佐藤花子に通知した。",
            ],
        ],
        color=(0.05, 0.05, 0.05),
    )
    window = MainWindow()
    window.resize(1280, 900)
    window.open_pdf(sample)
    window.load_ocr_lines(lines)
    window.show()
    app.processEvents()
    window.zoom_slider.setValue(170)
    app.processEvents()
    window.view.centerOn(420, 280)
    grab(window, "01-open.png")

    progress = OcrProgressDialog(5, window)
    progress.set_progress(2, 5, "2 / 5 ページを読み取っています。通信はしていません。")
    progress.resize(480, 200)
    grab(progress, "02-ocr-progress.png")
    progress.hide()

    window.search_box.setText("山田太郎")
    window._search()
    window.selections[0].action = Action.PSEUDONYM
    window.selections[0].pseudonym = "被告A"
    window._refresh_selection_table()
    window._draw_overlays()
    window.view.centerOn(420, 280)
    grab(window, "03-selections.png")

    window.table.upsert("山田太郎", "被告A")
    window.table.upsert("株式会社ＡＢＣ", "会社A")
    window._refresh_replacement_table()
    window.replacement_table.selectRow(1)
    window._find_variants_for_row()
    grab(window, "04-replacement-table.png")

    save_dialog = SaveOptionsDialog(Path.home() / "訴状-易水.pdf", window)
    save_dialog.fixed_box.setChecked(True)
    save_dialog.resize(640, 420)
    grab(save_dialog, "05-save-options.png")
    save_dialog.hide()

    dest = ROOT / "build" / "screenshot-out.pdf"
    for selection in window.selections:
        if selection.matched_text == "山田太郎" and not selection.pseudonym:
            selection.action = Action.REDACT
    result = export_pdf(
        window.document,
        dest,
        window.lines,
        window.selections,
        window.table,
        SaveOptions(strip_metadata=True, fixed_width=True, fixed_width_pt=160),
        source_path=sample,
    )
    passed = VerifyResultDialog(result, window)
    passed.resize(640, 480)
    grab(passed, "06-verify-pass.png")
    passed.hide()

    failed = VerifyResultDialog(
        ExportResult(
            report=VerifyReport(
                passed=False,
                leftovers=(Leftover("山田太郎", 1, "text"),),
                checked_terms=("山田太郎",),
            ),
            redaction_count=1,
            pseudonym_count=0,
            output_path=str(dest),
            applied_box_width=None,
        ),
        window,
    )
    failed.resize(640, 480)
    grab(failed, "07-verify-fail.png")

    placeholder(
        "08-smartscreen-more-info-placeholder.png",
        "Windows によって PC が保護されました",
        "発行元を確認できませんでした。\n"
        "［詳細情報］をクリックします。\n\n"
        "実物の画面は、署名のないインストーラを初めて開いたときに出ます。\n"
        "この画像は手順の目印であり、Microsoft の画面そのものではありません。",
    )
    placeholder(
        "09-smartscreen-run-placeholder.png",
        "詳細情報のあと",
        "［実行］ボタンが出ます。それを押すとインストールが始まります。\n"
        "SHA-256 が配布元の値と一致していることを先に確認してください。\n\n"
        "実物の画面は Windows 上でしか撮れません。公開前に所有者の確認が必要です。",
    )


if __name__ == "__main__":
    main()
