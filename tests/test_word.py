"""Word files become a PDF through Microsoft Word. CI never launches Word."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pymupdf
import pytest

from ekisui.domain.session import Session
from ekisui.domain.types import SaveOptions, Settings
from ekisui.errors import WordConvertError
from ekisui.pdf.document import open_document, pdf_path
from ekisui.pdf.export import export_pdf
from ekisui.pdf.wordconvert import (
    _export_with_application,
    _strip_pdf_metadata,
    convert_word_to_pdf,
)


def _compact(path: Path) -> str:
    opened = pymupdf.open(path)
    try:
        return "".join("".join(page.get_text().split()) for page in opened)
    finally:
        opened.close()


def _wordish_pdf(path: Path) -> None:
    """Text in the places Word puts a header, a footer, and a text box."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 36), "山田太郎", fontname="japan", fontsize=12)
    page.insert_text((72, 220), "控える文章です", fontname="japan", fontsize=14)
    page.insert_textbox(pymupdf.Rect(72, 360, 420, 420), "佐藤花子", fontname="japan", fontsize=14)
    page.insert_text((72, 800), "03-1234-5678", fontname="japan", fontsize=12)
    document.set_metadata({"author": "WORD_AUTHOR"})
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 200, 180, 220), "uri": "mailto:secret@example.test"})
    document.save(path)
    document.close()


class _View:
    def __init__(self) -> None:
        self.RevisionsView = None
        self.ShowRevisionsAndComments = None
        self.ShowComments = None
        self.ShowInsertionsAndDeletions = None


class _Doc:
    def __init__(self) -> None:
        self.ActiveWindow = type("Window", (), {"View": _View()})()
        self.export_args = None
        self.closed = None
        self.saved = False

    def ExportAsFixedFormat(self, *args, **kwargs) -> None:
        self.export_args = args
        self.export_kwargs = kwargs

    def Close(self, **kwargs) -> None:
        self.closed = kwargs

    def Save(self) -> None:
        self.saved = True


class _Documents:
    def __init__(self, document: _Doc) -> None:
        self.document = document
        self.opened_args = None
        self.security_at_open = None

    def Open(self, *args, **kwargs):
        self.opened_args = args
        self.opened_kwargs = kwargs
        self.security_at_open = self.word.AutomationSecurity
        return self.document


class _Word:
    def __init__(self) -> None:
        self.Documents = _Documents(_Doc())
        self.Documents.word = self
        self.Visible = True
        self.DisplayAlerts = 1
        self.AutomationSecurity = 1


def test_export_asks_for_the_final_view_without_markup_or_properties(tmp_path):
    source = tmp_path / "契約.docx"
    source.write_bytes(b"original-bytes")
    word = _Word()
    _export_with_application(word, source, tmp_path / "out.pdf")
    assert word.Visible is False
    assert word.DisplayAlerts == 0
    assert word.Documents.security_at_open == 3
    opened = word.Documents.opened_args
    assert opened[0] == str(source)
    assert opened[2] is True
    assert opened[3] is False
    assert opened[4] == "ekisui"
    assert opened[14] is True
    export = word.Documents.document.export_args
    assert export[1] == 17
    assert export[7] == 0
    assert export[8] is False
    assert export[9] is False
    assert export[12] is False
    assert export[2] is False
    view = word.Documents.document.ActiveWindow.View
    assert view.RevisionsView == 0
    assert view.ShowRevisionsAndComments is False
    assert view.ShowComments is False
    assert word.Documents.document.closed == {"SaveChanges": 0}
    assert word.Documents.document.saved is False
    assert source.read_bytes() == b"original-bytes"


def test_convert_without_word_raises_in_japanese_and_keeps_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr("ekisui.pdf.wordconvert.sys.platform", "linux")
    source = tmp_path / "メモ.docx"
    source.write_bytes(b"do-not-touch")
    with pytest.raises(WordConvertError) as caught:
        convert_word_to_pdf(source, tmp_path / "work")
    assert "Word" in str(caught.value)
    assert source.read_bytes() == b"do-not-touch"


def test_converted_pdf_drops_the_author(tmp_path):
    path = tmp_path / "from-word.pdf"
    _wordish_pdf(path)
    _strip_pdf_metadata(path)
    opened = pymupdf.open(path)
    try:
        assert (opened.metadata or {}).get("author") in {None, ""}
        assert list(opened[0].get_links()) == []
        raw = path.read_bytes()
    finally:
        opened.close()
    assert b"WORD_AUTHOR" not in raw
    assert b"secret@example.test" not in raw


def test_redaction_removes_header_footer_and_textbox_text(tmp_path):
    path = tmp_path / "wordish.pdf"
    _wordish_pdf(path)
    session = Session(open_document(path), Settings())
    for phrase in ("山田太郎", "佐藤花子", "03-1234-5678"):
        found = session.add_phrase(phrase)
        assert found is not None, phrase
    session.commit_redactions(tmp_path, False)
    baked = _compact(Path(pdf_path(session.document)))
    assert "山田太郎" not in baked
    assert "佐藤花子" not in baked
    assert "03-1234-5678" not in baked
    assert "控える文章です" in baked
    dest = tmp_path / "out_Masked.pdf"
    export_pdf(
        session.document,
        [],
        dest,
        SaveOptions(align_box_width=False, strip_metadata=True, export_log=False, export_replacement_table=False),
        Settings(),
        prior_boxes=session.burned_boxes,
    )
    saved = _compact(dest)
    raw = dest.read_bytes()
    for secret in ("山田太郎", "佐藤花子", "03-1234-5678"):
        assert secret not in saved
        assert secret.encode("utf-8") not in raw
        assert secret.encode("utf-16-be") not in raw
    assert "控える文章です" in saved
    assert path.read_bytes()  # the sample file is still there


def test_open_word_loads_the_converted_pdf_and_saves_beside_it(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from ekisui.gui import window as window_mod
    from ekisui.gui.window import MainWindow

    sample = tmp_path / "wordish.pdf"
    _wordish_pdf(sample)
    docx = tmp_path / "契約.docx"
    docx.write_bytes(b"original-docx")

    def fake_convert(source, work_dir):
        assert Path(source).resolve() == docx.resolve()
        dest = Path(work_dir) / "契約.pdf"
        dest.write_bytes(sample.read_bytes())
        return dest

    monkeypatch.setattr(window_mod, "convert_word_to_pdf", fake_convert)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.open_path(str(docx))
    assert window.session is not None
    assert window.session.document.source_path.endswith("契約.docx")
    assert Path(pdf_path(window.session.document)).suffix == ".pdf"
    assert "山田太郎" in _compact(Path(pdf_path(window.session.document)))
    assert "Wordから変換" in window.kind_label.text()
    assert docx.read_bytes() == b"original-docx"
    for phrase in ("山田太郎", "佐藤花子", "03-1234-5678"):
        assert window.session.add_phrase(phrase) is not None
    window._confirm()
    window._open_save()
    assert window.save_path.text().endswith("契約_Masked.pdf")
    window._save()
    app.processEvents()
    saved = _compact(tmp_path / "契約_Masked.pdf")
    assert "山田太郎" not in saved
    assert "佐藤花子" not in saved
    assert "03-1234-5678" not in saved
    assert "控える文章です" in saved
    assert docx.read_bytes() == b"original-docx"
    window.close()
    app.processEvents()


def test_word_conversion_failure_does_not_open_a_document(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from ekisui.gui import window as window_mod
    from ekisui.gui.window import MainWindow

    docx = tmp_path / "失敗.docx"
    docx.write_bytes(b"keep")
    def fail(*_args, **_kwargs):
        raise WordConvertError("Microsoft Word が見つかりません。")

    monkeypatch.setattr(window_mod, "convert_word_to_pdf", fail)
    shown: list[str] = []
    monkeypatch.setattr(window_mod.QMessageBox, "warning", lambda *_args: shown.append(str(_args[-1])))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.open_path(str(docx))
    assert window.session is None
    assert shown and "Word" in shown[0]
    assert docx.read_bytes() == b"keep"
    window.close()
    app.processEvents()
