from __future__ import annotations

import os
from pathlib import Path

import pymupdf

from ekisui_pdf.core.errors import EncryptedPdfError, SameFileError
from ekisui_pdf.core.models import ExportResult, OcrLine, Rect, SaveOptions, Selection, TextInsert
from ekisui_pdf.core.plan import applied_box_width, forbidden_terms, plan_pages
from ekisui_pdf.core.table import ReplacementTable
from ekisui_pdf.core.verify import verify_pdf

_JAPAN_FONT: pymupdf.Font | None = None


def open_document(path: Path) -> pymupdf.Document:
    document = pymupdf.open(path)
    if document.needs_pass and not document.authenticate(""):
        document.close()
        raise EncryptedPdfError("パスワード付きのPDFは開けません。")
    prepare_document(document)
    return document


def prepare_document(document: pymupdf.Document) -> None:
    if document.is_encrypted and document.needs_pass:
        raise EncryptedPdfError("パスワード付きのPDFは開けません。")
    for page in document:
        page.remove_rotation()


def render_page_rgb(page: pymupdf.Page, dpi: int = 144) -> pymupdf.Pixmap:
    zoom = dpi / 72.0
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csRGB)


def _japan_font() -> pymupdf.Font:
    global _JAPAN_FONT
    if _JAPAN_FONT is None:
        _JAPAN_FONT = pymupdf.Font("japan")
    return _JAPAN_FONT


def paths_are_same(left: Path, right: Path) -> bool:
    """Windows では大文字小文字だけ違うパスも同じファイルとして扱う。"""
    left_key = os.path.normcase(os.path.abspath(left))
    right_key = os.path.normcase(os.path.abspath(right))
    if left_key == right_key:
        return True
    if os.name == "nt" and left_key.casefold() == right_key.casefold():
        return True
    try:
        return Path(left).exists() and Path(right).exists() and os.path.samefile(left, right)
    except OSError:
        return False


def _insert_fitted(page: pymupdf.Page, insert: TextInsert) -> None:
    """幅の計算と描画を同じ Font('japan') で行う。insert_text の japan とは別物。"""
    rect = insert.rect.normalized()
    text = insert.text
    if not text or rect.width < 0.4 or rect.height < 0.4:
        return
    font = _japan_font()
    unit = font.text_length(text, fontsize=1) or 1.0
    fontsize = min(rect.width / unit * 0.98, rect.height * 0.82)
    fontsize = max(fontsize, 0.8)
    width = font.text_length(text, fontsize=fontsize)
    if width > rect.width and width > 0:
        fontsize *= rect.width / width * 0.98
        width = font.text_length(text, fontsize=fontsize)
    if insert.visible:
        x = rect.x0 + max(0.0, (rect.width - width) / 2)
        color = (1, 1, 1)
        render_mode = 0
    else:
        x = rect.x0
        color = (0, 0, 0)
        render_mode = 3
    baseline = min(rect.y0 + rect.height * 0.82, rect.y1 - 0.4)
    writer = pymupdf.TextWriter(page.rect)
    writer.append((x, baseline), text, font=font, fontsize=fontsize)
    writer.write_text(page, color=color, render_mode=render_mode)


def strip_sensitive(document: pymupdf.Document) -> None:
    """文書情報、XMP、添付、JavaScript、注釈、サムネイルを落とす。

    hidden_text は False。ここを True にすると、いま入れた透明テキスト層まで墨消しされる。
    """
    for page in document:
        for widget in list(page.widgets() or []):
            page.delete_widget(widget)
        for annot in list(page.annots() or []):
            page.delete_annot(annot)
    document.set_toc([])
    _clear_page_labels(document)
    catalog = document.pdf_catalog()
    document.xref_set_key(catalog, "OCProperties", "null")
    document.scrub(
        attached_files=True,
        clean_pages=True,
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


def _clear_page_labels(document: pymupdf.Document) -> None:
    try:
        document.set_page_labels([])
    except Exception:
        document.xref_set_key(document.pdf_catalog(), "PageLabels", "null")


def _drop_thumbnails(document: pymupdf.Document) -> None:
    for page in document:
        if document.xref_get_key(page.xref, "Thumb")[0] != "null":
            document.xref_set_key(page.xref, "Thumb", "null")


def _drop_existing_text(page: pymupdf.Page) -> None:
    """スキャンに付いている古い文字層を、画像の画素を消さずに落とす。"""
    page.add_redact_annot(page.rect, fill=None)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE,
        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        text=pymupdf.PDF_REDACT_TEXT_REMOVE,
    )


def _apply_plan(document: pymupdf.Document, plans: list) -> None:
    for page, plan in zip(document, plans, strict=True):
        active = [rect for rect in plan.redactions if rect.width >= 0.4 and rect.height >= 0.4]
        for rect in active:
            page.add_redact_annot(
                pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y1),
                fill=(0, 0, 0),
            )
        if active:
            # IMAGE_PIXELS は画像の上に黒を塗るのではなく、重なった画素を消す。
            page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )
        for insert in plan.inserts:
            _insert_fitted(page, insert)


def export_pdf(
    source: pymupdf.Document,
    dest: Path,
    lines: list[OcrLine],
    selections: list[Selection],
    table: ReplacementTable,
    options: SaveOptions,
    source_path: Path | None = None,
) -> ExportResult:
    dest = Path(dest)
    if source_path is not None and paths_are_same(source_path, dest):
        raise SameFileError("元のファイルは上書きしません。別の名前で保存してください。")
    dest.parent.mkdir(parents=True, exist_ok=True)

    page_sizes = [(page.rect.width, page.rect.height) for page in source]
    plans = plan_pages(lines, selections, table, options, page_sizes)
    copy = pymupdf.open(stream=source.tobytes(), filetype="pdf")
    partial = dest.with_suffix(dest.suffix + ".partial")
    committed = False
    try:
        prepare_document(copy)
        if lines:
            for page in copy:
                _drop_existing_text(page)
        _apply_plan(copy, plans)
        if any(plan.redactions for plan in plans):
            _drop_thumbnails(copy)
        if options.strip_metadata:
            strip_sensitive(copy)
        # 非増分かつ garbage=4 で、参照されなくなった元画像と古い改訂を落とす。
        copy.save(
            partial,
            garbage=4,
            clean=True,
            deflate=True,
            incremental=False,
            encryption=pymupdf.PDF_ENCRYPT_NONE,
        )
        partial.replace(dest)
        committed = True
    finally:
        copy.close()
        if not committed:
            partial.unlink(missing_ok=True)
    report = verify_pdf(dest, forbidden_terms(selections))
    redaction_count = sum(1 for selection in selections if selection.action.value == "redact")
    pseudonym_count = sum(1 for selection in selections if selection.action.value == "pseudonym")
    return ExportResult(
        report=report,
        redaction_count=redaction_count,
        pseudonym_count=pseudonym_count,
        output_path=str(dest),
        applied_box_width=applied_box_width(plans, options),
    )


def page_count(document: pymupdf.Document) -> int:
    return document.page_count


def page_bounds(page: pymupdf.Page) -> Rect:
    rect = page.rect
    return Rect(rect.x0, rect.y0, rect.x1, rect.y1)
