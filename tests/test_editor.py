"""The inline OCR field and 確定 stay inside the viewport."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from ekisui.domain.types import Rect, TextLine, TextSource
from ekisui.gui.pageview import PageCanvas, PageView, place_inline_editor


def test_place_inline_editor_clamps_every_edge():
    view = (0.0, 0.0, 420.0, 280.0)
    anchors = [
        (360.0, 40.0, 90.0, 16.0),
        (8.0, 40.0, 40.0, 16.0),
        (40.0, 250.0, 200.0, 16.0),
        (300.0, 240.0, 160.0, 16.0),
    ]
    for scale in (1.0, 1.25, 1.5):
        margin = 4.0 * scale
        for anchor in anchors:
            field, button = place_inline_editor(anchor, view, scale)
            for box in (field, button):
                x, y, width, height = box
                assert x >= view[0] + margin - 1
                assert y >= view[1] + margin - 1
                assert x + width <= view[0] + view[2] - margin + 1
                assert y + height <= view[1] + view[3] - margin + 1
            assert button[2] >= 60 * scale - 2


def test_editor_widget_stays_inside_a_narrow_viewport():
    app = QApplication.instance() or QApplication([])
    canvas = PageCanvas()
    view = PageView(canvas)
    view.resize(360, 220)
    view.show()
    canvas.set_page(None, 900, 400)
    line = TextLine(
        "l0",
        0,
        "所書环官",
        Rect(820, 40, 890, 58),
        0.4,
        TextSource.OCR,
    )
    canvas.lines = [line]
    app.processEvents()
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum())
    canvas.begin_edit(line)
    app.processEvents()
    viewport = view.viewport()
    assert canvas.ok_button.text() == "確定"
    assert canvas.ok_button.toolTip() == "この行の文字を確定します。直した文字で、この行の候補と置換表を更新します。（Enterで確定、Escで取消）"
    visible = canvas._visible_rect()
    for widget in (canvas.editor, canvas.ok_button):
        assert widget.isVisible()
        geo = widget.geometry()
        assert geo.left() >= visible[0] - 1
        assert geo.top() >= visible[1] - 1
        assert geo.right() <= visible[0] + visible[2] + 1
        assert geo.bottom() <= visible[1] + visible[3] + 1
        top_left = viewport.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
        assert top_left.x() >= -1
        assert top_left.y() >= -1
        assert top_left.x() + widget.width() <= viewport.width() + 1
        assert top_left.y() + widget.height() <= viewport.height() + 1

    confirmed: list[tuple[str, str]] = []
    canvas.editConfirmed.connect(lambda line_id, text: confirmed.append((line_id, text)))
    canvas.editor.setText("所書环官")
    app.sendEvent(
        canvas.editor,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier),
    )
    assert confirmed == [("l0", "所書环官")]

    canvas.begin_edit(line)
    app.sendEvent(
        canvas.editor,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier),
    )
    assert canvas.editor.isHidden()
    assert canvas.ok_button.isHidden()
    view.close()
    app.processEvents()
