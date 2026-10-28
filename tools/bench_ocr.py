"""Time one CPU page after the models are loaded. Prints seconds, does not download."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ekisui.pdf.ocr_engine import PpOcrV5
from fonts import cjk_font


def main() -> None:
    font = ImageFont.truetype(cjk_font(), 42)
    image = Image.new("RGB", (1654, 1200), "white")
    draw = ImageDraw.Draw(image)
    y = 80
    for text in (
        "株式会社サンプル商事",
        "被告　山田太郎",
        "東京都千代田区架空町1-2-3",
        "電話03-1234-5678",
        "taro.yamada@example.jp",
        "口座番号1234567",
        "準備書面の本文です。横書きのスキャンを想定しています。",
    ):
        draw.text((80, y), text, font=font, fill=0)
        y += 120
    array = np.asarray(image)
    engine = PpOcrV5()
    engine.read(array)
    started = time.perf_counter()
    lines = engine.read(array)
    elapsed = time.perf_counter() - started
    text = "".join(line.text for line in lines)
    print(f"{elapsed:.2f} seconds/page")
    print(text)


if __name__ == "__main__":
    main()
