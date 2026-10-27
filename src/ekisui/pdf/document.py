from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf

from ekisui.domain.normalize import strict_text
from ekisui.domain.types import Document, Page, PageKind, Rect, TextLine, TextSource
from ekisui.errors import EncryptedPdf
from ekisui.pdf.deskew import correct_page, format_correction
from ekisui.pdf.ocr_engine import PpOcrV5


def open_document(path: str | Path) -> Document:
    source = pymupdf.open(str(path))
    try:
        if source.is_encrypted and source.needs_pass:
            raise EncryptedPdf()
        pages = []
        for index, page in enumerate(source):
            lines = extract_lines(page, index)
            compact = strict_text("".join(line.text for line in lines))
            # The cutoff decides whether OCR should run. Extracted text is kept either way,
            # including a cover page that is only a name.
            kind = PageKind.NATIVE if len(compact) >= 20 else PageKind.SCANNED
            rect = page.rect
            pages.append(
                Page(
                    index=index,
                    width=float(rect.width),
                    height=float(rect.height),
                    kind=kind,
                    lines=tuple(lines),
                    source_index=index,
                )
            )
        return Document(source_path=str(path), pages=tuple(pages))
    finally:
        source.close()


def extract_lines(page: pymupdf.Page, page_index: int) -> list[TextLine]:
    raw = page.get_text("rawdict")
    lines: list[TextLine] = []
    number = 0
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            pieces: list[str] = []
            chars: list[Rect] = []
            for span in line.get("spans", []):
                for char in span.get("chars") or []:
                    text = str(char.get("c") or "")
                    if not text:
                        continue
                    x0, y0, x1, y1 = char["bbox"]
                    step = (float(x1) - float(x0)) / len(text)
                    for offset, ch in enumerate(text):
                        pieces.append(ch)
                        chars.append(
                            Rect(
                                float(x0) + step * offset,
                                float(y0),
                                float(x0) + step * (offset + 1),
                                float(y1),
                            )
                        )
            text = "".join(pieces)
            if not text.strip():
                continue
            bbox = chars[0]
            for rect in chars[1:]:
                bbox = bbox.union(rect)
            lines.append(
                TextLine(
                    id=f"p{page_index}l{number}",
                    page_index=page_index,
                    text=text,
                    bbox=bbox,
                    confidence=1.0,
                    source=TextSource.NATIVE,
                    chars=tuple(chars),
                )
            )
            number += 1
    lines.sort(key=lambda item: (item.bbox.y0, item.bbox.x0))
    return lines


def render_page(page: pymupdf.Page, dpi: int) -> np.ndarray:
    zoom = dpi / 72.0
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csRGB)
    array = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    if pixmap.n == 4:
        array = array[:, :, :3]
    return np.ascontiguousarray(array.copy())


def recognize(
    document: Document,
    settings,
    engine: PpOcrV5,
    work_dir: Path,
    on_page=None,
    cancelled=None,
) -> Document:
    """OCR pages that have no text layer. Native pages are kept as they are."""
    source = pymupdf.open(document.source_path)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        pages: list[Page] = []
        total = len(document.pages)
        for done, page in enumerate(document.pages):
            if cancelled is not None and cancelled():
                pages.extend(document.pages[done:])
                break
            if page.kind == PageKind.NATIVE:
                pages.append(page)
                if on_page:
                    on_page(done + 1, total, page.correction_label)
                continue
            image = render_page(source[page.source_index], settings.ocr_dpi)
            deskewed = correct_page(image, settings.deskew)
            image, ocr_lines, extra = engine.read_page(deskewed.image)
            rotation = (deskewed.rotation + extra) % 360
            label = format_correction(rotation, deskewed.skew)
            image_path = work_dir / f"page-{page.index:04d}.png"
            _save_png(image, image_path)
            height, width = image.shape[:2]
            page_w = width / settings.ocr_dpi * 72.0
            page_h = height / settings.ocr_dpi * 72.0
            text_lines = []
            for number, line in enumerate(ocr_lines):
                text_lines.append(
                    TextLine(
                        id=f"p{page.index}o{number}",
                        page_index=page.index,
                        text=line.text,
                        bbox=_quad_to_rect(line.quad, width, height, page_w, page_h),
                        confidence=line.confidence,
                        source=TextSource.OCR,
                    )
                )
            pages.append(
                Page(
                    index=page.index,
                    width=page_w,
                    height=page_h,
                    kind=PageKind.SCANNED,
                    lines=tuple(text_lines),
                    image_path=str(image_path),
                    dpi=settings.ocr_dpi,
                    rotation=rotation,
                    skew=deskewed.skew,
                    correction_label=label,
                    source_index=page.source_index,
                )
            )
            if on_page:
                on_page(done + 1, total, label)
        return Document(source_path=document.source_path, pages=tuple(pages))
    finally:
        source.close()


def _quad_to_rect(quad, image_w: int, image_h: int, page_w: float, page_h: float) -> Rect:
    xs = [point[0] for point in quad]
    ys = [point[1] for point in quad]
    scale_x = page_w / image_w
    scale_y = page_h / image_h
    return Rect(min(xs) * scale_x, min(ys) * scale_y, max(xs) * scale_x, max(ys) * scale_y).pad(0.8, 0.6)


def _save_png(image: np.ndarray, path: Path) -> None:
    from PIL import Image

    Image.fromarray(image).save(path, format="PNG")
