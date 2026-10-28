from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QLayout,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ekisui.domain.types import CATEGORY_LABEL, Action, Category, MatchKind, TextSource


class FlowLayout(QLayout):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSpacing(4)
        self._items: list = []

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._flow(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._flow(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size + QSize(8, 8)

    def _flow(self, rect: QRect, apply: bool) -> int:
        x = rect.x()
        y = rect.y()
        line_h = 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() and line_h:
                x = rect.x()
                y += line_h + self.spacing()
                line_h = 0
            if apply:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x += hint.width() + self.spacing()
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class CandidatePanel(QWidget):
    searchRequested = Signal(str)
    toggled = Signal(str, bool)
    actionChanged = Signal(str, object)
    pseudonymEdited = Signal(str, str)
    activated = Signal(str)
    reviewed = Signal(str)
    excludeRequested = Signal()
    confirmRequested = Signal()
    selectAll = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("語句")
        self.query.setToolTip("マスキングする語句を入力します。（Ctrl+F）")
        self.query.returnPressed.connect(lambda: self.searchRequested.emit(self.query.text()))
        find = QPushButton("探す")
        find.setProperty("class", "primary")
        find.setToolTip("入力した語句を探し、マスキング候補に加えます。")
        find.clicked.connect(lambda: self.searchRequested.emit(self.query.text()))
        row.addWidget(self.query, 1)
        row.addWidget(find)
        root.addLayout(row)
        self.chip_host = QWidget()
        self.chips = FlowLayout(self.chip_host)
        root.addWidget(self.chip_host)
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        self.filter: Category | None = None
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_layout.addStretch(1)
        scroll.setWidget(self.list_host)
        root.addWidget(scroll, 1)
        foot = QHBoxLayout()
        self.count = QLabel("選択 0 / 0")
        self.count.setProperty("class", "sub")
        exclude = QPushButton("除外")
        exclude.setProperty("class", "btn")
        exclude.setToolTip("チェックを外した候補を、一覧から消します。")
        exclude.clicked.connect(self.excludeRequested.emit)
        foot.addWidget(self.count)
        foot.addStretch(1)
        foot.addWidget(exclude)
        root.addLayout(foot)
        self._apply_props()

    def set_hits(self, rows: list[dict], counts: dict) -> None:
        while self.chips.count():
            item = self.chips.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        total = sum(counts.values())
        self._add_chip("すべて", None, total)
        for category in Category:
            if counts.get(category):
                self._add_chip(CATEGORY_LABEL[category], category, counts[category])
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        shown = 0
        included = 0
        for row in rows:
            if self.filter is not None and row["category"] != self.filter:
                continue
            shown += 1
            if row["included"]:
                included += 1
            self.list_layout.insertWidget(self.list_layout.count() - 1, self._row(row))
        self.count.setText(f"選択 {included} / {shown}")
        self.chip_host.setMinimumHeight(max(36, self.chips.heightForWidth(340)))

    def _add_chip(self, label: str, category: Category | None, count: int) -> None:
        button = QPushButton(f"{label} {count}")
        button.setProperty("class", "chip")
        button.setCheckable(True)
        button.setChecked(self.filter == category)
        button.clicked.connect(lambda _checked=False, cat=category: self._set_filter(cat))
        self._chip_group.addButton(button)
        self.chips.addWidget(button)
        self._style(button)

    def _set_filter(self, category: Category | None) -> None:
        self.filter = category
        self.selectAll.emit(True)

    def _row(self, row: dict) -> QWidget:
        frame = QFrame()
        frame.setProperty("class", "row")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        top = QHBoxLayout()
        bottom = QHBoxLayout()
        box = QPushButton("✓" if row["included"] else "")
        box.setFixedSize(22, 22)
        box.setCheckable(True)
        box.setChecked(row["included"])
        box.clicked.connect(lambda checked, hit_id=row["hit_id"]: self.toggled.emit(hit_id, checked))
        text = QLabel(row["surface"])
        text.setWordWrap(True)
        text.setMinimumWidth(80)
        text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        kind = QLabel(row["label"])
        kind.setProperty("class", "exact" if row["kind"] == MatchKind.EXACT else "fuzzy")
        kind.setToolTip(row["tip"])
        black = QPushButton("黒塗り")
        black.setProperty("class", "seg")
        black.setCheckable(True)
        black.setChecked(row["action"] == Action.BLACKOUT)
        repl = QPushButton("置換")
        repl.setProperty("class", "segRep")
        repl.setCheckable(True)
        repl.setChecked(row["action"] == Action.REPLACE)
        black.clicked.connect(lambda _c=False, gid=row["group_id"]: self.actionChanged.emit(gid, Action.BLACKOUT))
        repl.clicked.connect(lambda _c=False, gid=row["group_id"]: self.actionChanged.emit(gid, Action.REPLACE))
        page = QLabel(f"p.{row['page'] + 1}")
        page.setProperty("class", "sub")
        top.addWidget(box)
        top.addWidget(text, 1)
        if row.get("adjusted"):
            mark = QLabel("手動")
            mark.setProperty("class", "sub")
            mark.setToolTip("手動で範囲を調整しました。")
            top.addWidget(mark)
        if row.get("needs_review"):
            review = QPushButton("要確認")
            review.setProperty("class", "ib")
            review.setToolTip("OCR修正で変わった候補です。確認するまで、確定できません。")
            review.clicked.connect(lambda _c=False, hit_id=row["hit_id"]: self.reviewed.emit(hit_id))
            top.addWidget(review)
        elif row.get("ocr_changed"):
            note = QLabel("OCR修正で変更")
            note.setProperty("class", "sub")
            note.setToolTip("OCR修正で変わった候補です。確認済みです。")
            top.addWidget(note)
        top.addWidget(page)
        bottom.addWidget(kind)
        bottom.addWidget(black)
        bottom.addWidget(repl)
        if row["action"] == Action.REPLACE:
            name = QPushButton(row["pseudonym"] or "呼び名")
            name.setProperty("class", "ib")
            name.setToolTip("置換後の呼び名を編集します。")
            name.clicked.connect(lambda _c=False, gid=row["group_id"], current=row["pseudonym"] or "": self._edit_name(gid, current))
            bottom.addWidget(name)
        bottom.addStretch(1)
        layout.addLayout(top)
        layout.addLayout(bottom)
        text.mousePressEvent = lambda _event, hit_id=row["hit_id"]: self.activated.emit(hit_id)  # type: ignore[method-assign]
        for widget in (box, text, kind, black, repl, page):
            self._style(widget)
        return frame

    def _edit_name(self, group_id: str, current: str) -> None:
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, "呼び名", "呼び名", text=current)
        if ok:
            self.pseudonymEdited.emit(group_id, text)

    def _apply_props(self) -> None:
        for widget in self.findChildren(QWidget):
            self._style(widget)

    @staticmethod
    def _style(widget: QWidget) -> None:
        kind = widget.property("class")
        if kind:
            widget.setProperty("class", kind)
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class TablePanel(QWidget):
    includeVariant = Signal(str)
    removeVariant = Signal(str)
    addVariant = Signal(str)
    renumberRequested = Signal()
    saveRequested = Signal()
    loadRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        head = QHBoxLayout()
        title = QLabel("呼び名")
        title.setProperty("class", "sub")
        load = QPushButton("読込")
        load.setProperty("class", "btn")
        load.setToolTip("別ファイルの置換表を読み込みます。")
        load.clicked.connect(self.loadRequested.emit)
        add = QPushButton("＋ 語句")
        add.setProperty("class", "btn")
        add.setToolTip("マスキングする語句を手で追加します。")
        add.clicked.connect(lambda: self.addVariant.emit(""))
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(load)
        head.addWidget(add)
        root.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.host = QWidget()
        self.layout_groups = QVBoxLayout(self.host)
        self.layout_groups.addStretch(1)
        scroll.setWidget(self.host)
        root.addWidget(scroll, 1)
        foot = QHBoxLayout()
        renumber = QPushButton("番号を振り直す")
        renumber.setProperty("class", "btn")
        renumber.setToolTip("呼び名を振り直します。会社A、個人甲、住所Aの順です。")
        renumber.clicked.connect(self.renumberRequested.emit)
        save = QPushButton("置換表を保存…")
        save.setProperty("class", "btn")
        save.setToolTip("置換表をPDFとは別のCSVに保存します。")
        save.clicked.connect(self.saveRequested.emit)
        foot.addWidget(renumber)
        foot.addStretch(1)
        foot.addWidget(save)
        root.addLayout(foot)

    def set_groups(self, groups: list[dict]) -> None:
        while self.layout_groups.count() > 1:
            item = self.layout_groups.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        sections: dict[str, list[dict]] = {}
        for group in groups:
            sections.setdefault(group["section"], []).append(group)
        for section, items in sections.items():
            label = QLabel(section)
            label.setProperty("class", "sub")
            self.layout_groups.insertWidget(self.layout_groups.count() - 1, label)
            for group in items:
                self.layout_groups.insertWidget(self.layout_groups.count() - 1, self._group(group))

    def _group(self, group: dict) -> QWidget:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 4, 0, 8)
        top = QHBoxLayout()
        top.addWidget(QLabel(group["canonical"]))
        top.addStretch(1)
        arrow = QLabel("→")
        name = QLabel(group["pseudonym"] or "")
        name.setProperty("class", "pseudo")
        count = QLabel(f"{group['count']}件")
        count.setProperty("class", "sub")
        top.addWidget(arrow)
        top.addWidget(name)
        top.addWidget(count)
        layout.addLayout(top)
        chips = QHBoxLayout()
        chips.setSpacing(4)
        for variant in group["variants"]:
            chip = QFrame()
            chip.setProperty("class", "var" if variant["included"] else "sug")
            inner = QHBoxLayout(chip)
            inner.setContentsMargins(6, 2, 4, 2)
            inner.addWidget(QLabel(variant["text"]))
            if variant.get("note"):
                note = QLabel(variant["note"])
                note.setProperty("class", "sub")
                note.setToolTip("OCR修正で変わった表記です。候補一覧の「要確認」を確認してから確定します。")
                inner.addWidget(note)
            if variant["included"]:
                button = QPushButton("×")
                button.setFixedSize(22, 22)
                button.setToolTip("この表記をマスキング対象から外します。")
                button.clicked.connect(lambda _c=False, ids=variant["ids"]: self._emit_many(self.removeVariant, ids))
            else:
                button = QPushButton("＋")
                button.setFixedSize(22, 22)
                button.setToolTip(f"この表記も「{group['pseudonym']}」に置換します。")
                button.clicked.connect(lambda _c=False, ids=variant["ids"]: self._emit_many(self.includeVariant, ids))
            inner.addWidget(button)
            chips.addWidget(chip)
        add = QPushButton("＋ ゆれ")
        add.setProperty("class", "btn")
        add.setToolTip("別の表記を手入力で追加します。")
        add.clicked.connect(lambda _c=False, gid=group["id"]: self.addVariant.emit(gid))
        chips.addWidget(add)
        chips.addStretch(1)
        layout.addLayout(chips)
        return frame

    @staticmethod
    def _emit_many(signal, ids: list[str]) -> None:
        for hit_id in ids:
            signal.emit(hit_id)


class OcrPanel(QWidget):
    activated = Signal(str)
    rescanRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        chips = QHBoxLayout()
        self.mode = "review"
        self._buttons: list[QPushButton] = []
        for key, label in (("review", "要確認"), ("fixed", "修正済み"), ("all", "すべて")):
            button = QPushButton(label)
            button.setProperty("class", "chip")
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, name=key: self._set_mode(name))
            chips.addWidget(button)
            self._buttons.append(button)
        chips.addStretch(1)
        root.addLayout(chips)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.host = QWidget()
        self.rows = QVBoxLayout(self.host)
        self.rows.addStretch(1)
        scroll.setWidget(self.host)
        root.addWidget(scroll, 1)
        foot = QHBoxLayout()
        up = QPushButton("↑")
        up.setProperty("class", "btn")
        up.setToolTip("前の要確認行へ移動します。（Shift+F8）")
        down = QPushButton("↓")
        down.setProperty("class", "btn")
        down.setToolTip("次の要確認行へ移動します。（F8）")
        up.clicked.connect(lambda: self._step(-1))
        down.clicked.connect(lambda: self._step(1))
        rescan = QPushButton("探し直す")
        rescan.setProperty("class", "primary")
        rescan.setToolTip("直した文字で、マスキング候補を探し直します。")
        rescan.clicked.connect(self.rescanRequested.emit)
        foot.addWidget(up)
        foot.addWidget(down)
        foot.addStretch(1)
        foot.addWidget(rescan)
        root.addLayout(foot)
        self._visible: list[str] = []
        self._cursor = -1
        self._lines: list[dict] = []

    def set_lines(self, lines: list[dict], review_below: float) -> None:
        self._lines = lines
        self._review_below = review_below
        counts = {"review": 0, "fixed": 0, "all": len(lines)}
        for line in lines:
            if line["source"] == TextSource.CORRECTED:
                counts["fixed"] += 1
            elif line["confidence"] < review_below:
                counts["review"] += 1
        labels = {"review": "要確認", "fixed": "修正済み", "all": "すべて"}
        for button, key in zip(self._buttons, ("review", "fixed", "all"), strict=True):
            button.setText(f"{labels[key]} {counts[key]}")
            button.setChecked(self.mode == key)
        while self.rows.count() > 1:
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._visible = []
        for line in lines:
            if not self._match(line):
                continue
            self._visible.append(line["id"])
            label = QLabel(f"{line['page'] + 1}  {line['text']}")
            if line["source"] == TextSource.CORRECTED:
                label.setStyleSheet("color: #1e6b34; font-size: 14px; padding: 6px;")
            elif line["confidence"] < review_below:
                label.setStyleSheet("color: #8f1f14; font-size: 14px; padding: 6px;")
            else:
                label.setStyleSheet("font-size: 14px; padding: 6px;")
            label.setWordWrap(True)
            label.mousePressEvent = lambda _e, line_id=line["id"]: self.activated.emit(line_id)  # type: ignore[method-assign]
            self.rows.insertWidget(self.rows.count() - 1, label)

    def _match(self, line: dict) -> bool:
        if self.mode == "all":
            return True
        if self.mode == "fixed":
            return line["source"] == TextSource.CORRECTED
        return line["source"] != TextSource.CORRECTED and line["confidence"] < self._review_below

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self.set_lines(self._lines, self._review_below)

    def _step(self, delta: int) -> None:
        if not self._visible:
            return
        self._cursor = (self._cursor + delta) % len(self._visible)
        self.activated.emit(self._visible[self._cursor])
