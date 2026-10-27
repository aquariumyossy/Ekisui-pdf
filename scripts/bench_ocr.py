"""1ページ分のOCR時間を測る。モデル取得後に実行する。"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf

from ekisui_pdf.core.ocr import create_engine, recognize_image, render_page_bgr
from tests.factories import scanned_pdf


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "bench.pdf"
        scanned_pdf(
            pdf_path,
            [["第%d条 甲株式会社と山田太郎は、本件について合意する。" % index for index in range(1, 13)]],
        )
        document = pymupdf.open(pdf_path)
        try:
            image, zoom = render_page_bgr(document[0], dpi=200)
        finally:
            document.close()
    engine = create_engine()
    recognize_image(engine, image, page_index=0, zoom=zoom)
    started = time.perf_counter()
    lines = recognize_image(engine, image, page_index=0, zoom=zoom)
    elapsed = time.perf_counter() - started
    print(f"OCR_SECONDS_PER_PAGE={elapsed:.3f}")
    print(f"OCR_LINES={len(lines)}")
    print(f"OCR_DPI=200")


if __name__ == "__main__":
    main()
