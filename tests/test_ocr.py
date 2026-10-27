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
from ekisui.domain.types import Action, PageKind, Rect, SaveOptions, Settings
from ekisui.pdf.document import open_document, recognize
from ekisui.pdf.export import export_pdf
from ekisui.pdf.ocr_engine import PpOcrV5

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
    assert "太郎" in stale_text
    assert "太郎" not in fresh_text
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
