"""Headless check that the frozen app can still read, search, and redact.

The page list is one born-digital page and one scanned page with a fax-style
vector header drawn over the image. OCR, redaction, and the leftover check
all run in-process. ``--smoke`` writes smoke.log because the Windows exe has
no console.
"""

from __future__ import annotations

import io
import os
import traceback
from pathlib import Path

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/YuGothR.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "C:/Windows/Fonts/msmincho.ttc",
)


def run(directory: str | Path) -> int:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "smoke.log"
    lines: list[str] = ["SMOKE_START"]
    log_path.write_text("SMOKE_START\n", encoding="utf-8")

    def note(message: str) -> None:
        lines.append(message)
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    try:
        _run(out, note)
    except Exception:
        note(traceback.format_exc())
        note("SMOKE_FAIL")
        return 1
    note("SMOKE_OK")
    return 0


def _run(out: Path, note) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    from PIL import Image, ImageDraw, ImageFont
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    import pymupdf

    from ekisui.domain.normalize import strict_text
    from ekisui.domain.session import Session
    from ekisui.domain.types import Action, PageKind, SaveOptions, Settings
    from ekisui.pdf.document import open_document, recognize
    from ekisui.pdf.export import export_pdf
    from ekisui.pdf.ocr_engine import PpOcrV5
    from ekisui.pdf.verify import verify_pdf
    from ekisui.paths import model_dir

    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    QLabel("易水", widget)
    widget.show()
    app.processEvents()
    dot = out / "dot.png"
    Image.new("RGB", (4, 4), (12, 24, 36)).save(dot)
    pixmap = QPixmap(str(dot))
    if pixmap.isNull():
        raise RuntimeError("QPixmap could not load a PNG")
    note(f"QT_PNG {pixmap.width()}x{pixmap.height()}")
    note(f"MODEL_DIR {model_dir()}")

    source = out / "sample.pdf"
    _write_sample(source, _cjk_font(), Image, ImageDraw, ImageFont, pymupdf)
    opened = open_document(source)
    if opened.pages[0].kind != PageKind.NATIVE:
        raise RuntimeError(f"born-digital page classified as {opened.pages[0].kind}")
    if opened.pages[1].kind != PageKind.SCANNED:
        raise RuntimeError(f"mixed page classified as {opened.pages[1].kind}")

    native = "".join(line.text for line in opened.pages[0].lines)
    native_flat = "".join(native.split())
    if "依頼者" not in native_flat or "山田太郎" not in native_flat:
        raise RuntimeError(f"native extraction missed the sentence: {native_flat}")
    note(f"NATIVE_EXTRACT {native_flat}")

    before = Session(opened, Settings())
    native_hit = before.add_phrase("山田太郎")
    if native_hit is None or not any(hit.hit.page_index == 0 for hit in native_hit.included_hits()):
        raise RuntimeError("term search missed 山田太郎 on the born-digital page")
    note(f"NATIVE_SEARCH {len(native_hit.included_hits())}")

    recognized = recognize(opened, Settings(ocr_dpi=72, deskew=True), PpOcrV5(), out / "work")
    scan_text = "".join(line.text for line in recognized.pages[1].lines)
    if "佐藤花子" not in strict_text(scan_text):
        raise RuntimeError(f"OCR missed 佐藤花子: {scan_text}")
    if not any(line.visible and "FAX" in line.text for line in recognized.pages[1].lines):
        raise RuntimeError("fax header was not kept as visible vector text")
    note("SCAN_OCR 佐藤花子")
    note("FAX_HEADER kept")

    session = Session(recognized, Settings())
    born = session.add_phrase("山田太郎")
    scanned = session.add_phrase("佐藤花子")
    if born is None or scanned is None:
        raise RuntimeError("term search missed a name after OCR")
    born.action = Action.BLACKOUT
    scanned.action = Action.BLACKOUT
    dest = out / "sample_墨消し.pdf"
    export_pdf(
        recognized,
        [born, scanned],
        dest,
        SaveOptions(align_box_width=False, strip_metadata=True, export_log=False, export_replacement_table=False),
        Settings(),
    )
    saved = pymupdf.open(dest)
    try:
        page0 = "".join(saved[0].get_text().split())
        page1 = "".join(saved[1].get_text().split())
    finally:
        saved.close()
    if "依頼者" not in page0:
        raise RuntimeError(f"born-digital sentence was removed: {page0}")
    if "太郎" in page0 or "花子" in page1:
        raise RuntimeError(f"a redacted name is still searchable: {page0} | {page1}")
    if "FAX" not in page1 or "2222" not in page1:
        raise RuntimeError(f"fax header did not survive redaction: {page1}")
    note(f"NATIVE_REDACT {page0}")
    note("FAX_KEPT")
    note("SCAN_NAME_REMOVED")

    report = verify_pdf(str(dest), [born, scanned], Settings(), session.table, check_metadata=True)
    if not report.passed:
        detail = ", ".join(f"p{item.page_index}:{item.term}" for item in report.leftovers)
        raise RuntimeError(f"leftover check failed metadata={report.metadata_clean} leftovers={detail}")
    note("LEFTOVER_CHECK passed")


def _cjk_font() -> str:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise FileNotFoundError("no CJK font for the smoke scan page")


def _write_sample(path: Path, font_path: str, image_cls, draw_cls, font_cls, pymupdf) -> None:
    font = font_cls.truetype(font_path, 48)
    image = image_cls.new("RGB", (1100, 420), "white")
    draw_cls.Draw(image).text((60, 180), "佐藤花子", font=font, fill=0)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    doc = pymupdf.open()
    born = doc.new_page(width=595, height=842)
    born.insert_text((72, 120), "依頼者は山田太郎です", fontname="japan", fontsize=16)
    mixed = doc.new_page(width=image.width, height=image.height)
    mixed.insert_image(mixed.rect, stream=buffer.getvalue())
    mixed.insert_text((40, 36), "FAX送信 03-1111-2222", fontname="japan", fontsize=14)
    doc.save(path)
    doc.close()
