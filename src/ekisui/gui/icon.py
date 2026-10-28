"""Window icon loaded from every frame of assets/icon/ekisui.ico.

Each frame is a PNG. Qt's ICO plugin is not in the frozen app, and PNG
decoding is built into Qt Gui, so the frames are decoded as PNG.
"""

from __future__ import annotations

import struct

from PySide6.QtGui import QIcon, QImage, QPixmap

from ekisui.paths import icon_file


def ico_png_frames(data: bytes) -> list[tuple[int, int, bytes]]:
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or kind != 1 or count < 1:
        return []
    frames = []
    for index in range(count):
        width, height, _colors, _reserved, _planes, _bits, size, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * index
        )
        blob = data[offset : offset + size]
        if blob.startswith(b"\x89PNG\r\n\x1a\n"):
            frames.append((width or 256, height or 256, blob))
    return frames


def load_app_icon() -> QIcon:
    """Add each size in the ICO so the taskbar can pick 16, 32, or 256."""
    icon = QIcon()
    path = icon_file()
    if not path.is_file():
        return icon
    for _width, _height, blob in ico_png_frames(path.read_bytes()):
        image = QImage.fromData(blob)
        if not image.isNull():
            icon.addPixmap(QPixmap.fromImage(image))
    return icon
