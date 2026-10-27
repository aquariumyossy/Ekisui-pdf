"""Render the real window offscreen. Usage: python tools/screenshot_ui.py outdir"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pymupdf  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ekisui.domain.types import TextLine, TextSource  # noqa: E402
from ekisui.gui.theme import QSS  # noqa: E402
from ekisui.gui.window import MainWindow  # noqa: E402
from ekisui.pdf.verify import verify_pdf  # noqa: E402
from dataclasses import replace  # noqa: E402


def build_demo(path: Path) -> None:
    doc = pymupdf.open()
    pages = [
        [
            (16, "令和8年（ワ）第1234号　損害賠償請求事件"),
            (13, "原告　株式会社サンプル商事"),
            (13, "被告　山田太郎"),
            (18, "準備書面（１）"),
            (13, "令和8年10月20日"),
            (13, "東京地方裁判所民事部　御中"),
            (13, "原告訴訟代理人弁護士　架空花子"),
            (13, "第1　被告の主張に対する認否"),
            (12, "1　被告山田太郎（住所　東京都千代田区架空町1-2-3）は、"),
            (12, "原告に対し、令和7年4月1日付の業務委託契約を締結した。"),
            (12, "2　連絡先は電話03-1234-5678、メール"),
            (12, "taro.yamada@example.jpであると主張するが、否認する。"),
            (12, "3　原告株式会社サンプル商事の振込先は、架空銀行本店"),
            (12, "普通預金　口座番号1234567（〒100-0001）である。"),
            (13, "第2　原告の主張"),
            (12, "被告は、管理番号SMP2026Aの物件について、"),
            (12, "原告の承諾なく第三者に引き渡した。"),
        ],
        [
            (16, "表記のゆれ"),
            (13, "株式会社サンフル商事"),
            (13, "山田太朗"),
            (13, "株式会社サンプル商事"),
        ],
    ]
    for lines in pages:
        page = doc.new_page(width=595, height=842)
        y = 64
        for size, text in lines:
            page.insert_text((56, y), text, fontname="japan", fontsize=size)
            y += size + 16
    doc.save(path)
    doc.close()


def grab(window: MainWindow, path: Path) -> None:
    window.repaint()
    QApplication.processEvents()
    pixmap = window.grab()
    pixmap.save(str(path))
    print(path.name, pixmap.width(), pixmap.height())


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
    out.mkdir(parents=True, exist_ok=True)
    demo = Path("/tmp/ekisui-shot-demo.pdf")
    build_demo(demo)
    app = QApplication([])
    for candidate in ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",):
        if Path(candidate).exists():
            QFontDatabase.addApplicationFont(candidate)
    font = QFont("WenQuanYi Micro Hei")
    font.setPixelSize(14)
    app.setFont(font)
    app.setStyleSheet(QSS)
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    QApplication.processEvents()
    grab(window, out / "01-empty.png")

    window.open_path(str(demo))
    window.session.suggest()
    page = window.session.document.pages[0]
    flagged = []
    for index, line in enumerate(page.lines):
        if index == 8:
            flagged.append(replace(line, confidence=0.62, source=TextSource.OCR))
        else:
            flagged.append(line)
    pages = list(window.session.document.pages)
    pages[0] = replace(page, lines=tuple(flagged))
    window.session.document = replace(window.session.document, pages=tuple(pages))
    window.refresh()
    window._fit_width()
    QApplication.processEvents()
    grab(window, out / "03-candidates.png")

    window.btn_ocr_menu.setChecked(True)
    window._toggle_ocr_pop()
    QApplication.processEvents()
    grab(window, out / "02a-ocr-settings.png")
    window.ocr_pop.hide()
    window.btn_ocr_menu.setChecked(False)

    window.ocr_running = True
    window.card.show()
    window.apply_progress(1, 2, "+0.6°")
    window.refresh()
    QApplication.processEvents()
    grab(window, out / "02-ocr-progress.png")
    window.ocr_running = False
    window.card.hide()
    window.refresh()

    window._show_tab(1)
    window.tab_group.buttons()[1].setChecked(True)
    QApplication.processEvents()
    grab(window, out / "04-replace-table.png")

    window._show_tab(2)
    window.tab_group.buttons()[2].setChecked(True)
    line = next(item for item in window.session.document.pages[0].lines if item.confidence < 0.8)
    window._edit_line(line.id)
    QApplication.processEvents()
    grab(window, out / "05-ocr-fix.png")
    window.canvas.cancel_edit()

    window._show_tab(0)
    window.tab_group.buttons()[0].setChecked(True)
    window._open_confirm()
    QApplication.processEvents()
    grab(window, out / "06-confirm.png")
    window.shade.hide()

    window._open_save()
    QApplication.processEvents()
    grab(window, out / "07-save.png")

    dest = Path("/tmp/ekisui-shot-墨消し.pdf")
    window.save_path.setText(str(dest))
    window._save()
    QApplication.processEvents()
    grab(window, out / "09-verify-ok.png")
    window.shade.hide()

    report = verify_pdf(str(demo), window.session.groups, window.session.settings, window.session.table, False)
    window.show_report(report)
    QApplication.processEvents()
    grab(window, out / "08-verify-ng.png")
    print("verify passed on saved file screenshot; leftovers on source", len(report.leftovers))


if __name__ == "__main__":
    main()
