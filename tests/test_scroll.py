"""Wheel scrolling moves through stacked pages. Ctrl+wheel still zooms."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from ekisui.gui.pageview import PageCanvas, PageView


def test_scrollbar_reaches_the_next_page():
    app = QApplication.instance() or QApplication([])
    view = PageView()
    view.ensure_pages(2)
    view.canvas_for(0).set_page(None, 280, 640)
    view.canvas_for(1).set_page(None, 280, 640)
    view.resize(320, 180)
    view.show()
    app.processEvents()
    seen: list[int] = []
    view.pageScrolled.connect(seen.append)
    bar = view.verticalScrollBar()
    bar.setValue(bar.maximum())
    app.processEvents()
    assert bar.maximum() > view.canvas_for(0).height()
    assert seen[-1] == 1
    bar.setValue(0)
    app.processEvents()
    assert seen[-1] == 0
    view.scroll_to_page(1)
    assert bar.value() == view.canvas_for(1).y()
    view.close()
    app.processEvents()


def test_ctrl_wheel_zooms_and_plain_wheel_does_not():
    app = QApplication.instance() or QApplication([])
    view = PageView()
    view.ensure_pages(1)
    view.canvas_for(0).set_page(None, 400, 800)
    view.resize(300, 200)
    view.show()
    app.processEvents()
    zooms: list[float] = []
    view.zoomRequested.connect(lambda factor, _pos, _done: zooms.append(factor))

    plain = QWheelEvent(
        QPointF(40, 40),
        QPointF(40, 40),
        QPoint(0, -40),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    before = view.verticalScrollBar().value()
    assert view.eventFilter(view.viewport(), plain) is True
    assert zooms == []
    assert view.verticalScrollBar().value() > before

    on_page = QWheelEvent(
        QPointF(20, 20),
        QPointF(20, 20),
        QPoint(0, -30),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    page_before = view.verticalScrollBar().value()
    app.sendEvent(view.canvas_for(0), on_page)
    app.processEvents()
    assert view.verticalScrollBar().value() > page_before

    controlled = QWheelEvent(
        QPointF(40, 40),
        QPointF(40, 40),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    assert view.eventFilter(view.viewport(), controlled) is True
    assert zooms == [1.15]
    on_page_zoom = QWheelEvent(
        QPointF(20, 20),
        view.canvas_for(0).mapToGlobal(QPoint(20, 20)),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    app.sendEvent(view.canvas_for(0), on_page_zoom)
    app.processEvents()
    assert zooms[-1] == 1.15
    assert len(zooms) == 2
    view.close()
    app.processEvents()
