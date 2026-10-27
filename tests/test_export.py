from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from ekisui_pdf.core.models import Action, OcrLine, Rect, SaveOptions, Selection
from ekisui_pdf.core.pdfio import export_pdf
from ekisui_pdf.core.plan import plan_pages
from ekisui_pdf.core.table import TABLE_KIND, ReplacementTable, save_table
from tests.factories import scanned_pdf


def _selection_for(line: OcrLine, term: str, action: Action, pseudonym: str = "") -> Selection:
    start = line.text.index(term)
    end = start + len(term)
    from ekisui_pdf.core.geometry import slice_rect

    return Selection(
        id=f"{line.line_id}-{start}",
        page_index=line.page_index,
        rect=slice_rect(line.rect, line.text, start, end),
        matched_text=term,
        action=action,
        pseudonym=pseudonym,
        source="search",
        line_id=line.line_id,
        char_start=start,
        char_end=end,
    )


def _sample(tmp_path: Path):
    path = tmp_path / "scan.pdf"
    lines = scanned_pdf(
        path,
        [
            ["株式会社サンプルは山田太郎を被告とする。", "原告は株式会社　ＡＢＣである。"],
            ["次のページにも山田太郎がいる。", "甲は佐藤花子に通知した。"],
        ],
    )
    return path, lines


def test_text_layer_is_searchable_without_redaction(tmp_path: Path):
    source_path, lines = _sample(tmp_path)
    import pymupdf

    source = pymupdf.open(source_path)
    dest = tmp_path / "ocr-only.pdf"
    try:
        result = export_pdf(source, dest, lines, [], ReplacementTable(), SaveOptions())
    finally:
        source.close()
    assert result.report.passed
    saved = pymupdf.open(dest)
    try:
        assert saved[0].search_for("山田太郎")
        assert saved[1].search_for("佐藤花子")
        assert saved[0].get_text()
        before = pymupdf.open(source_path)[0].get_pixmap(dpi=72, alpha=False)
        after = saved[0].get_pixmap(dpi=72, alpha=False)
        assert before.samples == after.samples
    finally:
        saved.close()


def test_redaction_removes_text_and_changes_pixels(tmp_path: Path):
    source_path, lines = _sample(tmp_path)
    targets = [line for line in lines if "山田太郎" in line.text]
    selections = [_selection_for(line, "山田太郎", Action.REDACT) for line in targets]
    source = pymupdf.open(source_path)
    before = [page.get_pixmap(dpi=72, alpha=False) for page in source]
    dest = tmp_path / "redacted.pdf"
    try:
        result = export_pdf(
            source,
            dest,
            lines,
            selections,
            ReplacementTable(),
            SaveOptions(strip_metadata=True),
            source_path=source_path,
        )
    finally:
        source.close()
    assert result.report.passed, result.report.leftovers
    saved = pymupdf.open(dest)
    try:
        for page in saved:
            assert not page.search_for("山田太郎")
            assert "山田太郎" not in (page.get_text() or "")
        assert saved[0].search_for("株式会社")
        _assert_box_blackened(before[0], saved[0], selections[0].rect)
        image_xobjects = sum(
            saved.xref_get_key(xref, "Subtype")[1] == "/Image"
            for xref in range(1, saved.xref_length())
        )
        assert image_xobjects == saved.page_count
        raw = dest.read_bytes()
        assert "山田太郎".encode("utf-8") not in raw
        assert TABLE_KIND.encode("utf-8") not in raw
    finally:
        saved.close()


def test_partial_selection_leaves_the_other_hit(tmp_path: Path):
    source_path, lines = _sample(tmp_path)
    first = next(line for line in lines if line.page_index == 0 and "山田太郎" in line.text)
    selection = _selection_for(first, "山田太郎", Action.REDACT)
    source = pymupdf.open(source_path)
    dest = tmp_path / "partial.pdf"
    try:
        result = export_pdf(source, dest, lines, [selection], ReplacementTable(), SaveOptions())
    finally:
        source.close()
    assert not result.report.passed
    assert any(item.term == "山田太郎" and item.page_index == 1 for item in result.report.leftovers)


def test_pseudonym_is_consistent_and_table_stays_out_of_pdf(tmp_path: Path):
    source_path, lines = _sample(tmp_path)
    targets = [line for line in lines if "山田太郎" in line.text]
    selections = [
        _selection_for(line, "山田太郎", Action.PSEUDONYM, pseudonym="被告A") for line in targets
    ]
    table = ReplacementTable()
    table.upsert("山田太郎", "被告A")
    table_path = tmp_path / "table.json"
    save_table(table_path, table)
    source = pymupdf.open(source_path)
    dest = tmp_path / "pseudo.pdf"
    try:
        result = export_pdf(source, dest, lines, selections, table, SaveOptions(), source_path=source_path)
    finally:
        source.close()
    assert result.report.passed, result.report.leftovers
    saved = pymupdf.open(dest)
    try:
        found = [page.search_for("被告A") for page in saved]
        assert all(found)
        assert all(not page.search_for("山田太郎") for page in saved)
        texts = [page.get_text() for page in saved]
        assert all("被告A" in text for text in texts)
        assert all("山田太郎" not in text for text in texts)
    finally:
        saved.close()
    raw = dest.read_bytes()
    assert "山田太郎".encode() not in raw
    assert TABLE_KIND.encode() not in raw
    assert "山田太郎" in table_path.read_text(encoding="utf-8")
    assert "被告A" in table_path.read_text(encoding="utf-8")


def test_fixed_width_boxes_share_one_width():
    short = OcrLine(0, "甲", Rect(72, 100, 90, 120), line_id="s")
    long = OcrLine(0, "株式会社サンプル", Rect(72, 140, 250, 160), line_id="l")
    selections = [
        Selection("a", 0, Rect(72, 100, 90, 120), "甲", Action.REDACT, line_id="s", char_start=0, char_end=1),
        Selection(
            "b",
            0,
            Rect(72, 140, 250, 160),
            "株式会社サンプル",
            Action.REDACT,
            line_id="l",
            char_start=0,
            char_end=len(long.text),
        ),
    ]
    plans = plan_pages(
        [short, long],
        selections,
        ReplacementTable(),
        SaveOptions(fixed_width=True, fixed_width_pt=80),
        [(595, 842)],
    )
    widths = [round(rect.width, 2) for rect in plans[0].redactions]
    assert len(set(widths)) == 1
    assert widths[0] >= 170


def test_metadata_stripped_only_when_asked(tmp_path: Path):
    source_path = _poisoned_pdf(tmp_path / "poison.pdf")
    lines = [
        OcrLine(0, "本文です。", Rect(72, 90, 180, 110), line_id="p0-l0"),
    ]
    source = pymupdf.open(source_path)
    stripped = tmp_path / "stripped.pdf"
    kept = tmp_path / "kept.pdf"
    try:
        export_pdf(source, stripped, lines, [], ReplacementTable(), SaveOptions(strip_metadata=True))
        export_pdf(source, kept, lines, [], ReplacementTable(), SaveOptions(strip_metadata=False))
    finally:
        source.close()

    raw_stripped = stripped.read_bytes()
    for secret in ("SECRET_TITLE", "SECRET_XMP", "SECRET_EMBED", "SECRET_JS", "SECRET_NOTE", "SECRET_OLD_REVISION"):
        assert secret.encode() not in raw_stripped
    opened = pymupdf.open(stripped)
    try:
        assert opened.metadata["title"] == ""
        assert not opened.get_xml_metadata()
        assert opened.embfile_count() == 0
        assert list(opened[0].annots() or []) == []
        assert "本文です" in (opened[0].get_text() or "")
    finally:
        opened.close()

    kept_doc = pymupdf.open(kept)
    try:
        assert kept_doc.metadata["title"] == "SECRET_TITLE"
        assert "SECRET_OLD_REVISION".encode() not in kept.read_bytes()
    finally:
        kept_doc.close()


def test_refuses_to_overwrite_source(tmp_path: Path):
    source_path, lines = _sample(tmp_path)
    source = pymupdf.open(source_path)
    try:
        with pytest.raises(Exception, match="上書き"):
            export_pdf(
                source,
                source_path,
                lines,
                [],
                ReplacementTable(),
                SaveOptions(),
                source_path=source_path,
            )
    finally:
        source.close()


def _poisoned_pdf(path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 120), "本文です。", fontname="japan", fontsize=16)
    document.set_metadata({"title": "SECRET_OLD_REVISION"})
    document.save(path, deflate=False, garbage=0)
    document.close()

    revised = pymupdf.open(path)
    revised.set_metadata({"title": "SECRET_TITLE", "author": "SECRET_AUTHOR"})
    revised.set_xml_metadata("<x:xmpmeta>SECRET_XMP</x:xmpmeta>")
    revised.embfile_add("secret.txt", b"SECRET_EMBED")
    page = revised[0]
    page.add_text_annot(pymupdf.Point(300, 300), "SECRET_NOTE")
    widget = pymupdf.Widget()
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "secret_field"
    widget.rect = pymupdf.Rect(10, 700, 200, 730)
    widget.script = "app.alert('SECRET_JS');"
    page.add_widget(widget)
    revised.save(path, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
    revised.close()
    raw = path.read_bytes()
    for secret in ("SECRET_OLD_REVISION", "SECRET_TITLE", "SECRET_XMP", "SECRET_EMBED", "SECRET_NOTE", "SECRET_JS"):
        assert secret.encode() in raw, secret
    return path


def _assert_box_blackened(before: pymupdf.Pixmap, page: pymupdf.Page, rect: Rect) -> None:
    after = page.get_pixmap(dpi=72, alpha=False)
    x0 = max(int(rect.x0) + 1, 0)
    y0 = max(int(rect.y0) + 1, 0)
    x1 = min(int(rect.x1) - 1, after.width - 1)
    y1 = min(int(rect.y1) - 1, after.height - 1)
    assert x1 > x0 and y1 > y0
    total = 0
    black = 0
    changed = 0
    had_light = False
    for y in range(y0, y1):
        for x in range(x0, x1):
            total += 1
            old = before.pixel(x, y)
            new = after.pixel(x, y)
            if old != new:
                changed += 1
            if sum(old[:3]) > 80:
                had_light = True
            if sum(new[:3]) <= 30:
                black += 1
    assert had_light
    assert changed > 0
    assert black / total > 0.85
