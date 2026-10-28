"""PP-OCRv5 on a generated scan: searchable text layer, deskew label, upside-down page."""

import io
import os
import time
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

from ekisui.domain.normalize import strict_text
from ekisui.domain.session import Session
from ekisui.domain.types import Action, PageKind, Rect, SaveOptions, Settings, TextSource
from ekisui.pdf.document import open_document, recognize
from ekisui.pdf.export import export_pdf
from ekisui.pdf.ocr_engine import PpOcrV5
from ekisui.pdf.verify import verify_pdf

from fonts import cjk_font
from test_redact import _dark_fraction


def _render_dark(doc: pymupdf.Document, page_index: int, rect: Rect) -> float:
    pixmap = doc[page_index].get_pixmap(dpi=72, alpha=False)
    samples = pixmap.samples
    channels = pixmap.n
    x0 = max(0, int(rect.x0))
    y0 = max(0, int(rect.y0))
    x1 = min(pixmap.width, int(rect.x1))
    y1 = min(pixmap.height, int(rect.y1))
    dark = 0
    total = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            total += 1
            if samples[(y * pixmap.width + x) * channels] < 80:
                dark += 1
    assert total > 0
    return dark / total


def _page_image(lines: list[str], rotate: int) -> Image.Image:
    font = ImageFont.truetype(cjk_font(), 42)
    image = Image.new("RGB", (1100, 280), "white")
    draw = ImageDraw.Draw(image)
    y = 40
    for line in lines:
        draw.text((48, y), line, font=font, fill=(0, 0, 0))
        y += 90
    if rotate:
        image = image.rotate(rotate, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    return image


def _pdf_of(images: list[Image.Image], path: Path) -> None:
    doc = pymupdf.open()
    for image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        page = doc.new_page(width=image.width, height=image.height)
        page.insert_image(page.rect, stream=buffer.getvalue())
    doc.save(path)
    doc.close()


def test_scanned_pdf_gains_a_searchable_layer(tmp_path: Path) -> None:
    straight = _page_image(["株式会社サンプル商事", "山田太郎"], rotate=0)
    tilted = straight.rotate(3, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    upside = _page_image(["連絡先は山田花子"], rotate=180)
    source = tmp_path / "scan.pdf"
    _pdf_of([tilted, upside], source)

    opened = open_document(source)
    assert all(page.kind == PageKind.SCANNED for page in opened.pages)

    engine = PpOcrV5()
    started = time.perf_counter()
    recognized = recognize(opened, Settings(ocr_dpi=72, deskew=True), engine, tmp_path / "work")
    elapsed = time.perf_counter() - started
    (tmp_path / "seconds.txt").write_text(f"{elapsed:.2f} for {len(recognized.pages)} pages\n", encoding="utf-8")

    page0 = "".join(line.text for line in recognized.pages[0].lines)
    assert "サンプル商事" in strict_text(page0)
    assert "山田" in strict_text(page0)
    assert recognized.pages[0].correction_label
    assert "°" in recognized.pages[0].correction_label

    page1 = "".join(line.text for line in recognized.pages[1].lines)
    assert "山田" in strict_text(page1)
    assert recognized.pages[1].rotation == 180
    assert recognized.pages[1].correction_label and "180" in recognized.pages[1].correction_label

    dest = tmp_path / "out.pdf"
    export_pdf(recognized, [], dest, SaveOptions(export_log=False))
    saved = pymupdf.open(dest)
    try:
        text = strict_text("".join(page.get_text() for page in saved))
    finally:
        saved.close()
    assert "サンプル商事" in text
    assert "山田太郎" in text or "山田" in text


def test_bad_text_layer_on_a_scan_is_replaced(tmp_path: Path) -> None:
    font = ImageFont.truetype(cjk_font(), 42)
    image = Image.new("RGB", (1100, 280), "white")
    draw = ImageDraw.Draw(image)
    draw.text((48, 40), "株式会社サンプル商事", font=font, fill=0)
    draw.text((48, 140), "山田太郎", font=font, fill=0)
    image = image.rotate(3, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    source = tmp_path / "mfp.pdf"
    decoy = "旧文字層だけにある誤読ダミーQQQQです。画像にはありません。"
    doc = pymupdf.open()
    page = doc.new_page(width=image.width, height=image.height)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    page.insert_text((36, 28), decoy, fontname="japan", fontsize=11, render_mode=3)
    doc.save(source)
    doc.close()

    opened = open_document(source)
    assert opened.pages[0].kind == PageKind.SCANNED
    recognized = recognize(opened, Settings(ocr_dpi=72, deskew=True), PpOcrV5(), tmp_path / "work")
    layer = "".join(line.text for line in recognized.pages[0].lines)
    assert "サンプル" in strict_text(layer)
    assert "QQQQ" not in layer
    assert recognized.pages[0].image_path
    assert recognized.pages[0].correction_label

    dest = tmp_path / "mfp-out.pdf"
    export_pdf(recognized, [], dest, SaveOptions(export_log=False, strip_metadata=True))
    saved = pymupdf.open(dest)
    try:
        text = "".join(page.get_text() for page in saved)
    finally:
        saved.close()
    assert "サンプル" in strict_text(text)
    assert "QQQQ" not in text
    assert "誤読ダミー" not in text


def test_hits_from_the_old_layer_are_redone_after_ocr(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    font = ImageFont.truetype(cjk_font(), 48)
    image = Image.new("RGB", (1100, 360), "white")
    ImageDraw.Draw(image).text((48, 180), "山田太郎", font=font, fill=0)
    image = image.rotate(3, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    source = tmp_path / "layer.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=image.width, height=image.height)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    page.insert_text((36, 28), "山田太郎", fontname="japan", fontsize=11, render_mode=3)
    page.insert_text((36, 48), "誤読ダミーQQQQ", fontname="japan", fontsize=11, render_mode=3)
    doc.save(source)
    doc.close()

    opened = open_document(source)
    assert opened.pages[0].kind == PageKind.SCANNED
    recognized = recognize(opened, Settings(ocr_dpi=72, deskew=True), PpOcrV5(), tmp_path / "work")
    assert any("太郎" in line.text for line in recognized.pages[0].lines)

    stale_session = Session(opened, Settings())
    assert stale_session.add_phrase("山田太郎") is not None
    stale_session.document = recognized
    stale_path = tmp_path / "stale.pdf"
    options = SaveOptions(export_log=False, strip_metadata=True, align_box_width=False)
    export_pdf(recognized, stale_session.groups, stale_path, options, stale_session.settings)

    from PySide6.QtWidgets import QApplication

    from ekisui.gui.window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.open_path(str(source))
    assert window.ocr_label.text() == "未読取"
    assert window.session.add_phrase("山田太郎") is not None
    old_y = window.session.groups[0].hits[0].hit.bbox.y0
    window._ocr_done(recognized)
    assert window.ocr_label.text() == "OCR済み"
    group = next(item for item in window.session.groups if item.hits and "山田" in item.canonical)
    group.action = Action.BLACKOUT
    name_rect = next(hit.hit.bbox for hit in group.included_hits() if "太" in hit.hit.surface or "郎" in hit.hit.surface)
    assert name_rect.y0 > old_y + 40
    fresh_path = tmp_path / "fresh.pdf"
    export_pdf(window.session.document, [group], fresh_path, options, window.session.settings)

    probe = pymupdf.open()
    probe_page = probe.new_page(width=recognized.pages[0].width, height=recognized.pages[0].height)
    probe_page.insert_image(probe_page.rect, filename=recognized.pages[0].image_path)
    probe_path = tmp_path / "probe.pdf"
    probe.save(probe_path)
    probe.close()
    before_doc = pymupdf.open(probe_path)
    try:
        before_dark = _dark_fraction(before_doc, 0, name_rect)
    finally:
        before_doc.close()

    stale = pymupdf.open(stale_path)
    fresh = pymupdf.open(fresh_path)
    try:
        stale_dark = _dark_fraction(stale, 0, name_rect)
        fresh_dark = _dark_fraction(fresh, 0, name_rect)
        covered = _render_dark(fresh, 0, name_rect)
        fresh_text = "".join(item.get_text() for item in fresh)
        stale_text = "".join(item.get_text() for item in stale)
    finally:
        stale.close()
        fresh.close()
        window.close()
        app.processEvents()
    assert "QQQQ" not in fresh_text
    # Saved glyphs are one text object each, so extractors break the name with newlines.
    assert "太郎" in "".join(stale_text.split())
    assert "太郎" not in "".join(fresh_text.split())
    assert before_dark > 0.05
    assert stale_dark > before_dark * 0.7
    assert fresh_dark < before_dark * 0.35
    assert covered > 0.85


def _red_bbox(path: Path) -> Rect:
    image = np.array(Image.open(path))
    red = (image[:, :, 0] > 150) & (image[:, :, 1] < 80) & (image[:, :, 2] < 80)
    ys, xs = np.where(red)
    assert len(xs) > 0
    return Rect(float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))


def _iou(left: Rect, right: Rect) -> float:
    overlap = left.intersection(right)
    if overlap is None:
        return 0.0
    return overlap.area() / (left.area() + right.area() - overlap.area())


def test_dragged_region_follows_the_straightened_scan(tmp_path: Path) -> None:
    font = ImageFont.truetype(cjk_font(), 42)
    image = Image.new("RGB", (1000, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((640, 48, 860, 200), fill=(200, 0, 0))
    draw.text((48, 250), "山田太郎", font=font, fill=0)
    image = image.rotate(4, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    array = np.array(image)
    red = (array[:, :, 0] > 150) & (array[:, :, 1] < 80) & (array[:, :, 2] < 80)
    ys, xs = np.where(red)
    seal = Rect(float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))
    source = tmp_path / "seal.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=image.width, height=image.height)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    page.insert_text((36, image.height - 24), "誤読ダミーQQQQ", fontname="japan", fontsize=11, render_mode=3)
    doc.save(source)
    doc.close()

    opened = open_document(source)
    assert opened.pages[0].kind == PageKind.SCANNED
    session = Session(opened, Settings(ocr_dpi=72))
    region = session.add_region(0, seal)
    assert region is not None
    assert region.hits[0].hit.surface == "（範囲）"
    recognized = recognize(opened, Settings(ocr_dpi=72, deskew=True), PpOcrV5(), tmp_path / "work")
    session.document = recognized
    session.rebind_after_ocr(opened)
    moved = next(hit.hit.bbox for group in session.groups for hit in group.hits if hit.hit.surface == "（範囲）")
    assert recognized.pages[0].image_path
    assert _iou(moved, _red_bbox(Path(recognized.pages[0].image_path))) > 0.5
    group = next(item for item in session.groups if any(hit.hit.surface == "（範囲）" for hit in item.hits))
    group.action = Action.BLACKOUT
    dest = tmp_path / "sealed.pdf"
    export_pdf(recognized, [group], dest, SaveOptions(export_log=False, strip_metadata=True, align_box_width=False))
    saved = pymupdf.open(dest)
    try:
        pixmap = pymupdf.Pixmap(saved, saved[0].get_images()[0][0])
        samples = pixmap.samples
        channels = pixmap.n
        reds = 0
        total = 0
        x0, y0 = max(0, int(moved.x0)), max(0, int(moved.y0))
        x1, y1 = min(pixmap.width, int(moved.x1)), min(pixmap.height, int(moved.y1))
        for y in range(y0, y1):
            for x in range(x0, x1):
                offset = (y * pixmap.width + x) * channels
                total += 1
                if samples[offset] > 150 and samples[offset + 1] < 80:
                    reds += 1
        text = saved[0].get_text()
    finally:
        saved.close()
    assert total > 0
    assert reds / total < 0.05
    assert "QQQQ" not in text


def test_rotated_scan_keeps_the_header_on_its_ink(tmp_path: Path) -> None:
    font = ImageFont.truetype(cjk_font(), 42)
    image = Image.new("RGB", (900, 1200), "white")
    ImageDraw.Draw(image).text((80, 480), "山田太郎", font=font, fill=0)
    source = tmp_path / "rot.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(pymupdf.Rect(30, 36, 565, 806), stream=buffer.getvalue())
    page.insert_text((36, 28), "FAX送信 03-1111-2222", fontname="japan", fontsize=12)
    page.set_rotation(90)
    doc.save(source)
    doc.close()

    opened = open_document(source)
    assert opened.pages[0].kind == PageKind.SCANNED
    recognized = recognize(opened, Settings(ocr_dpi=72, deskew=True), PpOcrV5(), tmp_path / "work")
    lines = recognized.pages[0].lines
    header = next(line for line in lines if line.source == TextSource.NATIVE and "FAX" in line.text)
    ocr_header = next(line for line in lines if line.source == TextSource.OCR and "FAX" in line.text)
    assert _iou(header.bbox, ocr_header.bbox) > 0.45
    probe = pymupdf.open()
    probe_page = probe.new_page(width=recognized.pages[0].width, height=recognized.pages[0].height)
    probe_page.insert_image(probe_page.rect, filename=recognized.pages[0].image_path)
    probe_path = tmp_path / "probe.pdf"
    probe.save(probe_path)
    probe.close()
    probe_doc = pymupdf.open(probe_path)
    try:
        ink = _dark_fraction(probe_doc, 0, header.bbox)
    finally:
        probe_doc.close()
    assert ink > 0.01
    assert any("太郎" in line.text and line.source == TextSource.OCR for line in lines)


def test_fax_header_on_a_scan_still_finds_the_name_in_the_image(tmp_path: Path) -> None:
    font = ImageFont.truetype(cjk_font(), 48)
    image = Image.new("RGB", (1100, 420), "white")
    ImageDraw.Draw(image).text((60, 220), "山田太郎", font=font, fill=0)
    image = image.rotate(3, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    source = tmp_path / "fax.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=image.width, height=image.height)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    page.insert_text((40, 36), "FAX送信 03-1111-2222", fontname="japan", fontsize=14)
    page.insert_text((40, image.height - 28), "誤読ダミーQQQQ", fontname="japan", fontsize=11, render_mode=3)
    doc.save(source)
    doc.close()

    opened = open_document(source)
    assert opened.pages[0].kind == PageKind.SCANNED
    assert any(line.visible and "FAX" in line.text for line in opened.pages[0].lines)
    assert any(not line.visible and "QQQQ" in line.text for line in opened.pages[0].lines)
    assert not any("太郎" in line.text for line in opened.pages[0].lines)

    recognized = recognize(opened, Settings(ocr_dpi=72, deskew=True), PpOcrV5(), tmp_path / "work")
    lines = recognized.pages[0].lines
    assert any("太郎" in line.text and line.source == TextSource.OCR for line in lines)
    header = next(line for line in lines if line.visible and line.source == TextSource.NATIVE and "FAX" in line.text)
    ocr_header = next(line for line in lines if line.source == TextSource.OCR and "FAX" in line.text)
    assert not any("QQQQ" in line.text for line in lines)
    # The vector header moved with the image, so it sits on the ink OCR saw.
    assert _iou(header.bbox, ocr_header.bbox) > 0.5

    probe = pymupdf.open()
    probe_page = probe.new_page(width=recognized.pages[0].width, height=recognized.pages[0].height)
    probe_page.insert_image(probe_page.rect, filename=recognized.pages[0].image_path)
    probe_path = tmp_path / "probe.pdf"
    probe.save(probe_path)
    probe.close()
    probe_doc = pymupdf.open(probe_path)
    try:
        header_ink = _dark_fraction(probe_doc, 0, header.bbox)
    finally:
        probe_doc.close()
    assert header_ink > 0.01

    session = Session(recognized, Settings())
    group = session.add_phrase("山田太郎")
    assert group is not None
    assert group.included_hits()
    group.action = Action.BLACKOUT
    name_rect = group.included_hits()[0].hit.bbox
    before_doc = pymupdf.open(probe_path)
    try:
        before_dark = _dark_fraction(before_doc, 0, name_rect)
    finally:
        before_doc.close()

    dest = tmp_path / "fax-out.pdf"
    options = SaveOptions(export_log=False, strip_metadata=True, align_box_width=False)
    export_pdf(recognized, [group], dest, options, Settings())
    saved = pymupdf.open(dest)
    try:
        after_dark = _dark_fraction(saved, 0, name_rect)
        covered = _render_dark(saved, 0, name_rect)
        text = "".join(item.get_text() for item in saved)
    finally:
        saved.close()
    assert before_dark > 0.05
    assert after_dark < before_dark * 0.35
    assert covered > 0.85
    # Each glyph is its own text object, so extractors put spaces between the
    # header letters. The phone number itself is still there.
    kept = "".join(text.split())
    assert "FAX" in kept
    assert "2222" in kept
    assert "太郎" not in kept
    assert "QQQQ" not in kept
    report = verify_pdf(str(dest), [group], Settings(), session.table, True)
    assert report.passed

    header_group = session.add_phrase("03-1111-2222")
    assert header_group is not None
    header_group.action = Action.BLACKOUT
    header_path = tmp_path / "fax-header.pdf"
    export_pdf(recognized, [header_group], header_path, options, Settings())
    saved_header = pymupdf.open(header_path)
    try:
        header_text = "".join(item.get_text() for item in saved_header)
    finally:
        saved_header.close()
    # Spaces from per-glyph extraction must not hide a surviving number.
    assert "2222" not in "".join(header_text.split())
    assert "QQQQ" not in header_text

    again = recognize(recognized, Settings(ocr_dpi=72, deskew=True), PpOcrV5(), tmp_path / "work-again")
    assert sum("太郎" in line.text for line in again.pages[0].lines) == 1


def _blackout_phrase(recognized, phrase: str, dest: Path):
    session = Session(recognized, Settings())
    group = session.add_phrase(phrase)
    assert group is not None and group.included_hits()
    group.action = Action.BLACKOUT
    rect = group.included_hits()[0].hit.bbox
    options = SaveOptions(export_log=False, strip_metadata=True, align_box_width=False)
    export_pdf(recognized, [group], dest, options, Settings())
    return session, group, rect


def test_name_in_the_middle_of_a_scan_line_is_redacted(tmp_path: Path) -> None:
    """A name that is not the whole OCR line must sit in the same cells search uses."""
    font = ImageFont.truetype(cjk_font(), 36)
    image = Image.new("RGB", (1400, 500), "white")
    ImageDraw.Draw(image).text((40, 80), "本件の担当者は山田太郎です", font=font, fill=0)
    ImageDraw.Draw(image).text((40, 180), "報告者 山田太郎", font=font, fill=0)
    source = tmp_path / "mid.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=image.width, height=image.height)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    doc.save(source)
    doc.close()

    opened = open_document(source)
    assert opened.pages[0].kind == PageKind.SCANNED
    recognized = recognize(opened, Settings(ocr_dpi=120, deskew=True), PpOcrV5(), tmp_path / "work")
    assert any("太郎" in line.text and line.source == TextSource.OCR for line in recognized.pages[0].lines)

    probe = pymupdf.open()
    probe_page = probe.new_page(width=recognized.pages[0].width, height=recognized.pages[0].height)
    probe_page.insert_image(probe_page.rect, filename=recognized.pages[0].image_path)
    probe_path = tmp_path / "probe.pdf"
    probe.save(probe_path)
    probe.close()

    session, group, name_rect = _blackout_phrase(recognized, "山田太郎", tmp_path / "mid-out.pdf")
    before = pymupdf.open(probe_path)
    try:
        before_dark = _dark_fraction(before, 0, name_rect)
    finally:
        before.close()
    saved = pymupdf.open(tmp_path / "mid-out.pdf")
    try:
        after_dark = _dark_fraction(saved, 0, name_rect)
        text = "".join(item.get_text() for item in saved)
    finally:
        saved.close()
    assert before_dark > 0.05
    assert after_dark < before_dark * 0.35
    flat = "".join(text.split())
    assert "太郎" not in flat and "山田" not in flat
    assert "担当者" in flat
    report = verify_pdf(str(tmp_path / "mid-out.pdf"), [group], Settings(), session.table, True)
    assert report.passed


def test_vector_name_on_a_full_page_image_is_redacted(tmp_path: Path) -> None:
    """OCR of a letterhead must not leave a second copy of the vector name."""
    image = Image.new("RGB", (900, 1200), (245, 245, 245))
    source = tmp_path / "letter.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    page.insert_text((48, 120), "本件の担当者は山田太郎です", fontname="japan", fontsize=14)
    page.insert_text((48, 160), "報告者 山田太郎", fontname="japan", fontsize=14)
    doc.save(source)
    doc.close()

    opened = open_document(source)
    assert opened.pages[0].kind == PageKind.SCANNED
    recognized = recognize(opened, Settings(ocr_dpi=120, deskew=True), PpOcrV5(), tmp_path / "work")
    assert any(line.source == TextSource.NATIVE and "太郎" in line.text for line in recognized.pages[0].lines)
    assert any(line.source == TextSource.OCR and "太郎" in line.text for line in recognized.pages[0].lines)

    session, group, _rect = _blackout_phrase(recognized, "山田太郎", tmp_path / "letter-out.pdf")
    saved = pymupdf.open(tmp_path / "letter-out.pdf")
    try:
        text = "".join(item.get_text() for item in saved)
    finally:
        saved.close()
    flat = "".join(text.split())
    assert "山田" not in flat and "太郎" not in flat
    assert "担当者" in flat
    report = verify_pdf(str(tmp_path / "letter-out.pdf"), [group], Settings(), session.table, True)
    assert report.passed
