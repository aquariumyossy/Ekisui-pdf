"""The window opens a text PDF and lists candidates. No display is required."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("HF_HUB_OFFLINE", "1")


def test_window_suggests_from_a_text_pdf(tmp_path) -> None:
    import pymupdf
    from PySide6.QtWidgets import QApplication

    from ekisui.gui.window import MainWindow

    path = tmp_path / "brief.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 80), "株式会社サンプル商事", fontname="japan", fontsize=14)
    page.insert_text((72, 110), "被告　山田太郎", fontname="japan", fontsize=14)
    page.insert_text((72, 140), "電話03-1234-5678", fontname="japan", fontsize=14)
    document.save(path)
    document.close()

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.open_path(str(path))
    assert window.session is not None
    assert window.session.groups == []
    assert window.ocr_ran is False
    window.session.suggest()
    window.refresh()
    canonical = {group.canonical for group in window.session.groups}
    assert "株式会社サンプル商事" in canonical
    assert "山田太郎" in canonical
    window.close()
    app.processEvents()


def test_toolbar_and_mask_save_flow(tmp_path) -> None:
    import pymupdf
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget

    from ekisui.gui import window as window_mod
    from ekisui.gui.window import MainWindow
    from ekisui.pdf.document import pages_need_ocr
    from ekisui.pdf.export import unique_destination

    path = tmp_path / "brief.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 80), "株式会社サンプル商事", fontname="japan", fontsize=14)
    page.insert_text((72, 110), "被告　山田太郎", fontname="japan", fontsize=14)
    page.insert_text((72, 140), "電話03-1234-5678", fontname="japan", fontsize=14)
    document.save(path)
    document.close()

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    bar = window.findChild(QWidget, "toolbar")
    labels = []
    layout = bar.layout()
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if isinstance(widget, QPushButton):
            labels.append(widget.text())
    assert labels == ["開く", "OCR実行", "▾", "マスキング実行", "範囲で選ぶ", "保存", "設定"]
    assert window.btn_ocr.toolTip() == "スキャン画像の文字を読み取り、検索できるPDFにします。マスキングはしません。文字データのあるPDFと、Wordから変換したPDFには使いません。"
    assert window.btn_mask.toolTip() == "開いているPDFから、個人情報などのマスキング候補を自動で探します。Wordは変換したPDFが対象です。"
    assert window.btn_region.toolTip() == "ページ上をドラッグして、マスキングする範囲を選べます。"
    assert window.btn_confirm.text() == "確定…"
    assert window.findChildren(QPushButton, "自動候補") == []

    window.open_path(str(path))
    assert window.btn_save.isEnabled() is False
    assert window.btn_save.toolTip() == "読み取りもマスキングの確定もまだないので、保存できません。"
    started = []
    original_ocr = window.start_ocr
    original_need = window_mod.pages_need_ocr
    window.start_ocr = lambda: started.append("ocr")
    window_mod.pages_need_ocr = lambda _document: True
    try:
        window.start_mask()
    finally:
        window_mod.pages_need_ocr = original_need
    assert original_need is pages_need_ocr
    assert started == ["ocr"]
    assert window._after_ocr == "mask"
    window.start_ocr = original_ocr

    window._after_ocr = "mask"
    window._ocr_done(window.session.document)
    assert window.ocr_ran is True
    assert any("山田太郎" in group.canonical for group in window.session.groups)

    window._open_save()
    buttons = {button.text(): button for button in window.shade.findChildren(QPushButton)}
    assert buttons["OCRだけ保存する"].isEnabled()
    buttons["OCRだけ保存する"].click()
    app.processEvents()
    assert window.save_path.text().endswith("brief_OCR.pdf")
    window._save()
    app.processEvents()
    saved = pymupdf.open(tmp_path / "brief_OCR.pdf")
    saved_text = "".join(item.get_text() for item in saved)
    saved.close()
    assert "山田太郎" in saved_text
    assert "03-1234-5678" in saved_text

    window.shade.hide()
    window._open_save()
    buttons = {button.text(): button for button in window.shade.findChildren(QPushButton)}
    buttons["確定に進む"].click()
    app.processEvents()
    confirm = {button.text(): button for button in window.shade.findChildren(QPushButton)}
    confirm["確定する"].click()
    assert window.session.confirmed is True

    taken = tmp_path / "brief_Masked.pdf"
    taken.write_bytes(b"taken")
    (tmp_path / "brief_Masked_墨消し記録.csv").write_text("taken", encoding="utf-8")
    window._open_save()
    assert window.save_path.text().endswith("brief_Masked (2).pdf")
    window._save()
    app.processEvents()
    masked = pymupdf.open(tmp_path / "brief_Masked (2).pdf")
    masked_text = "".join(item.get_text() for item in masked)
    masked.close()
    assert "太郎" not in masked_text
    assert "03-1234-5678" not in masked_text
    assert (tmp_path / "brief_Masked (2)_墨消し記録.csv").exists()

    occupied = tmp_path / "plain.pdf"
    occupied.write_bytes(b"x")
    assert unique_destination(occupied).name == "plain (2).pdf"
    window.close()
    app.processEvents()
