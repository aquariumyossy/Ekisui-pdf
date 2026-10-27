import hashlib
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from ekisui.domain.session import Session
from ekisui.domain.types import (
    Action,
    Category,
    Document,
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

from fonts import cjk_font


def _scanned_document(tmp: Path) -> tuple[Document, str]:
    font = ImageFont.truetype(cjk_font(), 42)
    images = []
    lines_per_page = [
        ["株式会社サンプル商事", "残す文章です"],
        ["株式会社サンプル商事", "架空花子"],
    ]
    for index, lines in enumerate(lines_per_page):
        image = Image.new("RGB", (900, 360), "white")
        draw = ImageDraw.Draw(image)
        draw.text((40, 40), lines[0], font=font, fill=(0, 0, 0))
        draw.text((40, 160), lines[1], font=font, fill=(10, 10, 120))
        images.append(image)
    source = tmp / "source.pdf"
    _save_poisoned_pdf(images, source)
    pages = []
    for index, image in enumerate(images):
        png = tmp / f"page-{index}.png"
        image.save(png)
        text_lines = (
            TextLine(
                f"p{index}a",
                index,
                lines_per_page[index][0],
                Rect(40, 40, 640, 100),
                0.99,
                TextSource.OCR,
            ),
            TextLine(
                f"p{index}b",
                index,
                lines_per_page[index][1],
                Rect(40, 160, 400, 220),
                0.99,
                TextSource.OCR,
            ),
        )
        pages.append(
            Page(
                index=index,
                width=900,
                height=360,
                kind=PageKind.SCANNED,
                lines=text_lines,
                image_path=str(png),
                dpi=72,
                source_index=0,
            )
        )
    return Document(str(source), tuple(pages)), hashlib.sha256(source.read_bytes()).hexdigest()


def _save_poisoned_pdf(images, path: Path) -> None:
    doc = pymupdf.open()
    for image in images:
        png = path.with_name(path.stem + f"-{image.size[0]}.png")
        image.save(png)
        page = doc.new_page(width=image.width, height=image.height)
        page.insert_image(page.rect, filename=str(png))
    doc.set_metadata({"author": "SENTINEL_AUTHOR_EKISUI", "title": "SENTINEL_TITLE_EKISUI"})
    doc.set_xml_metadata("<rdf>SENTINEL_XMP_EKISUI</rdf>")
    doc.embfile_add("secret.txt", b"SENTINEL_EMBED_EKISUI")
    xref = doc.get_new_xref()
    doc.update_object(xref, "<< /S /JavaScript /JS (SENTINEL_JS_EKISUI) >>")
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"{xref} 0 R")
    doc.save(path)
    doc.close()
    doc = pymupdf.open(path)
    doc.set_metadata({"author": "SENTINEL_OLD_REVISION"})
    doc.save(path, incremental=True, encryption=0)
    doc.close()


def _dark_fraction(doc: pymupdf.Document, page_index: int, rect: Rect) -> float:
    page = doc[page_index]
    images = page.get_images()
    assert images, "redacted page has no image xobject"
    pixmap = pymupdf.Pixmap(doc, images[0][0])
    if pixmap.n >= 4 and pixmap.alpha:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
    samples = pixmap.samples
    channels = pixmap.n
    scale_x = pixmap.width / page.rect.width
    scale_y = pixmap.height / page.rect.height
    x0 = max(0, int(rect.x0 * scale_x))
    y0 = max(0, int(rect.y0 * scale_y))
    x1 = min(pixmap.width, int(rect.x1 * scale_x))
    y1 = min(pixmap.height, int(rect.y1 * scale_y))
    dark = 0
    total = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            offset = (y * pixmap.width + x) * channels
            if samples[offset] < 80:
                dark += 1
            total += 1
    assert total > 0
    return dark / total


def test_scanned_redaction_removes_text_and_pixels(tmp_path):
    document, digest = _scanned_document(tmp_path)
    session = Session(document, Settings())
    company = session.add_phrase("株式会社サンプル商事")
    assert company is not None
    assert company.pseudonym == "会社A"
    assert {hit.hit.page_index for hit in company.hits} == {0, 1}
    flower = session.add_phrase("架空花子")
    dest = tmp_path / "out_墨消し.pdf"
    options = SaveOptions(
        align_box_width=True,
        strip_metadata=True,
        export_log=True,
        include_original_terms=False,
        export_replacement_table=False,
    )
    # Compare against the page image we drew, via a one-page pdf of that png.
    probe = pymupdf.open()
    probe_page = probe.new_page(width=900, height=360)
    probe_page.insert_image(probe_page.rect, filename=document.pages[0].image_path)
    probe_path = tmp_path / "probe.pdf"
    probe.save(probe_path)
    probe.close()
    before_dark = _dark_fraction(pymupdf.open(probe_path), 0, Rect(40, 40, 640, 100))

    result = export_pdf(document, [company], dest, options, Settings())
    assert hashlib.sha256(Path(document.source_path).read_bytes()).hexdigest() == digest
    saved = pymupdf.open(dest)
    page0 = "".join(saved[0].get_text().split())
    page1 = "".join(saved[1].get_text().split())
    assert "会社A" in page0
    assert "会社A" in page1
    assert "株式会社サンプル商事" not in page0
    assert "株式会社サンプル商事" not in page1
    assert "残す文章です" in page0
    raw = dest.read_bytes()
    assert "株式会社サンプル商事".encode("utf-8") not in raw
    assert "株式会社サンプル商事".encode("utf-16-be") not in raw
    for sentinel in (
        b"SENTINEL_AUTHOR_EKISUI",
        b"SENTINEL_XMP_EKISUI",
        b"SENTINEL_EMBED_EKISUI",
        b"SENTINEL_JS_EKISUI",
        b"SENTINEL_OLD_REVISION",
        "表記ゆれ".encode("utf-8"),
    ):
        assert sentinel not in raw
    assert saved[0].annots() is None or list(saved[0].annots()) == []
    after_dark = _dark_fraction(saved, 0, company.hits[0].hit.bbox)
    assert before_dark > 0.05
    assert after_dark < before_dark * 0.35
    saved.close()

    log = Path(result.log_path).read_text(encoding="utf-8-sig")
    assert "株式会社サンプル商事" not in log
    assert "会社A" in log
    assert "黒塗り" not in log or "置換" in log
    assert result.table_path is None

    report = verify_pdf(str(dest), [company, flower], Settings(), session.table, check_metadata=True)
    assert report.metadata_clean is True
    assert any("花子" in item.term for item in report.leftovers)
    assert not any("サンプル" in item.term for item in report.leftovers)

    clean = verify_pdf(str(dest), [company], Settings(), session.table, check_metadata=True)
    assert clean.passed

    # A second export of the same plan stays clean and does not touch the source.
    again = tmp_path / "again_墨消し.pdf"
    export_pdf(document, [company], again, options, Settings())
    assert verify_pdf(str(again), [company], Settings(), session.table, True).passed
    assert hashlib.sha256(Path(document.source_path).read_bytes()).hexdigest() == digest


def test_log_can_include_the_original_term(tmp_path):
    document, _digest = _scanned_document(tmp_path)
    session = Session(document, Settings())
    company = session.add_phrase("株式会社サンプル商事")
    dest = tmp_path / "named_墨消し.pdf"
    result = export_pdf(
        document,
        [company],
        dest,
        SaveOptions(export_log=True, include_original_terms=True, strip_metadata=True),
        Settings(),
    )
    text = Path(result.log_path).read_text(encoding="utf-8-sig")
    assert "株式会社サンプル商事" in text
    assert "元の語句" in text
    assert "株式会社サンプル商事".encode("utf-8") not in dest.read_bytes()


def test_aligned_boxes_cover_short_names(tmp_path):
    document, _digest = _scanned_document(tmp_path)
    session = Session(document, Settings(align_chars=5))
    group = session.add_phrase("株式会社サンプル商事")
    group.action = Action.BLACKOUT
    group.pseudonym = None
    narrow = tmp_path / "narrow_墨消し.pdf"
    wide = tmp_path / "wide_墨消し.pdf"
    export_pdf(document, [group], narrow, SaveOptions(align_box_width=False, export_log=False), Settings())
    export_pdf(
        document,
        [group],
        wide,
        SaveOptions(align_box_width=True, export_log=False),
        Settings(align_chars=5),
    )
    # The phrase is already wider than 5em, so both cover it and the text is gone.
    for path in (narrow, wide):
        assert "株式会社サンプル商事" not in pymupdf.open(path)[0].get_text()


def test_proportional_line_redacts_the_real_glyphs(tmp_path):
    path = tmp_path / "mixed.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=400)
    page.insert_text(
        (48, 80),
        "Tel:03-1234 ABCDEF株式会社サンプル商事です。",
        fontname="japan",
        fontsize=12,
    )
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(48, 100, 200, 120), "uri": "mailto:taro@example.com"})
    doc.save(path)
    doc.close()

    opened = open_document(path)
    assert opened.pages[0].lines
    assert opened.pages[0].lines[0].chars
    session = Session(opened, Settings())
    group = session.add_phrase("株式会社サンプル商事")
    assert group is not None
    dest = tmp_path / "mixed_墨消し.pdf"
    export_pdf(opened, [group], dest, SaveOptions(export_log=False, strip_metadata=True), Settings())
    saved = pymupdf.open(dest)
    try:
        text = saved[0].get_text()
        assert "株式会社サンプル商事" not in text
        assert "サンプル商事" not in text
        assert saved[0].get_links() == []
    finally:
        saved.close()
    report = verify_pdf(str(dest), [group], Settings(), session.table, True)
    assert report.passed


def test_short_text_page_is_still_redactable(tmp_path):
    path = tmp_path / "cover.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "株式会社サンプル商事", fontname="japan", fontsize=16)
    doc.save(path)
    doc.close()
    opened = open_document(path)
    assert opened.pages[0].lines
    assert "サンプル商事" in opened.pages[0].lines[0].text
    session = Session(opened, Settings())
    group = session.add_phrase("株式会社サンプル商事")
    assert group is not None and group.hits
    dest = tmp_path / "cover_墨消し.pdf"
    export_pdf(opened, [group], dest, SaveOptions(export_log=False), Settings())
    assert "株式会社サンプル商事" not in pymupdf.open(dest)[0].get_text()
