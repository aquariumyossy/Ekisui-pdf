from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLineEdit, QMenu, QPushButton, QScrollArea, QToolTip, QWidget

from ekisui.domain.types import Action, MatchKind, Rect, TextLine
from ekisui.gui.zoom import page_at_scroll, stack_offsets

_HANDLE = 8.0
_PAGE_PAD = 18
_PAGE_GAP = 16
_LEFT_TIP = "左にドラッグすると範囲の先頭を1文字ずつ動かします。Enterで決定します。"
_RIGHT_TIP = "右にドラッグすると範囲の末尾を1文字ずつ動かします。Enterで決定します。"
_MARKER_TIP = "手動で範囲を調整しました。"


def _exec_menu(menu: QMenu, pos) -> object:
    return menu.exec(pos)


def _turn_wheel(view: "PageView", event) -> bool:
    """Scroll the stacked pages, or zoom when Ctrl is held.

    The page widget is what the cursor is over, so this is the handler for
    both the page and the gray margin. Small touchpad deltas accumulate.
    """
    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta:
            factor = 1.15 if delta > 0 else 1 / 1.15
            pos = view.viewport().mapFromGlobal(event.globalPosition().toPoint())
            view.zoomRequested.emit(factor, QPointF(pos), True)
        event.accept()
        return True
    pixel = event.pixelDelta()
    if pixel.isNull():
        angle = event.angleDelta()
        view._wheel_x += angle.x() / 120.0 * 48.0
        view._wheel_y += angle.y() / 120.0 * 48.0
        move_x = int(view._wheel_x)
        move_y = int(view._wheel_y)
        view._wheel_x -= move_x
        view._wheel_y -= move_y
        pixel = QPoint(move_x, move_y)
    if pixel.x() == 0 and pixel.y() == 0:
        event.accept()
        return True
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().value() - pixel.x())
    view.verticalScrollBar().setValue(view.verticalScrollBar().value() - pixel.y())
    event.accept()
    return True


def place_inline_editor(
    anchor: tuple[float, float, float, float],
    view: tuple[float, float, float, float],
    scale: float = 1.0,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """Place the field and 確定 button inside the visible view.

    ``scale`` grows the chrome so tests can imitate 125% and 150%. The widget
    passes 1 because Qt geometry is already in logical pixels.
    """
    ax, ay, aw, _ah = anchor
    vx, vy, vw, vh = view
    scale = max(scale, 0.5)
    margin = 4.0 * scale
    gap = 4.0 * scale
    btn_w = 64.0 * scale
    btn_h = 32.0 * scale
    field_h = 32.0 * scale
    min_w = 180.0 * scale
    left = vx + margin
    top = vy + margin
    right = vx + vw - margin
    bottom = vy + vh - margin
    avail = max(btn_w + gap + 24.0 * scale, right - left)
    field_w = min(max(min_w, aw), max(24.0 * scale, avail - gap - btn_w))
    fx = ax
    bx = fx + field_w + gap
    if bx + btn_w > right or fx < left:
        cluster_right = min(max(ax + aw, left + field_w), right)
        fx = cluster_right - field_w
        bx = fx - gap - btn_w
        if bx < left:
            bx = left
            fx = bx + btn_w + gap
            field_w = max(24.0 * scale, min(field_w, right - fx))
    if fx < left:
        fx = left
    if bx + btn_w > right:
        bx = right - btn_w
        fx = min(fx, bx - gap - field_w)
        if fx < left:
            fx = left
            field_w = max(24.0 * scale, bx - gap - fx)
    fy = ay
    chrome_h = max(field_h, btn_h)
    if fy + chrome_h > bottom:
        fy = ay - chrome_h
    if fy < top:
        fy = top
    if fy + chrome_h > bottom:
        fy = max(top, bottom - chrome_h)

    def box(x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
        return (int(round(x)), int(round(y)), max(1, int(round(w))), max(1, int(round(h))))

    return box(fx, fy, field_w, field_h), box(bx, fy, btn_w, btn_h)


class PageCanvas(QWidget):
    regionChosen = Signal(int, object)
    lineActivated = Signal(str)
    editConfirmed = Signal(str, str)
    editCancelled = Signal()
    hitAdjusted = Signal(str, str, float)
    hitRestore = Signal(str)
    hitSelected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
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
        self.page_index = 0
        self.selected_hit = ""
        self.review_below = 0.80
        self._origin = QPoint(0, 0)
        self._rubber: QRectF | None = None
        self._dragging = False
        self._handle: tuple[str, str] | None = None
        self.editor = QLineEdit(self)
        self.editor.hide()
        self.editor.setFont(QFont(self.font().family(), 12))
        self.editor.returnPressed.connect(self._confirm_edit)
        self.editor.installEventFilter(self)
        self.ok_button = QPushButton("確定", self)
        self.ok_button.setProperty("class", "ib")
        self.ok_button.setToolTip("この行の文字を確定します。直した文字で、この行の候補と置換表を更新します。（Enterで確定、Escで取消）")
        self.ok_button.hide()
        self.ok_button.clicked.connect(self._confirm_edit)
        self._edit_line = ""
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.25, min(zoom, 4.0))
        self._relayout()
        self.reposition_edit()

    def set_page(self, pixmap: QPixmap | None, width: float, height: float) -> None:
        self.pixmap = pixmap
        self.page_w = width
        self.page_h = height
        self.cancel_edit()
        self._relayout()

    def _relayout(self) -> None:
        width = max(1, int(self.page_w * self.zoom)) + _PAGE_PAD * 2
        height = max(1, int(self.page_h * self.zoom)) + _PAGE_PAD * 2
        self.setMinimumSize(width, height)
        self.resize(width, height)
        self._origin = QPoint(_PAGE_PAD, _PAGE_PAD)
        self.update()
        parent = self.parentWidget()
        if isinstance(parent, PageColumn) and not parent._in_layout:
            parent.relayout()

    def page_point(self, pos) -> tuple[float, float]:
        return (
            (pos.x() - self._origin.x()) / self.zoom,
            (pos.y() - self._origin.y()) / self.zoom,
        )

    def begin_edit(self, line: TextLine) -> None:
        self._edit_line = line.id
        self.editor.setText(line.text)
        self._place(line)
        self.editor.show()
        self.ok_button.show()
        self.editor.setFocus()
        self.editor.selectAll()

    def reposition_edit(self, *_args) -> None:
        if not self._edit_line:
            return
        line = next((item for item in self.lines if item.id == self._edit_line), None)
        if line is None:
            return
        self._place(line)

    def _place(self, line: TextLine) -> None:
        rect = self._map(line.bbox)
        field, button = place_inline_editor(
            (rect.x(), rect.y(), rect.width(), rect.height()),
            self._visible_rect(),
            scale=1.0,
        )
        self.editor.setGeometry(*field)
        self.ok_button.setGeometry(*button)

    def _visible_rect(self) -> tuple[float, float, float, float]:
        area = self._scroll_area()
        if area is None:
            return (0.0, 0.0, float(max(self.width(), 1)), float(max(self.height(), 1)))
        viewport = area.viewport()
        # The canvas sits inside the viewport, so map from the parent, not to it.
        origin = self.mapFrom(viewport, QPoint(0, 0))
        return (float(origin.x()), float(origin.y()), float(viewport.width()), float(viewport.height()))

    def _scroll_area(self) -> QScrollArea | None:
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return parent
            parent = parent.parent()
        return None

    def cancel_edit(self) -> None:
        child_focused = self.editor.hasFocus() or self.ok_button.hasFocus()
        self._edit_line = ""
        if child_focused:
            self.setFocus()
        self.editor.hide()
        self.ok_button.hide()

    def _confirm_edit(self) -> None:
        if not self._edit_line:
            return
        line_id = self._edit_line
        text = self.editor.text()
        self.cancel_edit()
        self.editConfirmed.emit(line_id, text)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.editor and event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Escape,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_edit()
                self.editCancelled.emit()
            else:
                self._confirm_edit()
            return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.editor.isVisible():
            self.cancel_edit()
            self.editCancelled.emit()
            return
        if (
            self.selected_hit
            and not self.editor.isVisible()
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape)
        ):
            self._deselect()
            event.accept()
            return
        super().keyPressEvent(event)

    def _deselect(self) -> None:
        """Hide the handles. The adjusted range stays until 自動の範囲に戻す."""
        if not self.selected_hit:
            return
        self.selected_hit = ""
        self._handle = None
        self.update()
        self.hitSelected.emit("")

    def wheelEvent(self, event) -> None:  # noqa: N802
        view = self._scroll_area()
        if isinstance(view, PageView) and _turn_wheel(view, event):
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._popup(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        handle = self._handle_at(event.position())
        if handle is not None and not self.region_mode:
            self._handle = handle
            self.hitSelected.emit(handle[0])
            self.setFocus()
            return
        x, y = self.page_point(event.position())
        if self.region_mode:
            self._dragging = True
            self._rubber = QRectF(x, y, 1, 1)
            self.update()
            return
        hit = self._hit_at(x, y)
        if hit is not None and self.show_hits and not self.show_boxes:
            self.hitSelected.emit(hit["id"])
            self.setFocus()
            return
        if self.show_lines:
            for line in reversed(self.lines):
                if line.bbox.contains(x, y):
                    self.lineActivated.emit(line.id)
                    return
        if self._edit_line:
            self.editor.setFocus()
            return
        if self.selected_hit:
            self._deselect()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._handle is not None:
            x, _y = self.page_point(event.position())
            hit_id, edge = self._handle
            self.hitAdjusted.emit(hit_id, edge, x)
            return
        if self._dragging and self._rubber is not None:
            x, y = self.page_point(event.position())
            start = self._rubber.topLeft()
            self._rubber = QRectF(start.x(), start.y(), x - start.x(), y - start.y()).normalized()
            self.update()
            return
        self._hover_tip(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._handle is not None:
            self._handle = None
            return
        if not self._dragging or self._rubber is None:
            return
        self._dragging = False
        rect = self._rubber
        self._rubber = None
        self.update()
        if rect.width() > 4 and rect.height() > 4:
            self.regionChosen.emit(self.page_index, Rect(rect.x(), rect.y(), rect.right(), rect.bottom()))

    def _popup(self, event) -> None:
        x, y = self.page_point(event.position())
        hit = self._hit_at(x, y)
        if hit is None or not hit.get("adjusted"):
            return
        menu = QMenu(self)
        action = menu.addAction("自動の範囲に戻す")
        if _exec_menu(menu, event.globalPosition().toPoint()) is action:
            self.hitRestore.emit(hit["id"])

    def _hover_tip(self, event) -> None:
        handle = self._handle_at(event.position())
        if handle is not None:
            QToolTip.showText(event.globalPosition().toPoint(), _LEFT_TIP if handle[1] == "left" else _RIGHT_TIP, self)
            return
        x, y = self.page_point(event.position())
        for hit in self.hits:
            if not hit.get("adjusted"):
                continue
            marker = self._marker_rect(self._map(hit["bbox"]))
            if marker.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), _MARKER_TIP, self)
                return

    def _hit_at(self, x: float, y: float) -> dict | None:
        for hit in reversed(self.hits):
            if hit["bbox"].contains(x, y):
                return hit
        return None

    def _handle_at(self, pos: QPointF) -> tuple[str, str] | None:
        if not self.selected_hit or not self.show_hits or self.show_boxes:
            return None
        for hit in self.hits:
            if hit["id"] != self.selected_hit or len(hit.get("line_ids") or ()) > 1:
                continue
            mapped = self._map(hit["bbox"])
            if self._handle_rect(mapped, "left").contains(pos):
                return hit["id"], "left"
            if self._handle_rect(mapped, "right").contains(pos):
                return hit["id"], "right"
        return None

    def _handle_rect(self, mapped: QRectF, edge: str) -> QRectF:
        if edge == "left":
            return QRectF(mapped.left() - _HANDLE / 2, mapped.center().y() - _HANDLE, _HANDLE, _HANDLE * 2)
        return QRectF(mapped.right() - _HANDLE / 2, mapped.center().y() - _HANDLE, _HANDLE, _HANDLE * 2)

    def _marker_rect(self, mapped: QRectF) -> QRectF:
        return QRectF(mapped.right() - 12, mapped.top() + 2, 8, 8)

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
                mapped = self._map(hit["bbox"])
                if kind == MatchKind.EXACT:
                    painter.setPen(QPen(QColor("#d4a000"), 1.4))
                    painter.setBrush(QColor(255, 215, 64, 130))
                else:
                    painter.setPen(QPen(QColor("#d9731a"), 1.4))
                    painter.setBrush(QColor(255, 160, 90, 120))
                if hit["id"] == self.selected_hit:
                    painter.setPen(QPen(QColor("#0f6cbd"), 2.2))
                painter.drawRect(mapped)
                if hit.get("adjusted"):
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#0f6cbd"))
                    painter.drawEllipse(self._marker_rect(mapped))
                if hit["id"] == self.selected_hit and len(hit.get("line_ids") or ()) <= 1:
                    painter.setPen(QPen(QColor("#0f6cbd"), 1.2))
                    painter.setBrush(QColor("#ffffff"))
                    painter.drawRect(self._handle_rect(mapped, "left"))
                    painter.drawRect(self._handle_rect(mapped, "right"))
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


class PageColumn(QWidget):
    """Pages stacked with a gap, so the wheel scrolls from one page into the next."""

    def __init__(self) -> None:
        super().__init__()
        self.canvases: list[PageCanvas] = []
        self._in_layout = False

    def adopt(self, canvas: PageCanvas) -> None:
        canvas.setParent(self)
        canvas.page_index = 0
        self.canvases = [canvas]
        self.relayout()

    def set_count(self, count: int) -> None:
        while len(self.canvases) < count:
            canvas = PageCanvas(self)
            canvas.page_index = len(self.canvases)
            self.canvases.append(canvas)
        while len(self.canvases) > count:
            canvas = self.canvases.pop()
            canvas.hide()
            canvas.setParent(None)
            canvas.deleteLater()
        for index, canvas in enumerate(self.canvases):
            canvas.page_index = index
            canvas.show()
        self.relayout()

    def relayout(self) -> None:
        self._in_layout = True
        try:
            sizes = [(canvas.width(), canvas.height()) for canvas in self.canvases]
            placed = stack_offsets(sizes, _PAGE_GAP)
            width = 1
            bottom = 1
            for canvas, (x, y) in zip(self.canvases, placed):
                canvas.move(x, y)
                width = max(width, x + canvas.width())
                bottom = y + canvas.height()
            self.resize(max(1, width), max(1, bottom))
        finally:
            self._in_layout = False

    def wheelEvent(self, event) -> None:  # noqa: N802
        parent = self.parent()
        while parent is not None and not isinstance(parent, PageView):
            parent = parent.parent()
        if isinstance(parent, PageView) and _turn_wheel(parent, event):
            return
        super().wheelEvent(event)


class PageView(QScrollArea):
    zoomRequested = Signal(float, QPointF, bool)
    pageScrolled = Signal(int)

    def __init__(self, canvas: PageCanvas | None = None) -> None:
        super().__init__()
        self.column = PageColumn()
        self.setWidget(self.column)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setStyleSheet("QScrollArea { background: #d9dbde; border: none; }")
        self.viewport().installEventFilter(self)
        self.viewport().grabGesture(Qt.GestureType.PinchGesture)
        self._lock = False
        self._wheel_x = 0.0
        self._wheel_y = 0.0
        self.horizontalScrollBar().valueChanged.connect(self._reposition_edits)
        self.verticalScrollBar().valueChanged.connect(self._reposition_edits)
        self.verticalScrollBar().valueChanged.connect(self._emit_page)
        if canvas is not None:
            self.column.adopt(canvas)

    def ensure_pages(self, count: int) -> list[PageCanvas]:
        if len(self.column.canvases) != count:
            self.column.set_count(count)
        return self.column.canvases

    def canvas_for(self, index: int) -> PageCanvas:
        return self.column.canvases[index]

    def scroll_to_page(self, index: int) -> None:
        if index < 0 or index >= len(self.column.canvases):
            return
        self._lock = True
        self.verticalScrollBar().setValue(self.column.canvases[index].y())
        self._lock = False

    def _reposition_edits(self, *_args) -> None:
        for canvas in self.column.canvases:
            canvas.reposition_edit()

    def _emit_page(self, *_args) -> None:
        if self._lock or not self.column.canvases:
            return
        spans = [(canvas.y(), canvas.height()) for canvas in self.column.canvases]
        index = page_at_scroll(spans, self.verticalScrollBar().value(), self.viewport().height(), _PAGE_GAP)
        self.pageScrolled.emit(index)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reposition_edits()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.viewport() and event.type() == QEvent.Type.Wheel:
            return _turn_wheel(self, event)
        if obj is self.viewport() and event.type() == QEvent.Type.NativeGesture:
            if event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                factor = 1.0 + float(event.value())
                self.zoomRequested.emit(factor, QPointF(event.position()), bool(event.isEndEvent()))
                return True
        return super().eventFilter(obj, event)

    def viewportEvent(self, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Gesture:
            pinch = event.gesture(Qt.GestureType.PinchGesture)
            if pinch is not None and pinch.state() != Qt.GestureState.GestureCanceled:
                done = pinch.state() == Qt.GestureState.GestureFinished
                factor = float(pinch.scaleFactor()) or 1.0
                self.zoomRequested.emit(factor, QPointF(pinch.centerPoint()), done)
                return True
        return super().viewportEvent(event)
