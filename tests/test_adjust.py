"""Dragging a box snaps to character cells and the log records 手動."""

from ekisui.domain.adjust import move_edge, snap_boundary
from ekisui.domain.index import _cells
from ekisui.domain.session import Session
from ekisui.domain.types import Rect, SaveOptions, Settings
from ekisui.pdf.export import redaction_boxes, write_log
from ekisui.pdf.verify import _queries_for

from factory import document_from_lines


def test_snap_and_clamp():
    cells = [Rect(index * 10, 0, (index + 1) * 10, 12) for index in range(6)]
    assert snap_boundary(cells, 1) == 0
    assert snap_boundary(cells, 9) == 1
    assert snap_boundary(cells, 58) == 6
    assert move_edge(2, 5, "left", 0, 8) == (0, 5)
    assert move_edge(2, 5, "left", 9, 8) == (4, 5)
    assert move_edge(2, 5, "right", 2, 8) == (2, 3)
    assert move_edge(2, 5, "right", 100, 8) == (2, 8)


def test_adjust_updates_surface_log_and_restore(tmp_path):
    session = Session(document_from_lines([["被告 山田太郎は出席した"]]), Settings())
    session.suggest()
    group = next(item for item in session.groups if "太郎" in item.canonical)
    tracked = group.hits[0]
    line = session.document.pages[0].lines[0]
    cells = _cells(line)
    rou = line.text.index("郎")
    session.adjust_hit(tracked.id, "right", cells[rou].x0)
    assert tracked.adjusted
    assert "郎" not in tracked.hit.surface
    assert "山田" in tracked.hit.surface
    queries = _queries_for(group)
    assert group.canonical not in queries
    assert tracked.hit.surface in queries

    boxes = redaction_boxes(session.document, session.groups, SaveOptions(align_box_width=False), Settings())
    log_path = tmp_path / "log.csv"
    write_log(log_path, boxes, include_original=False)
    text = log_path.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0] == "ページ,左,上,右,下,種類,呼び名,調整"
    assert "手動" in text

    session.restore_hit(tracked.id)
    assert tracked.adjusted is False
    assert "太郎" in tracked.hit.surface
    assert _queries_for(group) == [group.canonical]
