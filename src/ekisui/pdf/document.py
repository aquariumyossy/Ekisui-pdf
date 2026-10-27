from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pymupdf

from ekisui.domain.normalize import strict_text
from ekisui.domain.types import Document, Page, PageKind, Rect, TextLine, TextSource
from ekisui.errors import EncryptedPdf
from ekisui.pdf.deskew import correct_page, format_correction, map_page_rect
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
            # A page-sized image is a scan even when a fax header or stamp is
            # also drawn on it. Born-digital pages have no page-sized image.
            kind = PageKind.SCANNED if needs_ocr(page, compact) else PageKind.NATIVE
            rect = page.rect
            pages.append(
                Page(
                    index=index,
                    width=float(rect.width),
                    height=float(rect.height),
                    kind=kind,
                    lines=tuple(lines),
                    source_index=index,
                    source_width=float(rect.width),
                    source_height=float(rect.height),
                )
            )
        return Document(source_path=str(path), pages=tuple(pages))
    finally:
        source.close()


# A copier page is an image that fills most of the sheet.
_SCAN_COVERAGE = 0.60
# A 1×1 pixel stretched over the page, or a tiny stamp, is not a scan.
# Strips and tiles of a low-resolution scan still clear this.
_MIN_IMAGE_PIXELS = 4_000
# Span alpha is 0–255. Render mode 3 is 0. Opacity 0.05 lands just above 12.
_VISIBLE_ALPHA = 13


def pages_need_ocr(document: Document) -> bool:
    """Scanned pages still waiting for a straightened image."""
    return any(page.kind == PageKind.SCANNED and not page.image_path for page in document.pages)


def needs_ocr(page: pymupdf.Page, compact: str) -> bool:
    """A page-sized image is a scan, even with a fax header or a stamp.

    The visible vector text is kept and merged with OCR. ``compact`` includes
    the invisible printer layer and is not used for this decision.
    """
    del compact
    return image_coverage(page) >= _SCAN_COVERAGE


def image_coverage(page: pymupdf.Page) -> float:
    """Share of the page covered by scan-sized images, after /Rotate.

    ``get_image_info`` boxes are in unrotated user space. Several strips are
    combined. The mask is about four points per cell, so a thin strip is not
    missed by a coarse lattice.
    """
    bounds = page.rect
    if bounds.width < 1 or bounds.height < 1:
        return 0.0
    rects: list[pymupdf.Rect] = []
    for item in page.get_image_info() or []:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        if width * height < _MIN_IMAGE_PIXELS:
            continue
        placed = _placed_image_rect(page, item.get("bbox"))
        if placed is not None:
            rects.append(placed)
    if not rects:
        return 0.0
    cell = 4.0
    cols = max(1, int(np.ceil(bounds.width / cell)))
    rows = max(1, int(np.ceil(bounds.height / cell)))
    mask = np.zeros((rows, cols), dtype=bool)
    for rect in rects:
        c0 = max(0, int((rect.x0 - bounds.x0) / bounds.width * cols))
        c1 = min(cols, int(np.ceil((rect.x1 - bounds.x0) / bounds.width * cols)))
        r0 = max(0, int((rect.y0 - bounds.y0) / bounds.height * rows))
        r1 = min(rows, int(np.ceil((rect.y1 - bounds.y0) / bounds.height * rows)))
        if c1 > c0 and r1 > r0:
            mask[r0:r1, c0:c1] = True
    return float(mask.mean())


def _placed_image_rect(page: pymupdf.Page, bbox) -> pymupdf.Rect | None:
    if not bbox:
        return None
    raw = pymupdf.Rect(bbox)
    if raw.is_empty or raw.is_infinite:
        return None
    placed = (raw * page.rotation_matrix) & page.rect
    if placed.is_empty or placed.width < 1 or placed.height < 1:
        return None
    return placed


def extract_lines(page: pymupdf.Page, page_index: int) -> list[TextLine]:
    raw = page.get_text("rawdict")
    lines: list[TextLine] = []
    number = 0
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            buckets: dict[bool, tuple[list[str], list[Rect]]] = {
                True: ([], []),
                False: ([], []),
            }
            for span in line.get("spans", []):
                pieces, chars = buckets[_span_visible(span)]
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
            for visible, (pieces, chars) in buckets.items():
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
                        visible=visible,
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
    """OCR every scanned page, including one that also has visible type.

    Born-digital pages are kept. A scan is rebuilt from the straightened image.
    OCR text and the visible vector text are both searchable. The vector boxes
    move with the same turns as the image. Invisible printer text is left out.
    """
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
            built = Page(
                index=page.index,
                width=page_w,
                height=page_h,
                kind=PageKind.SCANNED,
                lines=(),
                image_path=str(image_path),
                dpi=settings.ocr_dpi,
                rotation=rotation,
                skew=deskewed.skew,
                correction_label=label,
                source_index=page.source_index,
                quarter=deskewed.rotation,
                source_width=page.source_width or page.width,
                source_height=page.source_height or page.height,
            )
            text_lines.extend(_moved_visible_lines(source[page.source_index], page, built))
            pages.append(replace(built, lines=tuple(text_lines)))
            if on_page:
                on_page(done + 1, total, label)
        return Document(source_path=document.source_path, pages=tuple(pages))
    finally:
        source.close()


def _span_visible(span: dict) -> bool:
    alpha = span.get("alpha")
    if alpha is None:
        return True
    return int(alpha) > _VISIBLE_ALPHA


def _moved_visible_lines(pdf_page: pymupdf.Page, old: Page, new: Page) -> list[TextLine]:
    """Visible type, in the same place as the straightened image.

    ``get_text`` boxes are in unrotated user space. The render is the page
    after ``/Rotate``, so the boxes are turned first, then moved with the
    deskew. Lines already produced by OCR are not copied again.
    """
    origin = Page(
        index=old.index,
        width=old.source_width or old.width,
        height=old.source_height or old.height,
        kind=PageKind.SCANNED,
        lines=(),
        source_width=old.source_width or old.width,
        source_height=old.source_height or old.height,
    )
    matrix = pdf_page.rotation_matrix
    moved: list[TextLine] = []
    for line in extract_lines(pdf_page, old.index):
        if not line.visible:
            continue
        chars = tuple(map_page_rect(origin, new, _apply_matrix(char, matrix)) for char in line.chars)
        if chars:
            bbox = chars[0]
            for char in chars[1:]:
                bbox = bbox.union(char)
        else:
            bbox = map_page_rect(origin, new, _apply_matrix(line.bbox, matrix))
        if bbox.width < 0.5 or bbox.height < 0.5:
            continue
        moved.append(
            TextLine(
                id=f"p{old.index}v{len(moved)}",
                page_index=old.index,
                text=line.text,
                bbox=bbox,
                confidence=1.0,
                source=TextSource.NATIVE,
                chars=chars,
                visible=True,
            )
        )
    return moved


def _apply_matrix(rect: Rect, matrix: pymupdf.Matrix) -> Rect:
    def point(x: float, y: float) -> tuple[float, float]:
        return (matrix.a * x + matrix.c * y + matrix.e, matrix.b * x + matrix.d * y + matrix.f)

    corners = (point(rect.x0, rect.y0), point(rect.x1, rect.y0), point(rect.x0, rect.y1), point(rect.x1, rect.y1))
    xs = [item[0] for item in corners]
    ys = [item[1] for item in corners]
    return Rect(min(xs), min(ys), max(xs), max(ys))


def _quad_to_rect(quad, image_w: int, image_h: int, page_w: float, page_h: float) -> Rect:
    xs = [point[0] for point in quad]
    ys = [point[1] for point in quad]
    scale_x = page_w / image_w
    scale_y = page_h / image_h
    return Rect(min(xs) * scale_x, min(ys) * scale_y, max(xs) * scale_x, max(ys) * scale_y).pad(0.8, 0.6)


def _save_png(image: np.ndarray, path: Path) -> None:
    from PIL import Image

    Image.fromarray(image).save(path, format="PNG")
