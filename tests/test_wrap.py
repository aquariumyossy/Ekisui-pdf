"""A term split by a line break or a page break is redacted on both lines."""

from pathlib import Path

import pymupdf

from ekisui.domain.normalize import load_confusables, strict_text
from ekisui.domain.session import Session, TermGroup, TrackedHit
from ekisui.domain.types import Action, Category, Hit, MatchKind, Rect, SaveOptions, Settings
from ekisui.pdf.document import open_document
from ekisui.pdf.export import export_pdf
from ekisui.pdf.verify import verify_pdf

from factory import document_from_lines


TERM = "専門アドバイザー"


def _search(pages, threshold, gap=28.0):
    table = load_confusables()
    document = document_from_lines(pages, gap=gap)
    session = Session(document, Settings(fuzzy_threshold=threshold))
    group = session.add_phrase(TERM)
    assert group is not None
    return [tracked.hit for tracked in group.included_hits()]


def test_loose_line_spacing_still_covers_the_wrapped_vowel():
    # Baseline 32 with 16pt boxes leaves a 16pt gap. That used to split the term.
    for threshold in (0.60, 0.88):
        hits = _search(
            [["受領者が当該役職員または専門アドバイザ", "ーの選任および監督について責任を負う。"]],
            threshold,
            gap=32.0,
        )
        assert len(hits) == 1
        assert hits[0].kind == MatchKind.EXACT
        assert strict_text(hits[0].surface) == TERM
        assert len(hits[0].parts) == 2
        assert len(hits[0].line_ids) == 2


def test_page_break_covers_the_wrapped_vowel():
    for threshold in (0.60, 0.88):
        hits = _search(
            [["開示者は専門アドバイザ"], ["ーに開示できる。"]],
            threshold,
            gap=40.0,
        )
        assert {hit.page_index for hit in hits} == {0, 1}
        assert all(strict_text(hit.surface) == TERM for hit in hits)
        assert all(hit.kind == MatchKind.EXACT for hit in hits)
        assert sum(len(hit.parts) for hit in hits) == 2


def test_a_blank_gap_still_does_not_join():
    table = load_confusables()
    document = document_from_lines([["株式会社サ", "ンプル商事"]], gap=40.0)
    session = Session(document, Settings())
    assert session.add_phrase("株式会社サンプル商事") is None
    assert table is not None


def test_text_pdf_redacts_the_wrap_and_keeps_the_neighbors(tmp_path):
    path = tmp_path / "架空.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    lines = [
        (72, "受領者が当該役職員または専門アドバイザ"),
        (104, "ーの選任および監督について責任を負う。"),
        (150, "弁護士・公認会計士等の専門アドバイザーのうち"),
        (180, "当該役職員または専門アドバイザーは秘密情報を"),
        (210, "役職員または専門アドバイザーによる秘密情報"),
        (240, "その他の専門アドバイザーが関与する場合"),
        (780, "開示者は専門アドバイザ"),
    ]
    for y, text in lines:
        page.insert_text((56, y), text, fontname="japan", fontsize=10.5)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((56, 72), "ーに開示できる。", fontname="japan", fontsize=10.5)
    doc.save(path)
    doc.close()

    opened = open_document(path)
    session = Session(opened, Settings(fuzzy_threshold=0.60))
    group = session.add_phrase(TERM)
    assert group is not None
    assert any(len(tracked.hit.line_ids) > 1 for tracked in group.hits)
    assert any(tracked.hit.page_index == 1 for tracked in group.hits)
    dest = tmp_path / "架空_Masked.pdf"
    export_pdf(
        opened,
        session.groups,
        dest,
        SaveOptions(align_box_width=True, strip_metadata=True, export_log=False, export_replacement_table=False),
        session.settings,
    )
    saved = pymupdf.open(dest)
    try:
        text = "\n".join(page.get_text("text") for page in saved)
    finally:
        saved.close()
    assert TERM not in text
    assert "専門アドバイザ" not in text
    assert "受領者が当該役職員または" in text
    assert "の選任および監督" in text
    assert "弁護士・公認会計士等の" in text
    assert "のうち" in text
    assert "当該役職員または" in text
    assert "は秘密情報を" in text
    assert "役職員または" in text
    assert "による秘密情報" in text
    assert "その他の" in text
    assert "が関与する場合" in text
    assert "開示者は" in text
    assert "に開示できる" in text
    assert not any(line.startswith("ー") for line in text.splitlines())
    report = verify_pdf(str(dest), session.groups, session.settings, session.table, False)
    assert report.clean


def test_leftover_check_flags_a_wrapped_vowel_that_was_left_behind(tmp_path):
    path = tmp_path / "残った.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((56, 72), "受領者が当該役職員また", fontname="japan", fontsize=10.5)
    page.insert_text((56, 104), "ーの選任および監督について責任を負う。", fontname="japan", fontsize=10.5)
    doc.save(path)
    doc.close()
    group = TermGroup(
        id="g1",
        canonical=TERM,
        category=Category.PHRASE,
        action=Action.BLACKOUT,
        pseudonym=None,
        hits=[
            TrackedHit(
                "h1",
                Hit(0, TERM, Rect(0, 0, 10, 10), MatchKind.EXACT, 1.0, "", ()),
                True,
            )
        ],
        origin="search",
    )
    report = verify_pdf(str(path), [group], Settings(fuzzy_threshold=0.88), load_confusables(), False)
    assert any(item.term == "ー" and "続き" in item.explanation for item in report.leftovers)


def test_scanned_pdf_redacts_a_wrapped_term(tmp_path):
    from test_ocr import _page_image, _pdf_of

    source = tmp_path / "scan.pdf"
    _pdf_of(
        [
            _page_image(["開示者は専門アドバイザ"], 0),
            _page_image(["ーに開示できる。"], 0),
        ],
        source,
    )
    opened = open_document(source)
    from ekisui.pdf.document import recognize
    from ekisui.pdf.ocr_engine import PpOcrV5

    recognized = recognize(opened, Settings(ocr_dpi=72, deskew=False), PpOcrV5(), tmp_path / "work")
    read = "\n".join(line.text for page in recognized.pages for line in page.lines)
    assert "専門アドバイザ" in read, read
    session = Session(recognized, Settings(fuzzy_threshold=0.60))
    group = session.add_phrase(TERM)
    assert group is not None, read
    assert any(len(hit.parts) >= 1 for tracked in group.hits for hit in (tracked.hit,)), read
    covered = "".join(strict_text(tracked.hit.surface) for tracked in group.included_hits())
    assert "専門アドバイザ" in covered
    dest = tmp_path / "scan_Masked.pdf"
    export_pdf(
        recognized,
        session.groups,
        dest,
        SaveOptions(align_box_width=True, strip_metadata=True, export_log=False, export_replacement_table=False),
        session.settings,
    )
    saved = "\n".join(page.get_text("text") for page in pymupdf.open(dest))
    assert "専門アドバイザ" not in saved
    if any(line.startswith("ー") for line in read.splitlines()):
        assert not any(line.startswith("ー") for line in saved.splitlines()), saved
    report = verify_pdf(str(dest), session.groups, session.settings, session.table, False)
    assert report.clean, [(item.term, item.explanation) for item in report.leftovers]


def test_masking_finds_a_phone_split_across_a_wrap():
    document = document_from_lines([["連絡先は03-1234-", "5678です。"]], gap=32.0)
    session = Session(document, Settings())
    session.rescan()
    phones = [group for group in session.groups if "03-1234-5678" in strict_text(group.canonical)]
    assert phones
    assert any(len(tracked.hit.line_ids) > 1 for group in phones for tracked in group.included_hits())
