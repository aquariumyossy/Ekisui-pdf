from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, replace
from pathlib import Path

import pymupdf

from ekisui.domain.index import _cells, _char_weight
from ekisui.domain.normalize import strict_text
from ekisui.domain.session import TermGroup
from ekisui.domain.tableio import groups_to_csv
from ekisui.domain.types import Action, Document, Page, PageKind, Rect, SaveOptions, Settings, TextLine, TextSource
from ekisui.errors import EkisuiError
from ekisui.pdf.document import pdf_path


@dataclass(frozen=True)
class RedactionBox:
    page_index: int
    rect: Rect
    action: Action
    pseudonym: str | None
    original: str | None
    adjusted: bool = False
    ocr_changed: bool = False


@dataclass(frozen=True)
class ExportResult:
    pdf_path: str
    log_path: str | None
    table_path: str | None


def redaction_boxes(
    document: Document,
    groups: list[TermGroup],
    options: SaveOptions,
    settings: Settings,
) -> list[RedactionBox]:
    pages = {page.index: page for page in document.pages}
    boxes: list[RedactionBox] = []
    for group in groups:
        for tracked in group.included_hits():
            page = pages[tracked.hit.page_index]
            action = group.action
            pseudonym = group.pseudonym if action == Action.REPLACE else None
            if action == Action.REPLACE and not pseudonym:
                action = Action.BLACKOUT
            rects = tracked.hit.parts or (tracked.hit.bbox,)
            for rect in rects:
                boxes.append(
                    RedactionBox(
                        page_index=page.index,
                        rect=_box_rect(
                            rect,
                            page,
                            _widen_short(tracked.hit, rect, options.align_box_width),
                            settings.align_chars,
                            exact=bool(tracked.hit.parts),
                        ),
                        action=action,
                        pseudonym=pseudonym,
                        original=tracked.hit.surface,
                        adjusted=tracked.adjusted,
                        ocr_changed=tracked.ocr_changed,
                    )
                )
    return boxes


def export_pdf(
    document: Document,
    groups: list[TermGroup],
    dest: str | Path,
    options: SaveOptions,
    settings: Settings | None = None,
    archived: list[TermGroup] | None = None,
    prior_boxes: list[RedactionBox] | None = None,
) -> ExportResult:
    settings = settings or Settings()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    archived = archived or []
    boxes = redaction_boxes(document, groups, options, settings)
    source = pymupdf.open(pdf_path(document))
    output = pymupdf.open()
    try:
        by_page: dict[int, list[RedactionBox]] = {}
        for box in boxes:
            by_page.setdefault(box.page_index, []).append(box)
        for page in document.pages:
            pdf_page = _add_page(output, source, page)
            _redact_page(pdf_page, by_page.get(page.index, []))
        if options.strip_metadata:
            cleaned = strip_document(output)
            output.close()
            output = cleaned
        temporary = dest.with_name(dest.name + ".partial")
        output.save(
            temporary,
            garbage=4,
            deflate=True,
            clean=True,
            incremental=False,
            encryption=pymupdf.PDF_ENCRYPT_NONE,
            preserve_metadata=0 if options.strip_metadata else 1,
        )
    finally:
        output.close()
        source.close()
    os.replace(temporary, dest)

    log_path = None
    table_path = None
    base = dest.stem[: -len("_墨消し")] if dest.stem.endswith("_墨消し") else dest.stem
    if options.export_log:
        log_path = dest.with_name(base + "_墨消し記録.csv")
        earlier = list(prior_boxes) if prior_boxes is not None else redaction_boxes(document, archived, options, settings)
        write_log(log_path, [*earlier, *boxes], options.include_original_terms)
    if options.export_replacement_table:
        table_path = dest.with_name(base + "_置換表.csv")
        table_path.write_text(groups_to_csv([*archived, *groups]), encoding="utf-8-sig")
    return ExportResult(str(dest), str(log_path) if log_path else None, str(table_path) if table_path else None)


def strip_document(doc: pymupdf.Document) -> pymupdf.Document:
    """Drop document info, XMP, attachments, JavaScript, thumbnails, links, and annotations.

    ``scrub(remove_links=True)`` crashes in PyMuPDF 1.26/2.0 if a link xref was just
    freed, so links are deleted and the file is saved with garbage collection before
    scrub runs. Invisible text we just wrote is the searchable layer, so hidden_text stays.
    The returned document is a new object. The caller closes ``doc``.
    """
    doc.set_metadata({})
    try:
        doc.del_xml_metadata()
    except Exception:
        pass
    names = list(doc.embfile_names() or [])
    for name in names:
        doc.embfile_del(name)
    for page in doc:
        for widget in list(page.widgets() or []):
            page.delete_widget(widget)
        for link in list(page.get_links()):
            page.delete_link(link)
        annot = page.first_annot
        while annot:
            nxt = annot.next
            page.delete_annot(annot)
            annot = nxt
    catalog = doc.pdf_catalog()
    for key in ("OpenAction", "AA", "Names", "AcroForm", "Outlines", "PieceInfo", "Metadata"):
        try:
            doc.xref_set_key(catalog, key, "null")
        except Exception:
            pass
    buffer = io.BytesIO()
    doc.save(
        buffer,
        garbage=4,
        deflate=True,
        clean=True,
        incremental=False,
        encryption=pymupdf.PDF_ENCRYPT_NONE,
        preserve_metadata=0,
    )
    fresh = pymupdf.open(stream=buffer.getvalue())
    fresh.scrub(
        attached_files=True,
        clean_pages=False,
        embedded_files=True,
        hidden_text=False,
        javascript=True,
        metadata=True,
        redactions=False,
        remove_links=True,
        reset_fields=True,
        reset_responses=True,
        thumbnails=True,
        xml_metadata=True,
    )
    fresh.set_metadata({})
    try:
        fresh.del_xml_metadata()
    except Exception:
        pass
    return fresh


def _csv_cell(value: object) -> str:
    text = str(value)
    if text[:1] in "=+-@":
        return "'" + text
    return text


def unique_destination(path: Path, extra_suffixes: tuple[str, ...] = ()) -> Path:
    """Return ``path`` or ``stem (2).ext`` so nothing already on disk is replaced."""

    def taken(candidate: Path) -> bool:
        if candidate.exists():
            return True
        return any(candidate.with_name(candidate.stem + suffix).exists() for suffix in extra_suffixes)

    if not taken(path):
        return path
    number = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not taken(candidate):
            return candidate
        number += 1


def write_log(path: Path, boxes: list[RedactionBox], include_original: bool) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        header = ["ページ", "左", "上", "右", "下", "種類", "呼び名", "調整"]
        if include_original:
            header.append("元の語句")
        writer.writerow(header)
        for box in boxes:
            row = [
                box.page_index + 1,
                round(box.rect.x0, 2),
                round(box.rect.y0, 2),
                round(box.rect.x1, 2),
                round(box.rect.y1, 2),
                "黒塗り" if box.action == Action.BLACKOUT else "置換",
                box.pseudonym or "",
                " ".join(
                    part
                    for part, flag in (("手動", box.adjusted), ("OCR修正で変更", box.ocr_changed))
                    if flag
                ),
            ]
            if include_original:
                row.append(box.original or "")
            writer.writerow([_csv_cell(cell) for cell in row])


def _add_page(output: pymupdf.Document, source: pymupdf.Document, page: Page) -> pymupdf.Page:
    if page.kind == PageKind.SCANNED:
        if not page.image_path:
            raise EkisuiError("スキャンのページが残っています。OCR実行してから保存してください。")
        # A new page. Invisible printer text is not copied. Visible vector text
        # is already in page.lines, moved with the image, and written below.
        pdf_page = output.new_page(width=page.width, height=page.height)
        pdf_page.insert_image(pdf_page.rect, filename=page.image_path)
        _write_text_layer(pdf_page, page.lines)
        return pdf_page
    output.insert_pdf(source, from_page=page.source_index, to_page=page.source_index)
    pdf_page = output[-1]
    annot = pdf_page.first_annot
    while annot:
        nxt = annot.next
        pdf_page.delete_annot(annot)
        annot = nxt
    return pdf_page


def _write_text_layer(page: pymupdf.Page, lines: tuple[TextLine, ...]) -> None:
    """One glyph per search cell, so a redaction slice removes exactly those glyphs.

    OCR lines have no character boxes. Search splits them with ``_cells``.
    Writing the whole line into one text box left-aligns the glyphs, and a
    name in the middle of the line then sits outside its redaction rectangle.
    """
    for line in lines:
        if not line.text.strip():
            continue
        for glyph, cell in zip(line.text, _cells(line)):
            if glyph.isspace():
                continue
            _write_invisible(page, cell, glyph)


def _write_invisible(page: pymupdf.Page, rect: Rect, text: str) -> None:
    """One invisible glyph inside ``rect``.

    A whole-line ``insert_text`` runs past the end of the box. One glyph, sized
    to the cell, stays in the cell that search redacts.
    """
    if rect.width < 0.8 or rect.height < 0.8 or not text:
        return
    fontsize = min(rect.height * 0.72, rect.width / (max(_char_weight(text[:1]), 0.2) * 1.05), 16.0)
    if fontsize < 2.0:
        return
    baseline = rect.y0 + min(rect.height * 0.82, fontsize)
    page.insert_text((rect.x0, baseline), text, fontsize=fontsize, fontname="japan", render_mode=3)


def _redact_page(page: pymupdf.Page, boxes: list[RedactionBox]) -> None:
    if not boxes:
        return
    for box in boxes:
        fill = (0, 0, 0) if box.action == Action.BLACKOUT else (1, 1, 1)
        page.add_redact_annot(pymupdf.Rect(box.rect.x0, box.rect.y0, box.rect.x1, box.rect.y1), fill=fill)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
        graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
        text=pymupdf.PDF_REDACT_TEXT_REMOVE,
    )
    blackouts = [box for box in boxes if box.action == Action.BLACKOUT]
    for box in boxes:
        rect = pymupdf.Rect(box.rect.x0, box.rect.y0, box.rect.x1, box.rect.y1)
        if box.action == Action.REPLACE and not _covered_by_blackout(box, blackouts):
            page.draw_rect(rect, color=(0.2, 0.2, 0.2), fill=(1, 1, 1), width=0.6)
            fontsize = max(7.0, min(rect.height * 0.62, 14.0))
            page.insert_textbox(
                rect,
                box.pseudonym or "",
                fontsize=fontsize,
                fontname="japan",
                color=(0, 0, 0),
                align=pymupdf.TEXT_ALIGN_CENTER,
            )
        else:
            page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0), width=0)


def bake_redactions(
    document: Document,
    groups: list[TermGroup],
    settings: Settings,
    work_dir: str | Path,
    align_box_width: bool,
) -> tuple[Document, list[RedactionBox]]:
    """Burn included hits into a new PDF and drop them from the text layer.

    The file the user opened is not modified. Later reads use ``working_path``.
    """
    options = SaveOptions(
        align_box_width=align_box_width,
        strip_metadata=False,
        export_log=False,
        include_original_terms=False,
        export_replacement_table=False,
    )
    boxes = redaction_boxes(document, groups, options, settings)
    if not boxes:
        return document, []
    directory = Path(work_dir)
    directory.mkdir(parents=True, exist_ok=True)
    by_page: dict[int, list[RedactionBox]] = {}
    for box in boxes:
        by_page.setdefault(box.page_index, []).append(box)
    source = pymupdf.open(pdf_path(document))
    output = pymupdf.open()
    pages: list[Page] = []
    try:
        for page in document.pages:
            pdf_page = _add_page(output, source, page)
            page_boxes = by_page.get(page.index, [])
            _redact_page(pdf_page, page_boxes)
            image_path = page.image_path
            if page.kind == PageKind.SCANNED and page_boxes:
                image_path = str(_unique_file(directory, f"baked-p{page.index}", ".png"))
                dpi = page.dpi if page.dpi and page.dpi > 0 else 144
                pdf_page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csRGB).save(image_path)
            pages.append(
                replace(
                    page,
                    lines=_lines_after_redaction(page, page_boxes),
                    image_path=image_path,
                    source_index=len(pages),
                    source_width=page.width,
                    source_height=page.height,
                    # The baked page is already upright. Leaving the old turn
                    # would move a later range when OCR runs again.
                    rotation=0,
                    skew=0.0,
                    quarter=0,
                )
            )
        baked = _unique_file(directory, "session-redacted", ".pdf")
        output.save(baked, garbage=4, deflate=True, clean=True, incremental=False)
    finally:
        output.close()
        source.close()
    return replace(document, working_path=str(baked), pages=tuple(pages)), boxes


def _unique_file(directory: Path, stem: str, suffix: str) -> Path:
    path = directory / f"{stem}{suffix}"
    number = 2
    while path.exists():
        path = directory / f"{stem}-{number}{suffix}"
        number += 1
    return path


def _lines_after_redaction(page: Page, boxes: list[RedactionBox]) -> tuple[TextLine, ...]:
    if not boxes:
        return page.lines
    used_ids = {line.id for line in page.lines}
    kept: list[TextLine] = []
    for line in page.lines:
        cells = _cells(line)
        kept_chars: list[tuple[str, Rect]] = []
        for char, cell in zip(line.text, cells):
            if any(cell.intersects(box.rect) for box in boxes):
                continue
            kept_chars.append((char, cell))
        if len(kept_chars) == len(line.text):
            kept.append(line)
            continue
        text = "".join(char for char, _cell in kept_chars)
        if not text.strip():
            continue
        chars = [cell for _char, cell in kept_chars]
        bbox = chars[0]
        for cell in chars[1:]:
            bbox = bbox.union(cell)
        kept.append(replace(line, text=text, bbox=bbox, chars=tuple(chars)))
    blackouts = [box for box in boxes if box.action == Action.BLACKOUT]
    for box in boxes:
        if box.action != Action.REPLACE or not box.pseudonym:
            continue
        if _covered_by_blackout(box, blackouts):
            continue
        number = 0
        while f"p{page.index}baked{number}" in used_ids:
            number += 1
        line_id = f"p{page.index}baked{number}"
        used_ids.add(line_id)
        kept.append(
            TextLine(
                id=line_id,
                page_index=page.index,
                text=box.pseudonym,
                bbox=box.rect,
                confidence=1.0,
                source=TextSource.CORRECTED,
                visible=True,
            )
        )
    return tuple(kept)


def _covered_by_blackout(box: RedactionBox, blackouts: list[RedactionBox]) -> bool:
    cx, cy = box.rect.center()
    return any(other.rect.contains(cx, cy) and other is not box for other in blackouts)


def _widen_short(hit, rect: Rect, align: bool) -> bool:
    """A wrapped tail is short on the page. Widening it would cover the next word."""
    if not align or len(hit.parts) > 1:
        return False
    approx = max(1.0, rect.width / max(rect.height, 8.0))
    return len(strict_text(hit.surface)) <= approx + 1.5


def _box_rect(bbox: Rect, page: Page, align: bool, chars: int, exact: bool = False) -> Rect:
    # Exact glyph bounds stay off the next character. A horizontal pad deletes
    # that whole character, because removal is per glyph.
    rect = Rect(bbox.x0, bbox.y0 - 0.25, bbox.x1, bbox.y1 + 0.25) if exact else bbox.pad(1.0, 0.8)
    if align:
        em = max(rect.height, 8.0)
        width = max(rect.width, em * chars * 0.92)
        rect = Rect(rect.x0, rect.y0, rect.x0 + width, rect.y1)
    bounds = Rect(1.0, 1.0, max(2.0, page.width - 1.0), max(2.0, page.height - 1.0))
    clipped = rect.clip(bounds)
    if clipped.width < 2 or clipped.height < 2:
        return bbox.clip(bounds)
    return clipped
