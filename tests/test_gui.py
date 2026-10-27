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
    window.session.suggest()
    window.refresh()
    canonical = {group.canonical for group in window.session.groups}
    assert "株式会社サンプル商事" in canonical
    assert "山田太郎" in canonical
    window.close()
    app.processEvents()
