"""PP-OCRv5 on a generated scan: searchable text layer, deskew label, upside-down page."""

import io
import time
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from ekisui.domain.normalize import strict_text
from ekisui.domain.types import PageKind, Settings
from ekisui.pdf.document import open_document, recognize
from ekisui.pdf.export import export_pdf
from ekisui.pdf.ocr_engine import PpOcrV5
from ekisui.domain.types import SaveOptions

from fonts import cjk_font


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
