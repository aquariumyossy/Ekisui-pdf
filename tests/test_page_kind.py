"""A copier scan with a bad text layer is still a scan. Vector text is not."""

import io

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from ekisui.domain.session import Session
from ekisui.domain.types import Action, Document, Page, PageKind, Rect, SaveOptions, TextLine, TextSource
from ekisui.errors import EkisuiError
from ekisui.pdf.document import open_document
from ekisui.pdf.export import export_pdf

from fonts import cjk_font


def _image_page(path, image: Image.Image, invisible: str | None) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=image.width, height=image.height)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    if invisible:
        page.insert_text(
            (36, 36),
            invisible,
            fontname="japan",
            fontsize=11,
            render_mode=3,
        )
    doc.save(path)
    doc.close()


def test_full_page_image_with_text_is_scanned(tmp_path) -> None:
    font = ImageFont.truetype(cjk_font(), 42)
    image = Image.new("RGB", (1000, 280), "white")
    ImageDraw.Draw(image).text((40, 80), "株式会社サンプル商事", font=font, fill=0)
    path = tmp_path / "scan.pdf"
    decoy = "旧文字層だけにある誤読ダミーQQQQです。画像にはありません。"
    _image_page(path, image, decoy)

    opened = open_document(path)
    assert opened.pages[0].kind == PageKind.SCANNED
    assert "QQQQ" in "".join(line.text for line in opened.pages[0].lines)


def test_vector_text_without_a_full_image_stays_native(tmp_path) -> None:
    path = tmp_path / "born.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "株式会社サンプル商事の準備書面です。", fontname="japan", fontsize=14)
    page.insert_text((72, 110), "被告山田太郎は請求を争う。", fontname="japan", fontsize=14)
    stamp = Image.new("RGB", (40, 40), "white")
    buffer = io.BytesIO()
    stamp.save(buffer, format="PNG")
    page.insert_image(pymupdf.Rect(500, 40, 540, 80), stream=buffer.getvalue())
    doc.save(path)
    doc.close()

    opened = open_document(path)
    assert opened.pages[0].kind == PageKind.NATIVE
    assert any("サンプル商事" in line.text for line in opened.pages[0].lines)


def test_short_vector_cover_stays_native(tmp_path) -> None:
    path = tmp_path / "cover.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 120), "山田太郎", fontname="japan", fontsize=18)
    doc.save(path)
    doc.close()

    opened = open_document(path)
    assert opened.pages[0].kind == PageKind.NATIVE
    assert any("山田太郎" in line.text for line in opened.pages[0].lines)


def test_rotated_scan_with_a_long_invisible_layer_is_scanned(tmp_path) -> None:
    path = tmp_path / "rotated.pdf"
    image = Image.new("RGB", (900, 1200), "white")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    # Inset so the unrotated box, clipped to the rotated page, covers under 60%.
    page.insert_image(pymupdf.Rect(30, 42, 565, 800), stream=buffer.getvalue())
    page.insert_text(
        (40, 60),
        "旧文字層の誤読ダミーQQQQが長く続いて、文字数だけではテキストPDFに見える。",
        fontname="japan",
        fontsize=11,
        render_mode=3,
    )
    page.set_rotation(90)
    doc.save(path)
    doc.close()

    opened = open_document(path)
    assert opened.pages[0].kind == PageKind.SCANNED


def test_tiled_scan_with_an_invisible_layer_is_scanned(tmp_path) -> None:
    path = tmp_path / "tiles.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    for index in range(4):
        image = Image.new("RGB", (800, 400), "white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        page.insert_image(pymupdf.Rect(0, index * 200, 600, (index + 1) * 200), stream=buffer.getvalue())
    page.insert_text((36, 40), "誤読ダミーQQQQがタイルの上に長く置かれている文字層です。", fontname="japan", fontsize=12, render_mode=3)
    doc.save(path)
    doc.close()

    opened = open_document(path)
    assert opened.pages[0].kind == PageKind.SCANNED


def test_visible_text_with_a_large_figure_stays_native(tmp_path) -> None:
    path = tmp_path / "chart.pdf"
    image = Image.new("RGB", (800, 900), (220, 220, 220))
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 72), "被告山田太郎は請求を争う。", fontname="japan", fontsize=14)
    page.insert_text((48, 110), "原告鈴木花子も出頭した。", fontname="japan", fontsize=14)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(pymupdf.Rect(0, 180, 595, 842), stream=buffer.getvalue())
    doc.save(path)
    doc.close()

    opened = open_document(path)
    assert opened.pages[0].kind == PageKind.NATIVE
    assert any("山田太郎" in line.text for line in opened.pages[0].lines)


def test_stretched_speck_is_not_a_scan(tmp_path) -> None:
    path = tmp_path / "speck.pdf"
    image = Image.new("RGB", (1, 1), (240, 240, 240))
    doc = pymupdf.open()
    page = doc.new_page()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    page.insert_text((72, 120), "山田太郎", fontname="japan", fontsize=16)
    doc.save(path)
    doc.close()

    opened = open_document(path)
    assert opened.pages[0].kind == PageKind.NATIVE


def test_blank_page_without_an_image_stays_native(tmp_path) -> None:
    path = tmp_path / "blank.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    assert open_document(path).pages[0].kind == PageKind.NATIVE


def test_visible_name_on_a_full_page_image_stays_native(tmp_path) -> None:
    path = tmp_path / "letterhead.pdf"
    image = Image.new("RGB", (900, 1200), (230, 230, 230))
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    page.insert_text((72, 120), "山田太郎", fontname="japan", fontsize=18)
    doc.save(path)
    doc.close()

    opened = open_document(path)
    assert opened.pages[0].kind == PageKind.NATIVE
    assert any("山田太郎" in line.text for line in opened.pages[0].lines)


def test_short_caption_over_a_large_figure_stays_native(tmp_path) -> None:
    path = tmp_path / "caption.pdf"
    image = Image.new("RGB", (800, 900), (180, 180, 200))
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 64), "別紙のグラフです。", fontname="japan", fontsize=14)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(pymupdf.Rect(0, 160, 595, 842), stream=buffer.getvalue())
    doc.save(path)
    doc.close()
    assert open_document(path).pages[0].kind == PageKind.NATIVE


def test_invisible_opacity_on_a_scan_is_still_scanned(tmp_path) -> None:
    path = tmp_path / "ghost.pdf"
    image = Image.new("RGB", (800, 1000), "white")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    writer = pymupdf.TextWriter(page.rect)
    font = pymupdf.Font("japan")
    writer.append((36, 72), "見えない不透明度ゼロの誤読ダミーQQQQが長い。", font=font, fontsize=12)
    writer.write_text(page, render_mode=0, opacity=0.05)
    doc.save(path)
    doc.close()
    assert open_document(path).pages[0].kind == PageKind.SCANNED


def test_low_resolution_strips_with_an_invisible_layer_are_scanned(tmp_path) -> None:
    path = tmp_path / "thin.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    image = Image.new("RGB", (80, 70), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    blob = buffer.getvalue()
    for index in range(8):
        page.insert_image(
            pymupdf.Rect(0, index * 100, 600, (index + 1) * 100),
            stream=blob,
            keep_proportion=False,
        )
    page.insert_text((24, 40), "誤読ダミーQQQQが細い帯の上に長く置かれている文字層です。", fontname="japan", fontsize=11, render_mode=3)
    doc.save(path)
    doc.close()
    assert open_document(path).pages[0].kind == PageKind.SCANNED


def test_strips_that_miss_a_coarse_grid_are_scanned(tmp_path) -> None:
    path = tmp_path / "gaps.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    image = Image.new("RGB", (120, 40), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    blob = buffer.getvalue()
    top = 11.0
    while top + 18 < 800:
        page.insert_image(pymupdf.Rect(0, top, 600, top + 18), stream=blob, keep_proportion=False)
        top += 20
    page.insert_text((24, 30), "格子の隙間に置いた見えない誤読ダミーQQQQが長い文字層です。", fontname="japan", fontsize=11, render_mode=3)
    doc.save(path)
    doc.close()
    assert open_document(path).pages[0].kind == PageKind.SCANNED


def test_saving_a_scan_before_ocr_keeps_the_old_layer_out(tmp_path) -> None:
    font = ImageFont.truetype(cjk_font(), 42)
    image = Image.new("RGB", (1000, 280), "white")
    ImageDraw.Draw(image).text((40, 80), "株式会社サンプル商事", font=font, fill=0)
    path = tmp_path / "scan.pdf"
    _image_page(path, image, "旧文字層だけにある誤読ダミーQQQQです。画像にはありません。")
    opened = open_document(path)
    dest = tmp_path / "out.pdf"
    with pytest.raises(EkisuiError, match="OCR実行してから保存"):
        export_pdf(opened, [], dest, SaveOptions(export_log=False, strip_metadata=True))
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".partial").exists()


def test_region_on_an_unchanged_page_survives_rebind() -> None:
    native = Page(
        index=0,
        width=600,
        height=840,
        kind=PageKind.NATIVE,
        lines=(
            TextLine("p0l0", 0, "株式会社サンプル商事", Rect(72, 72, 280, 90), 1.0, TextSource.NATIVE),
        ),
    )
    scan = Page(
        index=1,
        width=600,
        height=840,
        kind=PageKind.SCANNED,
        lines=(TextLine("p1l0", 1, "誤読ダミーQQQQ", Rect(72, 72, 240, 90), 1.0, TextSource.NATIVE),),
    )
    opened = Document(source_path="memory.pdf", pages=(native, scan))
    session = Session(opened)
    region = session.add_region(0, Rect(400, 400, 520, 480))
    assert region is not None
    assert region.hits[0].hit.surface == "（範囲）"
    rebuilt = Page(
        index=1,
        width=640,
        height=880,
        kind=PageKind.SCANNED,
        lines=(TextLine("p1o0", 1, "山田太郎", Rect(80, 200, 200, 230), 0.9, TextSource.OCR),),
        image_path="page.png",
        dpi=72,
    )
    session.document = Document(source_path="memory.pdf", pages=(native, rebuilt))
    session.rebind_after_ocr(opened)
    kept = [hit for group in session.groups for hit in group.hits if hit.hit.surface == "（範囲）"]
    assert len(kept) == 1
    assert kept[0].hit.page_index == 0
    assert abs(kept[0].hit.bbox.x0 - 400) < 1
    assert abs(kept[0].hit.bbox.y0 - 400) < 1


def test_checked_candidate_stays_checked_after_rebind() -> None:
    old_page = Page(
        index=0,
        width=600,
        height=840,
        kind=PageKind.SCANNED,
        lines=(TextLine("p0l0", 0, "参照 AB12345678", Rect(72, 72, 280, 90), 1.0, TextSource.NATIVE),),
        source_width=600,
        source_height=840,
    )
    opened = Document(source_path="memory.pdf", pages=(old_page,))
    session = Session(opened)
    session.suggest()
    group = next(item for item in session.groups if "AB12345678" in item.canonical)
    assert group.hits[0].included is False
    group.hits[0].included = True
    group.action = Action.BLACKOUT
    rebuilt = Page(
        index=0,
        width=600,
        height=840,
        kind=PageKind.SCANNED,
        lines=(TextLine("p0o0", 0, "参照 AB12345678", Rect(80, 300, 300, 318), 0.9, TextSource.OCR),),
        image_path="page.png",
        dpi=72,
        source_width=600,
        source_height=840,
    )
    session.document = Document(source_path="memory.pdf", pages=(rebuilt,))
    session.rebind_after_ocr(opened)
    restored = next(item for item in session.groups if "AB12345678" in item.canonical)
    assert restored.action == Action.BLACKOUT
    assert any(hit.included and "AB12345678" in hit.hit.surface for hit in restored.hits)
