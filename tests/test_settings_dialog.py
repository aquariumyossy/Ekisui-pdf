"""Settings dialog wording. Ranges and stored values stay the same."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from ekisui.domain.types import Settings
from ekisui.gui.window import (
    SETTINGS_ALIGN_LABEL,
    SETTINGS_ALIGN_TIP,
    SETTINGS_BUTTON_TIP,
    SETTINGS_FUZZY_HIGH,
    SETTINGS_FUZZY_LOW,
    SETTINGS_FUZZY_TIP,
    SETTINGS_HEADING_BOX,
    SETTINGS_HEADING_READ,
    SETTINGS_REVIEW_LABEL,
    SETTINGS_REVIEW_TIP,
    SETTINGS_TITLE,
    MainWindow,
    fuzzy_caption,
)


def _labels(window: MainWindow) -> dict[str, QLabel]:
    found = {}
    for label in window.dialog.findChildren(QLabel):
        found[label.text()] = label
    return found


def _assert_fully_visible(window: MainWindow, label: QLabel) -> None:
    rect = label.fontMetrics().boundingRect(
        0,
        0,
        max(label.width(), 1),
        4000,
        int(Qt.TextFlag.TextWordWrap),
        label.text(),
    )
    assert label.height() + 2 >= rect.height(), (label.text(), label.width(), label.height(), rect.height())
    origin = label.mapTo(window.dialog, QPoint(0, 0))
    assert origin.x() >= 0
    assert origin.y() >= 0
    assert origin.x() + label.width() <= window.dialog.width() + 1
    assert origin.y() + label.height() <= window.dialog.height() + 1


def test_settings_dialog_wording_keeps_ranges_and_values() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    app.processEvents()
    assert window.btn_settings.toolTip() == SETTINGS_BUTTON_TIP
    assert window.settings == Settings()

    window._open_settings()
    app.processEvents()
    labels = _labels(window)
    assert labels[SETTINGS_TITLE].text() == "マスキングの設定"
    assert labels[SETTINGS_HEADING_READ].text() == "読み取りの誤りを見込んで探す"
    assert labels[SETTINGS_HEADING_BOX].text() == "マスキング枠"
    assert labels[fuzzy_caption(60)].text() == "少し違う表記も同じ語句とみなす（60%）"
    assert labels[SETTINGS_FUZZY_LOW].text() == "幅広く拾う"
    assert labels[SETTINGS_FUZZY_HIGH].text() == "厳密"
    assert labels[SETTINGS_REVIEW_LABEL].text() == "読み取りの自信がこの％未満の行を要確認にする"
    assert labels[SETTINGS_ALIGN_LABEL].text() == "短い枠を広げる最小の幅（文字数）"
    tips = [button.toolTip() for button in window.dialog.findChildren(QPushButton) if button.objectName() == "info"]
    assert tips == [SETTINGS_FUZZY_TIP, SETTINGS_REVIEW_TIP, SETTINGS_ALIGN_TIP]
    assert SETTINGS_FUZZY_TIP == (
        "OCRは『山田』を『山出』と読むなど、読み誤ることがあります。"
        "そうした少し違う表記も同じ語句として見つけ、マスキングします。"
        "％を下げるほど違いの大きい表記まで拾い、消し残りは減りますが、関係ない語句も増えます。"
        "4文字以上の語句に効きます。2〜3文字の語句は、紛らわしい1文字の違いだけを同じとみなします。"
    )
    assert SETTINGS_REVIEW_TIP == "OCRの自信が低い行に赤い枠を付け、目で確かめる対象にします。数字を上げると要確認の行が増えます。手で直した行は対象外です。"
    assert SETTINGS_ALIGN_TIP == (
        "短い語句の黒塗りや置換の枠を、この文字数まで広げます。"
        "枠の長さから元の語句を推測されにくくするためです。長い枠は縮めません。"
        "保存時の『枠の幅をそろえる』がオンのときに効きます。"
    )
    assert SETTINGS_BUTTON_TIP == "マスキングの設定です。読み取りの誤りがあっても同じ語句を見つける度合いと、枠の幅を変えます。"
    assert window.fuzzy.minimum() == 50
    assert window.fuzzy.maximum() == 90
    assert window.fuzzy.value() == 60
    assert window.review.minimum() == 50
    assert window.review.maximum() == 99
    assert window.review.value() == 80
    assert window.review.suffix() == "%"
    assert window.align.minimum() == 1
    assert window.align.maximum() == 12
    assert window.align.value() == 5
    assert window.dialog.width() == 720
    low = labels[SETTINGS_FUZZY_LOW]
    high = labels[SETTINGS_FUZZY_HIGH]
    assert low.mapTo(window.dialog, QPoint(0, 0)).x() < window.fuzzy.mapTo(window.dialog, QPoint(0, 0)).x()
    assert window.fuzzy.mapTo(window.dialog, QPoint(window.fuzzy.width(), 0)).x() <= high.mapTo(window.dialog, QPoint(0, 0)).x()
    for text in (
        SETTINGS_TITLE,
        SETTINGS_HEADING_READ,
        SETTINGS_HEADING_BOX,
        fuzzy_caption(60),
        SETTINGS_FUZZY_LOW,
        SETTINGS_FUZZY_HIGH,
        SETTINGS_REVIEW_LABEL,
        SETTINGS_ALIGN_LABEL,
    ):
        _assert_fully_visible(window, labels[text])

    window.fuzzy.setValue(50)
    assert window.fuzzy_label.text() == "少し違う表記も同じ語句とみなす（50%）"
    window.fuzzy.setValue(90)
    assert window.fuzzy_label.text() == "少し違う表記も同じ語句とみなす（90%）"
    window.fuzzy.setValue(70)
    window.review.setValue(91)
    window.align.setValue(8)
    window._apply_settings()
    assert window.settings.fuzzy_threshold == 0.70
    assert window.settings.review_below == 0.91
    assert window.settings.align_chars == 8
    assert window.settings.deskew is True
    assert window.settings.ocr_dpi == 200

    window._open_settings()
    app.processEvents()
    assert window.fuzzy.value() == 70
    assert window.review.value() == 91
    assert window.align.value() == 8
    assert window.fuzzy_label.text() == fuzzy_caption(70)
    window.shade.hide()
    window._clear_dialog()
    assert window.dialog.width() == 540
    window.close()
    app.processEvents()


def _inside_window(window: MainWindow, widget) -> None:
    origin = widget.mapTo(window, QPoint(0, 0))
    assert origin.x() >= -1
    assert origin.y() >= -1
    assert origin.x() + widget.width() <= window.width() + 1
    assert origin.y() + widget.height() <= window.height() + 1


def test_settings_dialog_stays_inside_a_narrow_window() -> None:
    from PySide6.QtGui import QFont, QFontDatabase

    from ekisui.gui.theme import QSS

    app = QApplication.instance() or QApplication([])
    previous_sheet = app.styleSheet()
    font_path = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
    if os.path.exists(font_path):
        QFontDatabase.addApplicationFont(font_path)
        font = QFont("WenQuanYi Micro Hei")
        font.setPixelSize(14)
        app.setFont(font)
    app.setStyleSheet(QSS)
    window = MainWindow()
    try:
        window.resize(1280, 800)
        window.show()
        app.processEvents()
        window._open_settings()
        app.processEvents()
        assert window.dialog.width() == 720
        assert window.fuzzy_label.height() < window.fuzzy_label.fontMetrics().lineSpacing() * 2
        assert window.review.width() < 160
        assert window.align.width() < 160
        hint = window.minimumSizeHint()
        window.resize(hint.width(), hint.height())
        app.processEvents()
        assert window.dialog.width() <= window.width() - 8
        _inside_window(window, window.dialog)
        high = next(label for label in window.dialog.findChildren(QLabel) if label.text() == SETTINGS_FUZZY_HIGH)
        apply = next(button for button in window.dialog.findChildren(QPushButton) if button.text() == "適用")
        _inside_window(window, high)
        _inside_window(window, apply)
        _assert_fully_visible(window, window.fuzzy_label)
        _assert_fully_visible(window, window.review_label)
        _assert_fully_visible(window, window.align_label)
        assert window.fuzzy.value() == 60
        assert window.review.value() == 80
        assert window.align.value() == 5
        window.close()
        app.processEvents()
    finally:
        app.setStyleSheet(previous_sheet)
