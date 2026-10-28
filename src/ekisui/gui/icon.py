"""Window icon loaded from every frame of assets/icon/ekisui.ico."""

from __future__ import annotations

from PySide6.QtGui import QIcon, QImageReader, QPixmap

from ekisui.paths import icon_file


def load_app_icon() -> QIcon:
    """Add each size in the ICO so the taskbar can pick 16, 32, or 256."""
    icon = QIcon()
    path = icon_file()
    if not path.is_file():
        return icon
    reader = QImageReader(str(path))
    count = reader.imageCount()
    if count <= 0:
        icon.addFile(str(path))
        return icon
    for index in range(count):
        reader.jumpToImage(index)
        image = reader.read()
        if not image.isNull():
            icon.addPixmap(QPixmap.fromImage(image))
    return icon
