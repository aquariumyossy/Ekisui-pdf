from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from ekisui_pdf.core.models import Rect


def pixmap_to_qimage(pixmap) -> QImage:
    if pixmap.n == 4:
        image_format = QImage.Format.Format_RGBA8888
    else:
        image_format = QImage.Format.Format_RGB888
    image = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, image_format)
    return image.copy()


class PageView(QGraphicsView):
    region_selected = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#d9d3c7"))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._zoom = 1.0
        self._scale = 1.0
        self._origin = None
        self._rubber = None
        self._overlays: list = []

    def set_page_image(self, image: QImage, pdf_width: float, pdf_height: float) -> None:
        self.scene().clear()
        self._overlays = []
        self._rubber = None
        self._origin = None
        item = self.scene().addPixmap(QPixmap.fromImage(image))
        self._scale = item.pixmap().width() / pdf_width if pdf_width else 1.0
        self.scene().setSceneRect(0, 0, item.pixmap().width(), max(item.pixmap().height(), pdf_height * self._scale))
        self._apply_zoom()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = min(4.0, max(0.25, zoom))
        self._apply_zoom()

    def zoom(self) -> float:
        return self._zoom

    def _apply_zoom(self) -> None:
        self.resetTransform()
        self.scale(self._zoom, self._zoom)

    def set_overlays(self, boxes: list[tuple[Rect, QColor]]) -> None:
        for item in self._overlays:
            self.scene().removeItem(item)
        self._overlays = []
        for rect, color in boxes:
            pen = QPen(color, 2)
            fill = QColor(color)
            fill.setAlpha(50)
            item = self.scene().addRect(
                rect.x0 * self._scale,
                rect.y0 * self._scale,
                max(rect.width, 0.5) * self._scale,
                max(rect.height, 0.5) * self._scale,
                pen,
            )
            item.setBrush(fill)
            self._overlays.append(item)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
            self.set_zoom(self._zoom * factor)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.scene().items():
            self._origin = self.mapToScene(event.position().toPoint())
            self._rubber = self.scene().addRect(
                QRectF(self._origin, self._origin),
                QPen(QColor("#9b2c2c"), 1, Qt.PenStyle.DashLine),
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._origin is not None and self._rubber is not None:
            current = self.mapToScene(event.position().toPoint())
            self._rubber.setRect(QRectF(self._origin, current).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._origin is not None and self._rubber is not None:
            scene_rect = self._rubber.rect()
            self.scene().removeItem(self._rubber)
            self._rubber = None
            self._origin = None
            if scene_rect.width() > 6 and scene_rect.height() > 6 and self._scale:
                self.region_selected.emit(
                    Rect(
                        scene_rect.left() / self._scale,
                        scene_rect.top() / self._scale,
                        scene_rect.right() / self._scale,
                        scene_rect.bottom() / self._scale,
                    )
                )
            event.accept()
            return
        super().mouseReleaseEvent(event)
