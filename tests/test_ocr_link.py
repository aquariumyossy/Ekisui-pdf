"""An OCR correction updates that line's candidates and keeps the old box."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pymupdf

from ekisui.domain.session import Session, TermGroup, TrackedHit
from ekisui.domain.types import Action, Category, Hit, MatchKind, Rect, SaveOptions, Settings
from ekisui.errors import EkisuiError
from ekisui.pdf.document import open_document
from ekisui.pdf.export import export_pdf, write_log, redaction_boxes
from ekisui.pdf.verify import verify_pdf

from factory import document_from_lines


def test_correction_merges_into_the_existing_label_and_keeps_the_old_box():
    session = Session(document_from_lines([["山田太郎は出席した", "山出太郎は欠席した"]]), Settings())
    session.suggest()
    original = next(group for group in session.groups if "山田太郎" in group.canonical)
    assert original.pseudonym == "個人甲"
    wrong = session.add_phrase("山出太郎")
    assert wrong is not None
    kept = wrong.hits[0]
    kept_box = kept.hit.bbox
    kept_text = kept.hit.surface
    line = session.document.pages[0].lines[1]
    session.correct_line(line.id, "山田太郎は欠席した")
    updated = next(item for item in session.document.pages[0].lines if item.id == line.id)
    assert kept.hit.bbox == kept_box
    assert kept.hit.surface == kept_text
    assert kept.needs_review is True
    assert kept.ocr_changed is True
    assert kept.prior_surface
    merged = [group for group in session.groups if group.pseudonym == "個人甲"]
    assert len(merged) == 1
    added = [
        hit
        for hit in merged[0].hits
        if hit.needs_review and hit.included is False and "山田" in hit.hit.surface and hit.ocr_changed
    ]
    assert added
    assert session.unreviewed_ocr() is True
    assert updated.text == "山田太郎は欠席した"
    assert updated.source.value == "corrected"


def test_confirm_stays_blocked_until_the_correction_is_reviewed(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from ekisui.gui import window as window_mod
    from ekisui.gui.window import MainWindow

    path = tmp_path / "names.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 80), "山田太郎は出席した", fontname="japan", fontsize=14)
    page.insert_text((72, 140), "山出太郎は欠席した", fontname="japan", fontsize=14)
    document.save(path)
    document.close()
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    shown: list[str] = []
    monkeypatch.setattr(window_mod.QMessageBox, "warning", lambda *_args: shown.append(str(_args[-1])))
    window.open_path(str(path))
    window.session.suggest()
    window.session.add_phrase("山出太郎")
    line = next(item for item in window.session.document.pages[0].lines if "山出" in item.text)
    window.session.correct_line(line.id, "山田太郎は欠席した")
    window.refresh()
    assert window.btn_confirm.isEnabled() is False
    window._confirm()
    assert window.session.confirmed is False
    window._open_confirm()
    assert shown and "未確認" in shown[-1]
    for group in window.session.groups:
        for hit in list(group.hits):
            if hit.needs_review:
                window.session.acknowledge_review(hit.id)
    window.refresh()
    assert window.btn_confirm.isEnabled() is True
    window._confirm()
    assert window.session.confirmed is True
    window.close()
    app.processEvents()


def test_new_label_keeps_both_the_old_box_and_the_corrected_reading():
    session = Session(document_from_lines([["鈴木太郎は出席した"]]), Settings())
    added = session.add_phrase("鈴木太郎")
    assert added is not None
    box = added.hits[0].hit.bbox
    session.correct_line(session.document.pages[0].lines[0].id, "佐藤花子は出席した")
    flower = next(group for group in session.groups if "佐藤花子" in group.canonical)
    assert flower.hits
    assert flower.hits[0].included is False
    assert flower.hits[0].needs_review is True
    kept = next(hit for group in session.groups for hit in group.hits if "鈴木" in hit.hit.surface)
    assert kept.hit.bbox == box
    assert kept.needs_review is True
    assert kept.prior_surface == "鈴木太郎"
    assert kept.corrected_surface == "佐藤花子"
    assert "出席" not in kept.prior_surface


def test_leftover_check_searches_the_original_ocr_string(tmp_path):
    path = tmp_path / "ocr.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 80), "山出太郎", fontname="japan", fontsize=14)
    document.save(path)
    document.close()
    opened = open_document(path)
    hit = Hit(0, "山田太郎", Rect(300, 300, 360, 320), MatchKind.EXACT, 1.0, "", ())
    tracked = TrackedHit(
        "h1",
        hit,
        True,
        ocr_changed=True,
        prior_surface="山出太郎",
        corrected_surface="山田太郎",
    )
    group = TermGroup("g1", "山田太郎", Category.PERSON, Action.REPLACE, "個人甲", [tracked])
    report = verify_pdf(str(path), [group], Settings(), opened and Session(opened).table, False)
    assert any(item.term == "山出太郎" for item in report.leftovers)
    boxes = redaction_boxes(opened, [group], SaveOptions(align_box_width=False), Settings())
    log_path = tmp_path / "log.csv"
    write_log(log_path, boxes, False)
    assert "OCR修正で変更" in log_path.read_text(encoding="utf-8-sig")


def test_confirmed_page_rejects_ocr_correction():
    session = Session(document_from_lines([["山田太郎", "残す文章"]]), Settings())
    session.suggest()
    session.committed = list(session.groups)
    line = next(item for item in session.document.pages[0].lines if "残す" in item.text)
    try:
        session.correct_line(line.id, "佐藤花子")
        raised = False
    except EkisuiError:
        raised = True
    assert raised
    assert "佐藤花子" not in "".join(item.text for item in session.document.pages[0].lines)


def test_saved_scan_uses_the_corrected_line(tmp_path):
    from ekisui.domain.types import Document, Page, PageKind, TextLine, TextSource

    image = tmp_path / "page.png"
    import PIL.Image

    PIL.Image.new("RGB", (400, 200), "white").save(image)
    source = tmp_path / "scan.pdf"
    sheet = pymupdf.open()
    page = sheet.new_page(width=400, height=200)
    page.insert_image(page.rect, filename=str(image))
    sheet.save(source)
    sheet.close()
    line = TextLine("p0l0", 0, "山出太郎", Rect(40, 40, 200, 70), 0.9, TextSource.OCR)
    document = Document(
        str(source),
        (Page(0, 400, 200, PageKind.SCANNED, (line,), image_path=str(image), dpi=72, source_index=0),),
    )
    session = Session(document, Settings())
    session.add_phrase("山出太郎")
    session.correct_line("p0l0", "控える文章")
    for group in session.groups:
        for hit in group.hits:
            hit.needs_review = False
            hit.included = False
    dest = tmp_path / "out.pdf"
    export_pdf(
        session.document,
        session.groups,
        dest,
        SaveOptions(align_box_width=False, strip_metadata=True, export_log=False, export_replacement_table=False),
        Settings(),
    )
    saved = pymupdf.open(dest)
    try:
        text = "".join(saved[0].get_text().split())
    finally:
        saved.close()
    assert "控える文章" in text
    assert "山出太郎" not in text
