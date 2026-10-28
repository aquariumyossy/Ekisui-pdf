"""Confirmation burns redactions into the session. Later actions cannot bring them back."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pymupdf
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from ekisui.domain.session import Session
from ekisui.domain.types import Rect, SaveOptions, Settings
from ekisui.pdf.document import open_document, recognize
from ekisui.pdf.export import export_pdf


def _native_pdf(path: Path) -> None:
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((72, 80), "山田太郎", fontname="japan", fontsize=16)
    first.insert_text((72, 220), "控える文章", fontname="japan", fontsize=16)
    first.insert_text((72, 360), "二回目の範囲", fontname="japan", fontsize=16)
    second = document.new_page()
    second.insert_text((72, 80), "次のページです", fontname="japan", fontsize=16)
    document.save(path)
    document.close()


def _dark_pdf(path: Path, page_index: int, rect: Rect) -> float:
    opened = pymupdf.open(path)
    try:
        page = opened[page_index]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False, colorspace=pymupdf.csRGB)
        return _dark_samples(
            pixmap.samples,
            pixmap.width,
            pixmap.height,
            pixmap.n,
            pixmap.stride,
            float(page.rect.width),
            float(page.rect.height),
            rect,
        )
    finally:
        opened.close()


def _dark_qpix(pixmap, page_w: float, page_h: float, rect: Rect) -> float:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
    scale_x = image.width() / page_w
    scale_y = image.height() / page_h
    x0 = max(0, int(rect.x0 * scale_x))
    y0 = max(0, int(rect.y0 * scale_y))
    x1 = min(image.width(), int(rect.x1 * scale_x))
    y1 = min(image.height(), int(rect.y1 * scale_y))
    dark = 0
    total = 0
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            if (image.pixel(x, y) & 0xFF) < 40:
                dark += 1
            total += 1
    assert total > 0
    return dark / total


def _dark_samples(samples, width, height, channels, stride, page_w, page_h, rect: Rect) -> float:
    scale_x = width / page_w
    scale_y = height / page_h
    x0 = max(0, int(rect.x0 * scale_x))
    y0 = max(0, int(rect.y0 * scale_y))
    x1 = min(width, int(rect.x1 * scale_x))
    y1 = min(height, int(rect.y1 * scale_y))
    dark = 0
    total = 0
    for y in range(y0, y1, 2):
        row = y * stride
        for x in range(x0, x1, 2):
            if samples[row + x * channels] < 40:
                dark += 1
            total += 1
    assert total > 0
    return dark / total


def _text(path: Path) -> str:
    opened = pymupdf.open(path)
    try:
        raw = "".join(page.get_text() for page in opened)
    finally:
        opened.close()
    return "".join(raw.split())


def _line(document, snippet: str):
    for page in document.pages:
        for line in page.lines:
            if snippet in line.text:
                return line
    raise AssertionError(snippet)


def test_confirm_then_new_range_keeps_the_first_redaction(tmp_path):
    from ekisui.gui.window import MainWindow

    path = tmp_path / "brief.pdf"
    _native_pdf(path)
    original = path.read_bytes()
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.open_path(str(path))
    assert window.session is not None
    secret = _line(window.session.document, "山田太郎")
    keep = _line(window.session.document, "控える文章")
    second = _line(window.session.document, "二回目の範囲")
    before = _dark_pdf(path, 0, secret.bbox)

    window._on_region(0, secret.bbox.pad(1, 1))
    window._confirm()
    assert window.session.confirmed is True
    assert window.session.committed
    assert window.preview is False
    baked = Path(window.session.document.working_path or "")
    assert baked.is_file()
    assert path.read_bytes() == original
    assert "山田太郎" not in _text(baked)
    assert "控える文章" in _text(baked)
    assert "次のページです" in _text(baked)
    burned = window.session.committed[0].hits[0].hit.bbox
    after = _dark_pdf(baked, 0, burned)
    assert before < 0.5
    assert after > 0.75
    assert "山田太郎" not in "".join(line.text for page in window.session.document.pages for line in page.lines)
    view = _dark_qpix(window._page_pixmap(0), window.session.document.pages[0].width, window.session.document.pages[0].height, burned)
    assert view > 0.75

    window._on_region(0, second.bbox.pad(1, 1))
    assert window.session.confirmed is False
    assert "山田太郎" not in _text(baked)
    assert _dark_pdf(baked, 0, burned) > 0.75
    assert not any("山田太郎" in group.canonical for group in window.session.groups)

    window._set_zoom(1.5)
    window._goto(1)
    window._goto(0)
    window._show_tab(0)
    window._show_tab(2)
    window.session.correct_line(keep.id, "控える文章")
    window._rescan()
    assert "山田太郎" not in _text(Path(window.session.document.working_path))
    assert _dark_qpix(
        window._page_pixmap(0),
        window.session.document.pages[0].width,
        window.session.document.pages[0].height,
        burned,
    ) > 0.75
    assert "次のページです" in "".join(line.text for line in window.session.document.pages[1].lines)

    window._confirm()
    window._open_save()
    window._save()
    app.processEvents()
    saved = next(tmp_path.glob("brief_Masked*.pdf"))
    saved_text = _text(saved)
    assert "山田太郎" not in saved_text
    assert "二回目の範囲" not in saved_text
    assert "控える文章" in saved_text
    assert "次のページです" in saved_text
    assert _dark_pdf(saved, 0, burned) > 0.75
    assert path.read_bytes() == original
    window.close()
    app.processEvents()


def test_ocr_finished_opens_the_fix_tab(tmp_path):
    from ekisui.gui.window import MainWindow

    path = tmp_path / "scan-name.pdf"
    _native_pdf(path)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.open_path(str(path))
    window._ocr_done(window.session.document)
    assert window.ocr_panel.isHidden() is False
    assert window.candidates.isHidden() is True
    assert window.tab_group.buttons()[2].isChecked()
    window.close()
    app.processEvents()


def test_recognize_opens_the_baked_pdf_not_the_original(tmp_path, monkeypatch):
    path = tmp_path / "brief.pdf"
    _native_pdf(path)
    session = Session(open_document(path), Settings())
    secret = _line(session.document, "山田太郎")
    session.add_region(0, secret.bbox.pad(1, 1))
    session.commit_redactions(tmp_path, True)
    seen: list[str] = []

    def stop(target, *args, **kwargs):
        seen.append(str(target))
        raise RuntimeError("stop")

    assert "山田太郎" not in _text(Path(session.document.working_path))
    monkeypatch.setattr("ekisui.pdf.document.pymupdf.open", stop)
    try:
        recognize(session.document, Settings(), None, tmp_path)
    except RuntimeError as exc:
        assert str(exc) == "stop"
    else:
        raise AssertionError("recognize did not open a PDF")
    assert seen == [session.document.working_path]


def test_second_bake_on_a_scan_keeps_the_first_pixels(tmp_path):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (480, 280), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 30, 200, 80), fill=(180, 180, 180))
    draw.rectangle((40, 140, 220, 190), fill=(180, 180, 180))
    png = tmp_path / "page.png"
    image.save(png)
    source = tmp_path / "scan.pdf"
    sheet = pymupdf.open()
    page = sheet.new_page(width=480, height=280)
    page.insert_image(page.rect, filename=str(png))
    sheet.save(source)
    sheet.close()

    from ekisui.domain.types import Document, Page, PageKind, TextLine, TextSource

    lines = (
        TextLine("a", 0, "山田太郎", Rect(40, 30, 200, 80), 0.99, TextSource.OCR),
        TextLine("b", 0, "二回目の範囲", Rect(40, 140, 220, 190), 0.99, TextSource.OCR),
        TextLine("c", 0, "控える文章", Rect(40, 220, 200, 260), 0.99, TextSource.OCR),
    )
    document = Document(
        str(source),
        (
            Page(
                index=0,
                width=480,
                height=280,
                kind=PageKind.SCANNED,
                lines=lines,
                image_path=str(png),
                dpi=72,
                source_index=0,
            ),
        ),
    )
    session = Session(document, Settings())
    session.add_region(0, Rect(40, 30, 200, 80))
    session.commit_redactions(tmp_path, False)
    burned = session.document.pages[0].image_path
    assert burned is not None
    assert _dark_pdf(Path(session.document.working_path), 0, Rect(40, 30, 200, 80)) > 0.75
    assert "山田太郎" not in "".join(line.text for line in session.document.pages[0].lines)
    session.add_region(0, Rect(40, 140, 220, 190))
    session.commit_redactions(tmp_path, False)
    options = SaveOptions(align_box_width=False, strip_metadata=True, export_log=False, export_replacement_table=False)
    dest = tmp_path / "out.pdf"
    export_pdf(session.document, [], dest, options, Settings(), archived=session.committed)
    assert "山田太郎" not in _text(dest)
    assert "二回目の範囲" not in _text(dest)
    assert "控える文章" in _text(dest)
    assert _dark_pdf(dest, 0, Rect(40, 30, 200, 80)) > 0.75
    assert _dark_pdf(dest, 0, Rect(40, 140, 220, 190)) > 0.75
