from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLineEdit, QPushButton, QScrollArea, QWidget

from ekisui.domain.types import Action, MatchKind, Rect, TextLine


class PageCanvas(QWidget):
    regionChosen = Signal(object)
    lineActivated = Signal(str)
    editConfirmed = Signal(str, str)
    editCancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("canvasHost")
        self.pixmap: QPixmap | None = None
        self.page_w = 595.0
        self.page_h = 842.0
        self.zoom = 1.0
        self.hits: list[dict] = []
        self.lines: list[TextLine] = []
        self.boxes: list[dict] = []
        self.show_hits = True
        self.show_lines = False
        self.show_boxes = False
        self.region_mode = False
        self.selected_hit = ""
        self.review_below = 0.80
        self._origin = QPoint(0, 0)
        self._rubber: QRectF | None = None
        self._dragging = False
        self.editor = QLineEdit(self)
        self.editor.hide()
        self.editor.setFont(QFont(self.font().family(), 12))
        self.editor.returnPressed.connect(self._confirm_edit)
        self.ok_button = QPushButton("確定", self)
        self.ok_button.setProperty("class", "ib")
        self.ok_button.setToolTip("Enterで確定・Escで取消")
        self.ok_button.hide()
        self.ok_button.clicked.connect(self._confirm_edit)
        self._edit_line = ""
        self.setMouseTracking(True)

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.25, min(zoom, 4.0))
        self._relayout()

    def set_page(self, pixmap: QPixmap | None, width: float, height: float) -> None:
        self.pixmap = pixmap
        self.page_w = width
        self.page_h = height
        self.cancel_edit()
        self._relayout()

    def _relayout(self) -> None:
        width = max(1, int(self.page_w * self.zoom))
        height = max(1, int(self.page_h * self.zoom))
        self.setMinimumSize(width + 36, height + 36)
        self.resize(width + 36, height + 36)
        self._origin = QPoint(18, 18)
        self.update()

    def page_point(self, pos) -> tuple[float, float]:
        return (
            (pos.x() - self._origin.x()) / self.zoom,
            (pos.y() - self._origin.y()) / self.zoom,
        )

    def begin_edit(self, line: TextLine) -> None:
        self._edit_line = line.id
        self.editor.setText(line.text)
        rect = self._map(line.bbox)
        self.editor.setGeometry(int(rect.x()), int(rect.y()), max(180, int(rect.width())), 32)
        self.ok_button.setGeometry(self.editor.geometry().right() + 4, int(rect.y()), 64, 32)
        self.editor.show()
        self.ok_button.show()
        self.editor.setFocus()
        self.editor.selectAll()

    def cancel_edit(self) -> None:
        self._edit_line = ""
        self.editor.hide()
        self.ok_button.hide()

    def _confirm_edit(self) -> None:
        if not self._edit_line:
            return
        line_id = self._edit_line
        text = self.editor.text()
        self.cancel_edit()
        self.editConfirmed.emit(line_id, text)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.editor.isVisible():
            self.cancel_edit()
            self.editCancelled.emit()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = self.page_point(event.position())
        if self.region_mode:
            self._dragging = True
            self._rubber = QRectF(x, y, 1, 1)
            self.update()
            return
        if self.show_lines:
            for line in reversed(self.lines):
                if line.bbox.contains(x, y):
                    self.lineActivated.emit(line.id)
                    return

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._dragging or self._rubber is None:
            return
        x, y = self.page_point(event.position())
        self._rubber.setBottomRight(self._rubber.topLeft() + QPoint(0, 0))
        start = self._rubber.topLeft()
        self._rubber = QRectF(start.x(), start.y(), x - start.x(), y - start.y()).normalized()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if not self._dragging or self._rubber is None:
            return
        self._dragging = False
        rect = self._rubber
        self._rubber = None
        self.update()
        if rect.width() > 4 and rect.height() > 4:
            self.regionChosen.emit(Rect(rect.x(), rect.y(), rect.right(), rect.bottom()))

    def _map(self, rect: Rect) -> QRectF:
        return QRectF(
            self._origin.x() + rect.x0 * self.zoom,
            self._origin.y() + rect.y0 * self.zoom,
            max(1.0, rect.width * self.zoom),
            max(1.0, rect.height * self.zoom),
        )

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#d9dbde"))
        page = QRectF(self._origin.x(), self._origin.y(), self.page_w * self.zoom, self.page_h * self.zoom)
        painter.fillRect(page, QColor("#fdfdfb"))
        painter.setPen(QPen(QColor("#c8c8c8")))
        painter.drawRect(page)
        if self.pixmap is not None and not self.pixmap.isNull():
            painter.drawPixmap(page.toRect(), self.pixmap)
        if self.show_lines:
            for line in self.lines:
                low = line.confidence < self.review_below and line.source.value != "corrected"
                color = QColor("#c42b1c") if low else QColor(15, 108, 189, 160)
                painter.setPen(QPen(color, 1.4))
                painter.setBrush(QColor(15, 108, 189, 16) if not low else QColor(196, 43, 28, 18))
                painter.drawRect(self._map(line.bbox))
        if self.show_hits and not self.show_boxes:
            for hit in self.hits:
                kind = hit["kind"]
                if kind == MatchKind.EXACT:
                    painter.setPen(QPen(QColor("#d4a000"), 1.4))
                    painter.setBrush(QColor(255, 215, 64, 130))
                else:
                    painter.setPen(QPen(QColor("#d9731a"), 1.4))
                    painter.setBrush(QColor(255, 160, 90, 120))
                if hit["id"] == self.selected_hit:
                    painter.setPen(QPen(QColor("#0f6cbd"), 2.2))
                painter.drawRect(self._map(hit["bbox"]))
        if self.show_boxes:
            for box in self.boxes:
                mapped = self._map(box["rect"])
                if box["action"] == Action.REPLACE:
                    painter.setPen(QPen(QColor("#333333"), 1))
                    painter.setBrush(QColor("#ffffff"))
                    painter.drawRect(mapped)
                    painter.setPen(QColor("#111111"))
                    painter.setFont(QFont(self.font().family(), 10))
                    painter.drawText(mapped, Qt.AlignmentFlag.AlignCenter, box.get("text") or "")
                else:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#111111"))
                    painter.drawRect(mapped)
        if self._rubber is not None:
            painter.setPen(QPen(QColor("#0f6cbd"), 2, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(15, 108, 189, 28))
            painter.drawRect(self._map(Rect(self._rubber.x(), self._rubber.y(), self._rubber.right(), self._rubber.bottom())))
        painter.end()


class PageView(QScrollArea):
    def __init__(self, canvas: PageCanvas) -> None:
        super().__init__()
        self.setWidget(canvas)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setStyleSheet("QScrollArea { background: #d9dbde; border: none; }")
