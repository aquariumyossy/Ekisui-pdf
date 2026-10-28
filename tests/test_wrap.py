"""A term split by a line break or a page break is redacted on both lines."""

from pathlib import Path

import pymupdf

from ekisui.domain.normalize import load_confusables, strict_text
from ekisui.domain.session import Session, TermGroup, TrackedHit
from ekisui.domain.types import (
    Action,
    Category,
    Document,
    Hit,
    MatchKind,
    Page,
    PageKind,
    Rect,
    SaveOptions,
    Settings,
    TextLine,
    TextSource,
)
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


def test_page_number_and_header_do_not_hide_the_wrap(tmp_path):
    path = tmp_path / "見出し.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((250, 36), "- 1 -", fontname="helv", fontsize=10)
    page.insert_text((56, 700), "開示者は専門アドバイザ", fontname="japan", fontsize=10.5)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((56, 40), "秘密保持契約書", fontname="japan", fontsize=10.5)
    page2.insert_text((56, 96), "ーに開示できる。", fontname="japan", fontsize=10.5)
    page2.insert_text((250, 810), "- 2 -", fontname="helv", fontsize=10)
    doc.save(path)
    doc.close()
    opened = open_document(path)
    session = Session(opened, Settings(fuzzy_threshold=0.60))
    group = session.add_phrase(TERM)
    assert group is not None
    assert {tracked.hit.page_index for tracked in group.included_hits()} == {0, 1}
    dest = tmp_path / "見出し_Masked.pdf"
    export_pdf(
        opened,
        session.groups,
        dest,
        SaveOptions(align_box_width=False, strip_metadata=True, export_log=False, export_replacement_table=False),
        session.settings,
    )
    saved = "\n".join(page.get_text("text") for page in pymupdf.open(dest))
    assert "専門アドバイザ" not in saved
    assert "秘密保持契約書" in saved
    assert "に開示できる" in saved
    assert not any(line.strip().startswith("ー") for line in saved.splitlines())
    report = verify_pdf(str(dest), session.groups, session.settings, session.table, False)
    assert report.clean, [(item.term, item.explanation) for item in report.leftovers]


def test_wrapped_term_is_not_dropped_beside_another_name():
    document = document_from_lines(
        [["山田太郎は当該役職員または専門アドバイザ", "ーの選任を監督する。"]],
        gap=32.0,
    )
    session = Session(document, Settings())
    session.suggest()
    assert session.add_phrase(TERM) is not None
    session.rescan()
    surfaces = [strict_text(hit.hit.surface) for group in session.groups for hit in group.included_hits()]
    assert TERM in surfaces
    assert any("山田" in surface for surface in surfaces)


def test_masking_joins_a_given_name_split_across_a_wrap():
    document = document_from_lines([["受領者は山田太", "郎に通知する。"]], gap=32.0)
    session = Session(document, Settings())
    session.suggest()
    people = [group.canonical for group in session.groups if "山田" in group.canonical]
    assert any(strict_text(name) == "山田太郎" for name in people), people


def test_ocr_rebind_moves_every_part():
    from dataclasses import replace

    from ekisui.domain.types import PageKind

    document = document_from_lines([["山田太郎"]])
    page = document.pages[0]
    old = replace(document, pages=(replace(page, kind=PageKind.SCANNED, image_path="old.png"),))
    session = Session(old, Settings())
    original = Rect(72, 72, 140, 88)
    hit = Hit(
        0,
        "山田太郎",
        original,
        MatchKind.EXACT,
        1.0,
        "",
        ("p0l0",),
        parts=(original,),
    )
    session.groups.append(
        TermGroup(
            id="g",
            canonical="山田太郎",
            category=Category.PERSON,
            action=Action.REPLACE,
            pseudonym="個人甲",
            hits=[TrackedHit("h", hit, True)],
            origin="region",
        )
    )
    moved = replace(page, kind=PageKind.SCANNED, image_path="new.png", skew=3.0)
    session.document = replace(old, pages=(moved,))
    session.rebind_after_ocr(old)
    kept = [item.hit for group in session.groups for item in group.hits if item.hit.parts]
    assert kept
    assert all(part != original for hit in kept for part in hit.parts)


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
    opened = open_document(path)
    tail = next(line for line in opened.pages[0].lines if line.text.startswith("ー"))
    group = TermGroup(
        id="g1",
        canonical=TERM,
        category=Category.PHRASE,
        action=Action.BLACKOUT,
        pseudonym=None,
        hits=[
            TrackedHit(
                "h1",
                Hit(
                    0,
                    "専門アドバイザ",
                    Rect(tail.bbox.x0, tail.bbox.y0 - 18, tail.bbox.x0 + 80, tail.bbox.y0 - 4),
                    MatchKind.FUZZY,
                    0.875,
                    "",
                    (),
                ),
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
    assert not any(line.strip().startswith(("ー", "一")) for line in saved.splitlines()), saved
    report = verify_pdf(str(dest), session.groups, session.settings, session.table, False)
    assert report.clean, [(item.term, item.explanation) for item in report.leftovers]


def _placed(lines: list[tuple[str, float, float, float]]) -> Document:
    """Lines are (text, x, y, x1). x1 lets a full line reach the column edge."""
    built = []
    for index, (text, x, y, x1) in enumerate(lines):
        built.append(
            TextLine(
                id=f"p0l{index}",
                page_index=0,
                text=text,
                bbox=Rect(x, y, x1, y + 12.0),
                confidence=1.0,
                source=TextSource.NATIVE,
            )
        )
    return Document(
        source_path="columns.pdf",
        pages=(
            Page(
                index=0,
                width=600.0,
                height=840.0,
                kind=PageKind.NATIVE,
                lines=tuple(built),
                source_index=0,
            ),
        ),
    )


def test_three_line_wrap_is_one_replacement(tmp_path: Path) -> None:
    path = tmp_path / "three.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((56, 80), "開示先の前文です専門アドバ", fontname="japan", fontsize=11)
    page.insert_text((56, 112), "イザ", fontname="japan", fontsize=11)
    page.insert_text((56, 144), "ーです。", fontname="japan", fontsize=11)
    doc.save(path)
    doc.close()
    opened = open_document(path)
    session = Session(opened, Settings(fuzzy_threshold=0.60))
    group = session.add_phrase(TERM)
    assert group is not None
    assert group.action == Action.REPLACE
    assert any("ー" in strict_text(tracked.hit.surface) for tracked in group.included_hits())
    dest = tmp_path / "three_Masked.pdf"
    export_pdf(
        opened,
        session.groups,
        dest,
        SaveOptions(align_box_width=False, strip_metadata=True, export_log=False, export_replacement_table=False),
        session.settings,
    )
    saved = pymupdf.open(dest)[0].get_text()
    assert "ー" not in saved
    assert "呼称A" in saved
    report = verify_pdf(str(dest), session.groups, session.settings, session.table, False)
    assert report.clean, [(item.term, item.explanation) for item in report.leftovers]


def test_column_wrap_does_not_eat_the_other_column(tmp_path: Path) -> None:
    document = _placed(
        [
            ("左列専門アドバイザ", 72, 100, 400),
            ("右列は別の文章です", 430, 100, 560),
            ("ーの選任について", 72, 122, 220),
            ("右側の続きです", 430, 122, 560),
        ]
    )
    session = Session(document, Settings(fuzzy_threshold=0.60))
    group = session.add_phrase(TERM)
    assert group is not None
    assert "ー" in strict_text(group.hits[0].hit.surface)
    assert "右" not in strict_text(group.hits[0].hit.surface)


def test_wrapped_account_is_not_replaced_by_an_unchecked_alnum() -> None:
    document = document_from_lines([["普通預金口座番号1234567", "A社名義の口座に振り込む。"]], gap=32.0)
    session = Session(document, Settings())
    session.rescan()
    accounts = [group for group in session.groups if group.category == Category.ACCOUNT]
    assert accounts and any(hit.included for group in accounts for hit in group.hits)
    assert any("1234567" in group.canonical for group in accounts)


def test_verify_flags_a_vowel_left_just_below_a_short_hit(tmp_path: Path) -> None:
    path = tmp_path / "tail.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((56, 80), "前文です", fontname="japan", fontsize=12)
    page.insert_text((56, 110), "ーの後文です。", fontname="japan", fontsize=12)
    doc.save(path)
    doc.close()
    opened = open_document(path)
    tail = next(line for line in opened.pages[0].lines if line.text.startswith("ー"))
    hit = Hit(
        0,
        "専門アドバイザ",
        Rect(tail.bbox.x0, tail.bbox.y0 - 18, tail.bbox.x0 + 90, tail.bbox.y0 - 4),
        MatchKind.FUZZY,
        0.875,
        "",
        (),
    )
    group = TermGroup(
        id="g",
        canonical=TERM,
        category=Category.PHRASE,
        action=Action.REPLACE,
        pseudonym="呼称A",
        hits=[TrackedHit("h", hit, True)],
        origin="search",
    )
    report = verify_pdf(str(path), [group], Settings(), load_confusables(), False)
    assert any(item.term.startswith("ー") for item in report.leftovers)


def test_masking_finds_a_phone_split_across_a_wrap():
    document = document_from_lines([["連絡先は03-1234-", "5678です。"]], gap=32.0)
    session = Session(document, Settings())
    session.rescan()
    phones = [group for group in session.groups if "03-1234-5678" in strict_text(group.canonical)]
    assert phones
    assert any(len(tracked.hit.line_ids) > 1 for group in phones for tracked in group.included_hits())
