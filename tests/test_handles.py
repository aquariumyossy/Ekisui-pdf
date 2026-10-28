"""Enter, Esc, and an empty click hide the handles and keep the adjusted range."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import pymupdf
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ekisui.domain.index import _cells
from ekisui.gui import pageview
from ekisui.gui.pageview import _LEFT_TIP, _RIGHT_TIP
from ekisui.gui.window import MainWindow


def _press(canvas, x: float, y: float, button=Qt.MouseButton.LeftButton) -> None:
    pos = QPointF(x, y)
    canvas.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            pos,
            canvas.mapToGlobal(pos.toPoint()),
            button,
            button,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def _window(tmp_path):
    path = tmp_path / "brief.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 80), "被告　山田太郎", fontname="japan", fontsize=14)
    document.save(path)
    document.close()
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    app.processEvents()
    window.open_path(str(path))
    window.session.suggest()
    window.refresh()
    app.processEvents()
    return app, window


def _adjusted(window):
    group = next(item for item in window.session.groups if "太郎" in item.canonical)
    tracked = group.hits[0]
    line = window.session.document.pages[0].lines[0]
    cells = _cells(line)
    rou = line.text.index("郎")
    window.session.adjust_hit(tracked.id, "right", cells[rou].x0)
    window.refresh()
    assert tracked.adjusted
    assert "郎" not in tracked.hit.surface
    canvas = window.view.column.canvases[0]
    return tracked, canvas


def test_handle_tooltips_say_enter_decides() -> None:
    assert _LEFT_TIP == "左にドラッグすると範囲の先頭を1文字ずつ動かします。Enterで決定します。"
    assert _RIGHT_TIP == "右にドラッグすると範囲の末尾を1文字ずつ動かします。Enterで決定します。"


def test_enter_esc_and_empty_click_keep_the_adjusted_range(tmp_path, monkeypatch) -> None:
    app, window = _window(tmp_path)
    tracked, canvas = _adjusted(window)
    surface = tracked.hit.surface
    restored = []
    original = window.session.restore_hit

    def spy(hit_id: str) -> None:
        restored.append(hit_id)
        original(hit_id)

    window.session.restore_hit = spy

    def dismiss(key) -> None:
        window._select_hit(tracked.id)
        canvas.setFocus()
        app.processEvents()
        QTest.keyClick(canvas, key)
        app.processEvents()
        assert window.selected_hit == ""
        assert canvas.selected_hit == ""
        assert tracked.adjusted is True
        assert tracked.hit.surface == surface
        assert restored == []

    dismiss(Qt.Key.Key_Return)
    dismiss(Qt.Key.Key_Enter)
    dismiss(Qt.Key.Key_Escape)

    window._select_hit(tracked.id)
    box = next(hit["bbox"] for hit in canvas.hits if hit["id"] == tracked.id)
    _press(canvas, canvas._origin.x() + box.x1 * canvas.zoom + 30, canvas._origin.y() + box.y0 * canvas.zoom)
    app.processEvents()
    assert window.selected_hit == ""
    assert canvas.selected_hit == ""
    assert tracked.adjusted is True
    assert tracked.hit.surface == surface
    assert restored == []

    window._select_hit(tracked.id)
    box = canvas.hits[0]["bbox"]

    monkeypatch.setattr(pageview, "_exec_menu", lambda menu, _pos: menu.actions()[0])
    _press(
        canvas,
        canvas._origin.x() + (box.x0 + box.x1) / 2 * canvas.zoom,
        canvas._origin.y() + (box.y0 + box.y1) / 2 * canvas.zoom,
        Qt.MouseButton.RightButton,
    )
    app.processEvents()
    assert restored == [tracked.id]
    assert tracked.adjusted is False
    assert "太郎" in tracked.hit.surface
    window.close()
    app.processEvents()


def test_enter_and_esc_stay_in_the_editor_and_the_search_box(tmp_path) -> None:
    app, window = _window(tmp_path)
    tracked, canvas = _adjusted(window)
    surface = tracked.hit.surface
    window._select_hit(tracked.id)
    window.candidates.query.setFocus()
    app.processEvents()
    QTest.keyClick(window.candidates.query, Qt.Key.Key_Return)
    QTest.keyClick(window.candidates.query, Qt.Key.Key_Escape)
    app.processEvents()
    assert window.selected_hit == tracked.id
    assert tracked.adjusted is True
    assert tracked.hit.surface == surface

    line = window.session.document.pages[0].lines[0]
    canvas.begin_edit(line)
    canvas.editor.setText("CHANGED")
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    app.processEvents()
    assert canvas.editor.isVisible()
    assert canvas.editor.text() == "CHANGED"
    assert window.selected_hit == ""
    assert tracked.hit.surface == surface
    window._select_hit(tracked.id)
    box = next(hit["bbox"] for hit in canvas.hits if hit["id"] == tracked.id)
    _press(canvas, canvas._origin.x() + box.x1 * canvas.zoom + 40, canvas._origin.y() + box.y0 * canvas.zoom)
    app.processEvents()
    assert window.selected_hit == ""
    assert canvas.editor.isVisible()
    assert canvas.editor.text() == "CHANGED"
    assert app.focusWidget() is canvas.editor
    window._select_hit(tracked.id)
    canvas.begin_edit(line)
    QTest.keyClick(canvas.editor, Qt.Key.Key_Escape)
    app.processEvents()
    assert canvas.editor.isHidden()
    assert window.selected_hit == tracked.id
    assert tracked.hit.surface == surface

    canvas.begin_edit(line)
    QTest.keyClick(canvas.editor, Qt.Key.Key_Return)
    app.processEvents()
    assert canvas.editor.isHidden()
    assert app.focusWidget() is canvas
    assert window.selected_hit == tracked.id
    assert tracked.adjusted is True
    QTest.keyClick(app.focusWidget(), Qt.Key.Key_Return)
    app.processEvents()
    assert window.selected_hit == ""
    assert tracked.adjusted is True
    assert tracked.hit.surface == surface
    window.close()
    app.processEvents()
