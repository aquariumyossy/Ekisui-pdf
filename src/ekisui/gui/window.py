from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import replace
from pathlib import Path

import pymupdf
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, QThread, Signal
from PySide6.QtGui import QFont, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ekisui.domain.normalize import strict_text
from ekisui.domain.session import Session
from ekisui.domain.tableio import csv_to_rows, groups_to_csv
from ekisui.domain.types import (
    CATEGORY_LABEL,
    Action,
    Category,
    MatchKind,
    PageKind,
    SaveOptions,
    Settings,
    TextSource,
)
from ekisui.errors import EkisuiError
from ekisui.gui.pageview import PageCanvas, PageView
from ekisui.gui.zoom import anchored_scroll
from ekisui.gui.panels import CandidatePanel, OcrPanel, TablePanel
from ekisui.pdf.document import open_document, pages_need_ocr, recognize
from ekisui.pdf.export import export_pdf, redaction_boxes, unique_destination
from ekisui.pdf.ocr_engine import PpOcrV5
from ekisui.pdf.verify import VerifyReport, verify_pdf


def _mark(widget: QWidget, kind: str) -> QWidget:
    widget.setProperty("class", kind)
    return widget


class OcrWorker(QThread):
    progress = Signal(int, int, object)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, document, settings, work: Path, cancel: threading.Event) -> None:
        super().__init__()
        self.document = document
        self.settings = settings
        self.work = work
        self.cancel = cancel

    def run(self) -> None:
        try:
            engine = PpOcrV5()
            result = recognize(
                self.document,
                self.settings,
                engine,
                self.work,
                on_page=lambda done, total, label: self.progress.emit(done, total, label),
                cancelled=self.cancel.is_set,
            )
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001 — show the message, keep the window alive
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ekisui-pdf")
        self.resize(1280, 800)
        self.setAcceptDrops(True)
        self.session: Session | None = None
        self.settings = Settings()
        self.page_index = 0
        self.zoom = 1.0
        self.fit_mode = True
        self.preview = False
        self.align_boxes = True
        self.region_mode = False
        self.show_lines = False
        self.selected_hit = ""
        self.ocr_running = False
        self.ocr_ran = False
        self._after_ocr = ""
        self._save_mode = "ocr"
        self.worker: OcrWorker | None = None
        self.cancel_event: threading.Event | None = None
        self.work_dir = Path(tempfile.mkdtemp(prefix="ekisui-"))
        self.live_labels: dict[int, str | None] = {}
        self._pixmap_cache: dict[tuple, QPixmap] = {}
        self.store = QSettings("ekisui", "ekisui-pdf")
        self._build()
        self._shortcuts()
        self.refresh()

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._toolbar())
        self.body = QWidget()
        body = QHBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.thumb_scroll = QScrollArea()
        self.thumb_scroll.setObjectName("thumbs")
        self.thumb_scroll.setWidgetResizable(True)
        self.thumb_scroll.setFixedWidth(132)
        self.thumb_host = QWidget()
        self.thumb_layout = QVBoxLayout(self.thumb_host)
        self.thumb_layout.addStretch(1)
        self.thumb_scroll.setWidget(self.thumb_host)
        body.addWidget(self.thumb_scroll)
        viewer = QWidget()
        viewer_box = QVBoxLayout(viewer)
        viewer_box.setContentsMargins(0, 0, 0, 0)
        viewer_box.setSpacing(0)
        viewer_box.addWidget(self._viewer_bar())
        self.canvas = PageCanvas()
        self.canvas.regionChosen.connect(self._on_region)
        self.canvas.lineActivated.connect(self._edit_line)
        self.canvas.editConfirmed.connect(self._commit_line)
        self.canvas.hitAdjusted.connect(self._on_adjust)
        self.canvas.hitRestore.connect(self._on_restore)
        self.canvas.hitSelected.connect(self._select_hit)
        self.view = PageView(self.canvas)
        self.view.zoomRequested.connect(self._zoom_at)
        viewer_box.addWidget(self.view, 1)
        self.side = QWidget()
        self.side.setObjectName("side")
        self.side.setMinimumWidth(320)
        self.side.setMaximumWidth(680)
        side_box = QVBoxLayout(self.side)
        side_box.setContentsMargins(0, 0, 0, 0)
        side_box.setSpacing(0)
        tabs = QHBoxLayout()
        tabs.setContentsMargins(8, 0, 8, 0)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.panels = []
        self.candidates = CandidatePanel()
        self.table = TablePanel()
        self.ocr_panel = OcrPanel()
        for index, (label, panel) in enumerate(
            (("候補・選択一覧", self.candidates), ("置換表", self.table), ("OCR修正", self.ocr_panel))
        ):
            button = QPushButton(label)
            _mark(button, "tab")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _c=False, i=index: self._show_tab(i))
            self.tab_group.addButton(button)
            tabs.addWidget(button)
            self.panels.append(panel)
        tabs.addStretch(1)
        side_box.addLayout(tabs)
        for panel in self.panels:
            side_box.addWidget(panel)
        self._wire_panels()
        self.table.hide()
        self.ocr_panel.hide()
        foot = QWidget()
        foot_box = QHBoxLayout(foot)
        foot_box.setContentsMargins(10, 4, 10, 8)
        self.btn_confirm = QPushButton("確定…")
        _mark(self.btn_confirm, "primary")
        self.btn_confirm.setToolTip("選んだ箇所のマスキングを確定します。画像と文字を消す処理です。")
        self.btn_confirm.clicked.connect(self._open_confirm)
        foot_box.addStretch(1)
        foot_box.addWidget(self.btn_confirm)
        side_box.addWidget(foot)
        viewer.setMinimumWidth(360)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setObjectName("split")
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(8)
        self.split.addWidget(viewer)
        self.split.addWidget(self.side)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        side_width = int(self.store.value("side_width", 384) or 384)
        side_width = max(320, min(680, side_width))
        self.split.setSizes([900, side_width])
        self.split.splitterMoved.connect(self._on_split)
        handle = self.split.handle(1)
        handle.setToolTip("左右にドラッグして、ページと一覧の幅を変えられます。")
        handle.setCursor(Qt.CursorShape.SplitHCursor)
        body.addWidget(self.split, 1)
        self.empty = self._empty_state()
        root.addWidget(self.empty, 1)
        root.addWidget(self.body, 1)
        self.body.hide()
        self._build_overlays(central)
        status = QStatusBar()
        self.setStatusBar(status)
        self.file_label = QLabel("")
        self.kind_label = QLabel("")
        self.ocr_label = QLabel("")
        status.addWidget(self.file_label)
        status.addWidget(self.kind_label)
        status.addPermanentWidget(self.ocr_label)

    def _toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("toolbar")
        bar.setFixedHeight(64)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        self.btn_open = self._tool("開く", "PDFを開きます。（Ctrl+O）", self._pick_pdf, primary=True)
        self.btn_ocr = self._tool(
            "OCR実行",
            "スキャン画像の文字を読み取り、検索できるPDFにします。マスキングはしません。",
            self.start_ocr,
        )
        self.btn_ocr_menu = QPushButton("▾")
        _mark(self.btn_ocr_menu, "dd")
        self.btn_ocr_menu.setToolTip("読み取り前の傾き補正を切り替えます。")
        self.btn_ocr_menu.setCheckable(True)
        self.btn_ocr_menu.clicked.connect(self._toggle_ocr_pop)
        self.btn_mask = self._tool(
            "マスキング実行",
            "個人情報などのマスキング候補を自動で探し、右の一覧に出します。",
            self.start_mask,
        )
        self.btn_region = self._tool(
            "範囲で選ぶ",
            "ページ上をドラッグして、マスキングする範囲を選べます。",
            self._toggle_region,
        )
        self.btn_region.setCheckable(True)
        self.btn_save = self._tool("保存", "別名で保存します。（Ctrl+Shift+S）", self._open_save)
        self.btn_save.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        layout.addWidget(self.btn_open)
        layout.addWidget(self.btn_ocr)
        layout.addWidget(self.btn_ocr_menu)
        layout.addWidget(self.btn_mask)
        layout.addWidget(self.btn_region)
        layout.addWidget(self.btn_save)
        layout.addStretch(1)
        offline = QLabel("オフライン")
        offline.setObjectName("offline")
        offline.setToolTip("外部とは通信しません。読み取りもマスキングもこのPCの中で行います。")
        layout.addWidget(offline)
        settings = self._tool("設定", "一致の厳しさや、マスキング枠の幅を変えます。", self._open_settings)
        layout.addWidget(settings)
        self.ocr_pop = QFrame(self.centralWidget())
        self.ocr_pop.setObjectName("pop")
        self.ocr_pop.setFixedSize(320, 78)
        pop_layout = QHBoxLayout(self.ocr_pop)
        label = QLabel("自動傾き補正")
        label.setToolTip("読み取りの前に、ページの向きと小さな傾きを直します。保存するPDFも直した画像になります。")
        self.deskew_box = QCheckBox()
        self.deskew_box.setChecked(True)
        self.deskew_box.setToolTip(label.toolTip())
        self.deskew_box.toggled.connect(self._set_deskew)
        pop_layout.addWidget(label)
        pop_layout.addStretch(1)
        pop_layout.addWidget(self.deskew_box)
        self.ocr_pop.hide()
        return bar

    def _tool(self, text: str, tip: str, slot, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        _mark(button, "tbPrimary" if primary else "tb")
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    def _viewer_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("vbar")
        bar.setFixedHeight(40)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 8, 0)
        prev_b = QPushButton("＜")
        _mark(prev_b, "ib")
        prev_b.setToolTip("前のページを表示します。（PageUp）")
        prev_b.clicked.connect(lambda: self._move_page(-1))
        next_b = QPushButton("＞")
        _mark(next_b, "ib")
        next_b.setToolTip("次のページを表示します。（PageDown）")
        next_b.clicked.connect(lambda: self._move_page(1))
        self.page_label = QLabel("1 / 1")
        out = QPushButton("−")
        _mark(out, "ib")
        out.setToolTip("ページを縮小します。（Ctrl+−）")
        out.clicked.connect(lambda: self._set_zoom(self.zoom / 1.15))
        self.zoom_label = QLabel("100%")
        inn = QPushButton("＋")
        _mark(inn, "ib")
        inn.setToolTip("ページを拡大します。（Ctrl+＋）")
        inn.clicked.connect(lambda: self._set_zoom(self.zoom * 1.15))
        fit = QPushButton("幅")
        _mark(fit, "ib")
        fit.setToolTip("ページの幅を、表示領域に合わせます。")
        fit.clicked.connect(self._fit_width)
        self.line_toggle = QPushButton("文字枠")
        _mark(self.line_toggle, "ib")
        self.line_toggle.setCheckable(True)
        self.line_toggle.setToolTip("読み取った文字の枠を表示します。赤い枠は要確認です。")
        self.line_toggle.toggled.connect(self._toggle_lines)
        layout.addWidget(prev_b)
        layout.addWidget(self.page_label)
        layout.addWidget(next_b)
        layout.addSpacing(12)
        layout.addWidget(out)
        layout.addWidget(self.zoom_label)
        layout.addWidget(inn)
        layout.addWidget(fit)
        layout.addStretch(1)
        layout.addWidget(self.line_toggle)
        return bar

    def _empty_state(self) -> QWidget:
        host = QWidget()
        host.setObjectName("empty")
        layout = QVBoxLayout(host)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop = QFrame()
        drop.setObjectName("drop")
        drop.setFixedSize(440, 220)
        inner = QVBoxLayout(drop)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption = QLabel("PDFをここにドロップ")
        caption.setStyleSheet("font-size: 16px; color: #5c5c5c;")
        button = QPushButton("PDFを開く")
        _mark(button, "primary")
        button.setToolTip("PDFを開きます。（Ctrl+O）")
        button.clicked.connect(self._pick_pdf)
        inner.addWidget(caption, alignment=Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(drop, alignment=Qt.AlignmentFlag.AlignCenter)
        self.recent_box = QVBoxLayout()
        layout.addLayout(self.recent_box)
        return host

    def _build_overlays(self, parent: QWidget) -> None:
        self.shade = QWidget(parent)
        self.shade.setObjectName("shade")
        self.shade.hide()
        shade_layout = QVBoxLayout(self.shade)
        shade_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dialog = QFrame()
        self.dialog.setObjectName("dialog")
        self.dialog.setFixedWidth(540)
        self.dialog.setMaximumHeight(640)
        self.dialog_layout = QVBoxLayout(self.dialog)
        self.dialog_layout.setContentsMargins(18, 16, 18, 16)
        shade_layout.addWidget(self.dialog)
        self.card = QFrame(parent)
        self.card.setObjectName("card")
        self.card.setFixedSize(360, 140)
        card_box = QVBoxLayout(self.card)
        self.card_title = QLabel("文字を読み取っています")
        self.card_title.setStyleSheet("font-size: 16px;")
        self.card_body = QLabel("")
        self.card_body.setWordWrap(True)
        stop = QPushButton("中止")
        _mark(stop, "btn")
        stop.setToolTip("読み取りを中止します。ここまで読んだページは残ります。")
        stop.clicked.connect(self._cancel_ocr)
        card_box.addWidget(self.card_title)
        card_box.addWidget(self.card_body)
        card_box.addWidget(stop, alignment=Qt.AlignmentFlag.AlignRight)
        self.card.hide()

    def _shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+O"), self, self._pick_pdf)
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_find)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self._open_save)
        QShortcut(QKeySequence("PgDown"), self, lambda: self._move_page(1))
        QShortcut(QKeySequence("PgUp"), self, lambda: self._move_page(-1))
        QShortcut(QKeySequence("F8"), self, lambda: self.ocr_panel._step(1))
        QShortcut(QKeySequence("Shift+F8"), self, lambda: self.ocr_panel._step(-1))

    def _wire_panels(self) -> None:
        self.candidates.searchRequested.connect(self._search)
        self.candidates.toggled.connect(self._toggle_hit)
        self.candidates.actionChanged.connect(self._set_action)
        self.candidates.pseudonymEdited.connect(self._set_name)
        self.candidates.activated.connect(self._activate_hit)
        self.candidates.excludeRequested.connect(self._exclude)
        self.candidates.selectAll.connect(lambda _v: self._fill_candidates())
        self.table.includeVariant.connect(lambda hit_id: self._toggle_hit(hit_id, True))
        self.table.removeVariant.connect(lambda hit_id: self._toggle_hit(hit_id, False))
        self.table.addVariant.connect(self._add_variant)
        self.table.renumberRequested.connect(self._renumber)
        self.table.saveRequested.connect(self._save_table)
        self.table.loadRequested.connect(self._load_table)
        self.ocr_panel.activated.connect(self._edit_line)
        self.ocr_panel.rescanRequested.connect(self._rescan)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.shade.setGeometry(self.centralWidget().rect())
        self.card.move(max(160, (self.width() - 360) // 2), 160)
        self._place_ocr_pop()
        if self.fit_mode and self.session:
            self._fit_width()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pdf"):
                self.open_path(path)
                return

    def open_path(self, path: str) -> None:
        if self.ocr_running:
            QMessageBox.warning(self, "ekisui-pdf", "文字の読み取りが終わるまで、別のPDFは開けません。")
            return
        try:
            document = open_document(path)
        except EkisuiError as exc:
            QMessageBox.warning(self, "ekisui-pdf", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "ekisui-pdf", f"PDFを開けませんでした。\n{exc}")
            return
        self.session = Session(document, self.settings)
        self.page_index = 0
        self.preview = False
        self.ocr_ran = False
        self._after_ocr = ""
        self.selected_hit = ""
        self.live_labels = {}
        self._pixmap_cache.clear()
        recent = list(self.store.value("recent", []) or [])
        resolved = str(Path(path).resolve())
        recent = [resolved] + [item for item in recent if item != resolved]
        self.store.setValue("recent", recent[:8])
        self.setWindowTitle(f"ekisui-pdf — {Path(path).name}")
        self.refresh()

    def refresh(self) -> None:
        ready = self.session is not None and not self.ocr_running
        self.empty.setVisible(self.session is None)
        self.body.setVisible(self.session is not None)
        for button in (self.btn_ocr, self.btn_ocr_menu, self.btn_region, self.btn_mask):
            button.setEnabled(ready)
        self.btn_save.setEnabled(ready and self._can_save())
        self.btn_save.setToolTip(self._save_tip())
        self.btn_confirm.setEnabled(ready)
        self.btn_open.setEnabled(not self.ocr_running)
        self.side.setVisible(self.session is not None and not self.ocr_running)
        self._fill_recent()
        if self.session is None:
            self.file_label.setText("")
            self.kind_label.setText("")
            self.ocr_label.setText("")
            return
        self._fill_thumbs()
        self._show_page()
        self._fill_candidates()
        self._fill_table()
        self._fill_ocr()
        self._fill_status()

    def _fill_recent(self) -> None:
        while self.recent_box.count():
            item = self.recent_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        recent = [path for path in list(self.store.value("recent", []) or []) if Path(path).exists()]
        if not recent or self.session is not None:
            return
        title = QLabel("最近使ったファイル")
        title.setProperty("class", "sub")
        self.recent_box.addWidget(title)
        for path in recent[:5]:
            button = QPushButton(Path(path).name)
            button.setStyleSheet("text-align: left; font-size: 14px; background: transparent; border: none; padding: 6px;")
            button.clicked.connect(lambda _c=False, chosen=path: self.open_path(chosen))
            self.recent_box.addWidget(button)

    def _fill_status(self) -> None:
        assert self.session
        path = Path(self.session.document.source_path)
        pages = self.session.document.pages
        self.file_label.setText(path.name)
        kinds = {page.kind for page in pages}
        if kinds == {PageKind.NATIVE}:
            kind = "テキストPDF"
        elif kinds == {PageKind.SCANNED}:
            kind = "スキャンPDF"
        else:
            kind = "混在PDF"
        self.kind_label.setText(f"{kind}・{len(pages)}ページ")
        pending = any(page.kind == PageKind.SCANNED and not page.image_path for page in pages)
        read = any(page.kind == PageKind.SCANNED and page.image_path for page in pages)
        if self.ocr_running:
            self.ocr_label.setText("OCR中")
        elif pending:
            self.ocr_label.setText("未読取")
        elif read:
            self.ocr_label.setText("OCR済み")
        elif any(page.lines for page in pages):
            self.ocr_label.setText("テキスト層あり")
        else:
            self.ocr_label.setText("")

    def _fill_thumbs(self) -> None:
        assert self.session
        while self.thumb_layout.count() > 1:
            item = self.thumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        counts: dict[int, int] = {}
        for group in self.session.groups:
            for tracked in group.hits:
                if tracked.included:
                    counts[tracked.hit.page_index] = counts.get(tracked.hit.page_index, 0) + 1
        for page in self.session.document.pages:
            thumb = QWidget()
            column = QVBoxLayout(thumb)
            column.setContentsMargins(8, 0, 8, 8)
            column.setSpacing(2)
            button = QPushButton()
            button.setObjectName("thumbBtn")
            button.setCheckable(True)
            button.setChecked(page.index == self.page_index)
            pixmap = self._thumb(page.index).scaled(
                84, 112, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            button.setIcon(pixmap)
            button.setIconSize(pixmap.size())
            button.setFixedSize(92, 120)
            if page.index == self.page_index:
                button.setStyleSheet("border: 2px solid #0f6cbd; padding: 0;")
            else:
                button.setStyleSheet("border: 1px solid #cfcfcf; padding: 0;")
            button.clicked.connect(lambda _c=False, index=page.index: self._goto(index))
            column.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
            caption = str(page.index + 1)
            if counts.get(page.index):
                caption += f"  {counts[page.index]}"
            number = QLabel(caption)
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number.setStyleSheet("font-size: 13px; color: #5c5c5c;")
            column.addWidget(number)
            correction = page.correction_label or self.live_labels.get(page.index)
            if correction:
                skew = QLabel(correction)
                skew.setAlignment(Qt.AlignmentFlag.AlignCenter)
                skew.setProperty("class", "skew")
                skew.setStyleSheet("color: #0f6cbd; font-size: 13px;")
                column.addWidget(skew)
            self.thumb_layout.insertWidget(self.thumb_layout.count() - 1, thumb)

    def _show_page(self) -> None:
        assert self.session
        page = self.session.document.pages[self.page_index]
        self.page_label.setText(f"{self.page_index + 1} / {len(self.session.document.pages)}")
        self.zoom_label.setText(f"{round(self.zoom * 100)}%")
        pixmap = self._page_pixmap(self.page_index)
        self.canvas.review_below = self.session.settings.review_below
        self.canvas.set_page(pixmap, page.width, page.height)
        self.canvas.set_zoom(self.zoom)
        self.canvas.region_mode = self.region_mode
        self.canvas.show_lines = self.show_lines
        self.canvas.show_boxes = self.preview
        self.canvas.show_hits = not self.preview
        self.canvas.selected_hit = self.selected_hit
        self.canvas.hits = []
        self.canvas.lines = list(page.lines)
        for group in self.session.groups:
            for tracked in group.included_hits():
                if tracked.hit.page_index != page.index:
                    continue
                self.canvas.hits.append(
                    {
                        "id": tracked.id,
                        "bbox": tracked.hit.bbox,
                        "kind": tracked.hit.kind,
                        "adjusted": tracked.adjusted,
                        "line_ids": tracked.hit.line_ids,
                    }
                )
        boxes = redaction_boxes(
            self.session.document,
            self.session.groups,
            SaveOptions(align_box_width=self.align_boxes),
            self.session.settings,
        )
        self.canvas.boxes = [
            {
                "rect": box.rect,
                "action": box.action,
                "text": box.pseudonym or "",
            }
            for box in boxes
            if box.page_index == page.index
        ]
        self.canvas.update()

    def _page_pixmap(self, index: int) -> QPixmap:
        assert self.session
        page = self.session.document.pages[index]
        key = ("page", index, page.image_path, page.width, page.height)
        if key in self._pixmap_cache:
            return self._pixmap_cache[key]
        if page.image_path and Path(page.image_path).exists():
            pixmap = QPixmap(page.image_path)
        else:
            pixmap = _render_pdf(self.session.document.source_path, page.source_index, 110)
        self._pixmap_cache[key] = pixmap
        return pixmap

    def _thumb(self, index: int) -> QPixmap:
        assert self.session
        page = self.session.document.pages[index]
        key = ("thumb", index, page.image_path)
        if key in self._pixmap_cache:
            return self._pixmap_cache[key]
        if page.image_path and Path(page.image_path).exists():
            pixmap = QPixmap(page.image_path).scaledToWidth(84, Qt.TransformationMode.SmoothTransformation)
        else:
            pixmap = _render_pdf(self.session.document.source_path, page.source_index, 24)
        self._pixmap_cache[key] = pixmap
        return pixmap

    def _fill_candidates(self) -> None:
        if not self.session:
            return
        counts: dict[Category, int] = {}
        rows = []
        for group in self.session.groups:
            counts[group.category] = counts.get(group.category, 0) + len(group.hits)
            for tracked in group.hits:
                kind = tracked.hit.kind
                label = "完全一致" if kind == MatchKind.EXACT else f"ゆるい一致（{round(tracked.hit.score * 100)}%）"
                if tracked.hit.explanation:
                    tip = f"ゆるい一致です。{tracked.hit.explanation}。"
                elif kind == MatchKind.EXACT:
                    tip = "この箇所をマスキングまたは置換の対象にします。"
                else:
                    tip = "ゆるい一致です。読み取りのゆれを確認してください。"
                rows.append(
                    {
                        "hit_id": tracked.id,
                        "group_id": group.id,
                        "surface": tracked.hit.surface,
                        "included": tracked.included,
                        "adjusted": tracked.adjusted,
                        "kind": kind,
                        "label": label,
                        "tip": tip,
                        "action": group.action,
                        "pseudonym": group.pseudonym,
                        "page": tracked.hit.page_index,
                        "category": group.category,
                    }
                )
        self.candidates.set_hits(rows, counts)

    def _fill_table(self) -> None:
        if not self.session:
            return
        groups = []
        for group in self.session.groups:
            if group.action != Action.REPLACE:
                continue
            variants: dict[str, dict] = {}
            for tracked in group.hits:
                key = strict_text(tracked.hit.surface)
                slot = variants.setdefault(
                    key,
                    {"text": tracked.hit.surface, "included": False, "ids": []},
                )
                slot["ids"].append(tracked.id)
                slot["included"] = slot["included"] or tracked.included
            if group.category == Category.COMPANY:
                section = "会社"
            elif group.category == Category.PERSON:
                section = "個人"
            elif group.category == Category.ADDRESS:
                section = "住所"
            else:
                section = CATEGORY_LABEL[group.category]
            groups.append(
                {
                    "id": group.id,
                    "section": section,
                    "canonical": group.canonical,
                    "pseudonym": group.pseudonym or "",
                    "count": len(group.included_hits()),
                    "variants": list(variants.values()),
                }
            )
        self.table.set_groups(groups)

    def _fill_ocr(self) -> None:
        if not self.session:
            return
        lines = []
        for page in self.session.document.pages:
            for line in page.lines:
                lines.append(
                    {
                        "id": line.id,
                        "page": page.index,
                        "text": line.text,
                        "confidence": line.confidence,
                        "source": line.source,
                    }
                )
        self.ocr_panel.set_lines(lines, self.session.settings.review_below)

    def _show_tab(self, index: int) -> None:
        for number, panel in enumerate(self.panels):
            panel.setVisible(number == index)
        if index == 2:
            self.show_lines = True
            self.line_toggle.setChecked(True)
        self._show_page()

    def _pick_pdf(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "PDFを開く", "", "PDF (*.pdf)")
        if path:
            self.open_path(path)

    def _focus_find(self) -> None:
        self._show_tab(0)
        self.tab_group.buttons()[0].setChecked(True)
        self.candidates.query.setFocus()

    def _toggle_region(self) -> None:
        self.region_mode = self.btn_region.isChecked()
        if self.session:
            self.canvas.region_mode = self.region_mode

    def _toggle_lines(self, checked: bool) -> None:
        self.show_lines = checked
        if self.session:
            self._show_page()

    def _set_deskew(self, checked: bool) -> None:
        self.settings = replace(self.settings, deskew=checked)
        if self.session:
            self.session.set_settings(replace(self.session.settings, deskew=checked))

    def _place_ocr_pop(self) -> None:
        if not hasattr(self, "btn_ocr_menu"):
            return
        origin = self.btn_ocr_menu.mapTo(self.centralWidget(), self.btn_ocr_menu.rect().bottomLeft())
        self.ocr_pop.move(max(8, origin.x() - 80), origin.y() + 4)

    def _toggle_ocr_pop(self) -> None:
        self._place_ocr_pop()
        self.ocr_pop.setVisible(self.btn_ocr_menu.isChecked())
        self.ocr_pop.raise_()

    def start_mask(self) -> None:
        """Extract candidates. Scanned pages are read first. A second press re-scans."""
        if not self.session or self.ocr_running:
            return
        if pages_need_ocr(self.session.document):
            self._after_ocr = "mask"
            self.start_ocr()
            return
        self._apply_mask()

    def _apply_mask(self) -> None:
        if not self.session:
            return
        self.session.rescan()
        self.preview = False
        self._show_tab(0)
        if self.tab_group.buttons():
            self.tab_group.buttons()[0].setChecked(True)
        self.refresh()

    def _can_save(self) -> bool:
        if self.session is None or self.ocr_running:
            return False
        if self.session.confirmed or self.ocr_ran:
            return True
        return bool(self.session.groups)

    def _save_tip(self) -> str:
        if self.session is None or not self._can_save():
            return "読み取りもマスキングの確定もまだないので、保存できません。"
        if self.session.confirmed:
            return "マスキングしたPDFを別名で保存します。消し残りも確認します。"
        if self.session.groups:
            return "候補が未確定です。読み取ったPDFだけ保存するか、確定に進むかを選べます。"
        return "読み取った文字だけのPDFを別名で保存します。マスキングはしません。"

    def _on_split(self, _pos: int, _index: int) -> None:
        sizes = self.split.sizes()
        if len(sizes) == 2 and sizes[1] >= 320:
            self.store.setValue("side_width", sizes[1])
        if self.fit_mode and self.session and not self.ocr_running:
            self._fit_width()
        self.canvas.reposition_edit()

    def _on_adjust(self, hit_id: str, edge: str, page_x: float) -> None:
        if not self.session:
            return
        self.session.adjust_hit(hit_id, edge, page_x)
        self._sync_hit(hit_id)
        self._fill_candidates()
        self._fill_table()

    def _on_restore(self, hit_id: str) -> None:
        if not self.session:
            return
        self.session.restore_hit(hit_id)
        self._sync_hit(hit_id)
        self._fill_candidates()
        self._fill_table()

    def _sync_hit(self, hit_id: str) -> None:
        if not self.session:
            return
        for group in self.session.groups:
            for tracked in group.hits:
                if tracked.id != hit_id:
                    continue
                for hit in self.canvas.hits:
                    if hit["id"] == hit_id:
                        hit["bbox"] = tracked.hit.bbox
                        hit["adjusted"] = tracked.adjusted
                self.selected_hit = hit_id
                self.canvas.selected_hit = hit_id
                self.canvas.update()
                return

    def _select_hit(self, hit_id: str) -> None:
        self.selected_hit = hit_id
        self.canvas.selected_hit = hit_id
        self.canvas.update()

    def _search(self, text: str) -> None:
        if not self.session:
            return
        group = self.session.add_phrase(text)
        self.preview = False
        if group is None:
            self.statusBar().showMessage("見つかりませんでした", 4000)
        self.refresh()

    def _on_region(self, rect) -> None:
        if not self.session:
            return
        group = self.session.add_region(self.page_index, rect)
        self.preview = False
        if group is None:
            self.statusBar().showMessage("この範囲から語句を読み取れませんでした", 4000)
        self.refresh()

    def _toggle_hit(self, hit_id: str, included: bool) -> None:
        if not self.session:
            return
        self.session.set_included(hit_id, included)
        self.preview = False
        self.refresh()

    def _set_action(self, group_id: str, action: Action) -> None:
        if not self.session:
            return
        self.session.set_action(group_id, action)
        self.preview = False
        self.refresh()

    def _set_name(self, group_id: str, name: str) -> None:
        if not self.session:
            return
        self.session.set_pseudonym(group_id, name)
        self.refresh()

    def _activate_hit(self, hit_id: str) -> None:
        if not self.session:
            return
        self.selected_hit = hit_id
        for group in self.session.groups:
            for tracked in group.hits:
                if tracked.id == hit_id:
                    self._goto(tracked.hit.page_index)
                    return

    def _exclude(self) -> None:
        if not self.session:
            return
        self.session.exclude_unchecked()
        self.refresh()

    def _add_variant(self, group_id: str) -> None:
        if not self.session:
            return
        text, ok = QInputDialog.getText(self, "表記ゆれ", "語句")
        if not ok or len(strict_text(text)) < 2:
            return
        if group_id:
            self.session.add_variant(group_id, text)
        else:
            self.session.add_phrase(text)
        self.refresh()

    def _renumber(self) -> None:
        if not self.session:
            return
        self.session.renumber()
        self.refresh()

    def _save_table(self) -> None:
        if not self.session:
            return
        path, _filter = QFileDialog.getSaveFileName(self, "置換表を保存", "置換表.csv", "CSV (*.csv)")
        if not path:
            return
        Path(path).write_text(groups_to_csv(self.session.groups), encoding="utf-8-sig")

    def _load_table(self) -> None:
        if not self.session:
            return
        path, _filter = QFileDialog.getOpenFileName(self, "置換表を読み込む", "", "CSV (*.csv)")
        if not path:
            return
        self.session.import_rows(csv_to_rows(Path(path).read_text(encoding="utf-8-sig")))
        self.refresh()

    def _edit_line(self, line_id: str) -> None:
        if not self.session:
            return
        for page in self.session.document.pages:
            for line in page.lines:
                if line.id == line_id:
                    self.show_lines = True
                    self.line_toggle.setChecked(True)
                    self._goto(page.index)
                    self.canvas.begin_edit(line)
                    return

    def _commit_line(self, line_id: str, text: str) -> None:
        if not self.session:
            return
        self.session.correct_line(line_id, text)
        self.preview = False
        self.refresh()

    def _rescan(self) -> None:
        if not self.session:
            return
        self.session.rescan()
        self.preview = False
        self.refresh()

    def _goto(self, index: int) -> None:
        if not self.session:
            return
        self.page_index = max(0, min(index, len(self.session.document.pages) - 1))
        self.refresh()

    def _move_page(self, delta: int) -> None:
        self._goto(self.page_index + delta)

    def _set_zoom(self, zoom: float) -> None:
        self.fit_mode = False
        self.zoom = max(0.3, min(zoom, 3.0))
        self._apply_zoom(rerender=True)

    def _fit_width(self) -> None:
        if not self.session:
            return
        page = self.session.document.pages[self.page_index]
        width = max(200, self.view.viewport().width() - 48)
        self.zoom = max(0.3, min(width / max(page.width, 1), 3.0))
        self.fit_mode = True
        self._apply_zoom(rerender=False)

    def _apply_zoom(self, rerender: bool) -> None:
        self.zoom_label.setText(f"{round(self.zoom * 100)}%")
        if not self.session:
            return
        self.canvas.set_zoom(self.zoom)
        if rerender:
            self._rerender_current()

    def _zoom_at(self, factor: float, pos: QPointF, rerender: bool) -> None:
        if not self.session or factor <= 0:
            return
        old = self.zoom
        horizontal = self.view.horizontalScrollBar()
        vertical = self.view.verticalScrollBar()
        new, scroll_x, scroll_y = anchored_scroll(
            old,
            old * factor,
            pos.x(),
            pos.y(),
            float(self.canvas._origin.x()),
            float(self.canvas._origin.y()),
            float(horizontal.value()),
            float(vertical.value()),
        )
        if abs(new - old) < 1e-4:
            if rerender:
                self._rerender_current()
            return
        self.fit_mode = False
        self.zoom = new
        self.zoom_label.setText(f"{round(new * 100)}%")
        self.canvas.set_zoom(new)
        horizontal.setValue(int(round(scroll_x)))
        vertical.setValue(int(round(scroll_y)))
        if rerender:
            self._rerender_current()

    def _rerender_current(self) -> None:
        if not self.session:
            return
        index = self.page_index
        self._pixmap_cache = {key: value for key, value in self._pixmap_cache.items() if not (key and key[1] == index)}
        page = self.session.document.pages[index]
        dpi = max(72, min(216, int(round(72 * self.zoom))))
        if page.image_path and Path(page.image_path).exists():
            pixmap = QPixmap(page.image_path)
        else:
            pixmap = _render_pdf(self.session.document.source_path, page.source_index, dpi)
        self.canvas.pixmap = pixmap
        self.canvas.update()

    def start_ocr(self) -> None:
        if not self.session or self.worker is not None:
            return
        self.cancel_event = threading.Event()
        self.worker = OcrWorker(self.session.document, self.session.settings, self.work_dir, self.cancel_event)
        self.worker.progress.connect(self.apply_progress)
        self.worker.finished_ok.connect(self._ocr_done)
        self.worker.failed.connect(self._ocr_failed)
        self.ocr_running = True
        self.card_title.setText("文字を読み取っています")
        self.card_body.setText(f"0 / {len(self.session.document.pages)}")
        self.card.show()
        self.card.raise_()
        self.refresh()
        self.worker.start()

    def apply_progress(self, done: int, total: int, label) -> None:
        self.card_body.setText(f"{done} / {total}" + (f"　{label}" if label else ""))
        if done > 0:
            self.live_labels[done - 1] = label
        self.ocr_label.setText(f"OCR {done} / {total}")
        if self.session:
            self._fill_thumbs()

    def _cancel_ocr(self) -> None:
        if self.cancel_event:
            self.cancel_event.set()
        self.card_body.setText("中止しています")

    def _ocr_done(self, document) -> None:
        mask = self._after_ocr == "mask"
        self._after_ocr = ""
        if self.session:
            previous = self.session.document
            self.session.document = document
            # Manual ranges move with the scan. Candidates are not created here.
            self.session.rebind_after_ocr(previous)
            self._pixmap_cache.clear()
            self.ocr_ran = True
        self._ocr_idle()
        if mask and self.session:
            self.session.rescan()
            self.preview = False
            self._show_tab(0)
            if self.tab_group.buttons():
                self.tab_group.buttons()[0].setChecked(True)
        self.refresh()

    def _ocr_failed(self, message: str) -> None:
        self._after_ocr = ""
        self._ocr_idle()
        QMessageBox.warning(self, "ekisui-pdf", message)
        self.refresh()

    def _ocr_idle(self) -> None:
        self.ocr_running = False
        self.worker = None
        self.card.hide()

    def _open_confirm(self) -> None:
        if not self.session:
            return
        black = replace_n = 0
        names = set()
        pages = set()
        for group in self.session.groups:
            hits = group.included_hits()
            if group.action == Action.BLACKOUT:
                black += len(hits)
            else:
                replace_n += len(hits)
                if group.pseudonym:
                    names.add(group.pseudonym)
            for tracked in hits:
                pages.add(tracked.hit.page_index + 1)
        self._clear_dialog()
        title = QLabel("確定しますか")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        summary = QLabel(
            f"黒塗り {black}か所　　置換 {replace_n}か所（呼び名 {len(names)}種）　　対象ページ {self._pages(pages)}"
        )
        summary.setWordWrap(True)
        warn = QLabel("画像と透明テキストを削除します。元に戻せません。")
        warn.setProperty("class", "warn")
        buttons = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        _mark(cancel, "btn")
        cancel.clicked.connect(self.shade.hide)
        go = QPushButton("確定する")
        _mark(go, "danger")
        go.setToolTip("選んだ箇所の確定に進みます。元のPDFは変更しません。")
        go.clicked.connect(self._confirm)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(go)
        self.dialog_layout.addWidget(title)
        self.dialog_layout.addWidget(summary)
        self.dialog_layout.addWidget(warn)
        self.dialog_layout.addLayout(buttons)
        self._show_shade()

    def _confirm(self) -> None:
        if self.session:
            self.session.confirmed = True
        self.preview = True
        self.shade.hide()
        self.refresh()

    def closeEvent(self, event) -> None:  # noqa: N802
        import shutil

        shutil.rmtree(self.work_dir, ignore_errors=True)
        super().closeEvent(event)

    def _open_save(self) -> None:
        if not self.session or self.ocr_running or not self._can_save():
            return
        if self.session.groups and not self.session.confirmed:
            self._ask_unconfirmed_save()
            return
        self._open_save_dialog("masked" if self.session.confirmed else "ocr")

    def _ask_unconfirmed_save(self) -> None:
        self._clear_dialog()
        title = QLabel("候補が確定されていません")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        body = QLabel("マスキング候補がまだ確定されていません。読み取ったPDFだけ保存するか、確定に進むかを選べます。")
        body.setWordWrap(True)
        ocr_only = QPushButton("OCRだけ保存する")
        _mark(ocr_only, "btn")
        ocr_only.setEnabled(self.ocr_ran)
        ocr_only.setToolTip(
            "マスキングせず、読み取ったPDFだけを別名で保存します。"
            if self.ocr_ran
            else "文字の読み取りがまだなので、読み取ったPDFは保存できません。"
        )
        ocr_only.clicked.connect(lambda: self._open_save_dialog("ocr"))
        go = QPushButton("確定に進む")
        _mark(go, "primary")
        go.setToolTip("マスキングの確定画面を開きます。")
        go.clicked.connect(self._open_confirm)
        cancel = QPushButton("キャンセル")
        _mark(cancel, "btn")
        cancel.setToolTip("保存せずに戻ります。")
        cancel.clicked.connect(self.shade.hide)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(ocr_only)
        buttons.addWidget(go)
        self.dialog_layout.addWidget(title)
        self.dialog_layout.addWidget(body)
        self.dialog_layout.addLayout(buttons)
        self._show_shade()

    def _open_save_dialog(self, mode: str) -> None:
        if not self.session:
            return
        self._save_mode = mode
        source = Path(self.session.document.source_path)
        suffix = "_Masked" if mode == "masked" else "_OCR"
        extras = ("_墨消し記録.csv", "_置換表.csv") if mode == "masked" else ()
        default = unique_destination(source.with_name(source.stem + suffix + ".pdf"), extras)
        self._clear_dialog()
        title = QLabel("マスキングしたPDFを保存" if mode == "masked" else "読み取ったPDFを保存")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.save_path = QLineEdit(str(default))
        browse = QPushButton("参照…")
        _mark(browse, "btn")
        browse.setToolTip("保存先のファイル名を選びます。")
        browse.clicked.connect(self._browse_save)
        path_row = QHBoxLayout()
        path_row.addWidget(self.save_path, 1)
        path_row.addWidget(browse)
        self.opt_meta = self._option("メタデータを消す", True, "作成者や更新日時などの情報を、保存するPDFから消します。")
        buttons = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        _mark(cancel, "btn")
        cancel.setToolTip("保存せずに戻ります。")
        cancel.clicked.connect(self.shade.hide)
        go = QPushButton("保存")
        _mark(go, "primary")
        go.setToolTip(
            "この名前で保存し、消し残りがないか確認します。"
            if mode == "masked"
            else "この名前で、読み取ったPDFを保存します。マスキングはしません。"
        )
        go.clicked.connect(self._save)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(go)
        self.dialog_layout.addWidget(title)
        self.dialog_layout.addWidget(QLabel("ファイル名"))
        self.dialog_layout.addLayout(path_row)
        self.dialog_layout.addWidget(self.opt_meta)
        if mode == "masked":
            self.opt_align = self._option(
                "枠の幅をそろえる",
                True,
                "短いマスキング枠を広げ、元の語句の長さが分かりにくくします。長い枠は縮めません。",
            )
            self.opt_log = self._option("墨消し記録を出力", True, "マスキングした位置と種類の一覧を、CSVで書き出します。")
            self.opt_terms = self._option("元の語句を含める", False, "記録に元の語句を入れます。そのCSVも機密になります。")
            self.opt_table = self._option("置換表を別ファイルに保存", False, "呼び名の対応表を、PDFとは別のCSVに保存します。")
            for box in (self.opt_align, self.opt_log, self.opt_terms, self.opt_table):
                self.dialog_layout.addWidget(box)
        self.dialog_layout.addLayout(buttons)
        self._show_shade()

    def _option(self, text: str, checked: bool, tip: str) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(checked)
        box.setToolTip(tip)
        return box

    def _browse_save(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "別名で保存", self.save_path.text(), "PDF (*.pdf)")
        if path:
            self.save_path.setText(path)

    def _save(self) -> None:
        if not self.session:
            return
        dest = Path(self.save_path.text())
        source = Path(self.session.document.source_path).resolve()
        if dest.resolve() == source:
            QMessageBox.warning(self, "ekisui-pdf", "元のファイルは上書きしません。別の名前を指定してください。")
            return
        masked = self._save_mode == "masked"
        extras = ("_墨消し記録.csv", "_置換表.csv") if masked else ()
        dest = unique_destination(dest, extras)
        if masked:
            self.align_boxes = self.opt_align.isChecked()
            options = SaveOptions(
                align_box_width=self.align_boxes,
                strip_metadata=self.opt_meta.isChecked(),
                export_log=self.opt_log.isChecked(),
                include_original_terms=self.opt_terms.isChecked(),
                export_replacement_table=self.opt_table.isChecked(),
            )
            groups = self.session.groups
        else:
            options = SaveOptions(
                align_box_width=False,
                strip_metadata=self.opt_meta.isChecked(),
                export_log=False,
                include_original_terms=False,
                export_replacement_table=False,
            )
            groups = []
        try:
            result = export_pdf(self.session.document, groups, dest, options, self.session.settings)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "ekisui-pdf", f"保存できませんでした。\n{exc}")
            return
        if not masked:
            self._show_ocr_saved(result.pdf_path)
            return
        try:
            report = verify_pdf(
                result.pdf_path,
                self.session.groups,
                self.session.settings,
                self.session.table,
                options.strip_metadata,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "ekisui-pdf", f"保存後の確認ができませんでした。\n{exc}")
            return
        self._show_verify(result.pdf_path, result.log_path, report)

    def _show_ocr_saved(self, pdf_path: str) -> None:
        self._clear_dialog()
        title = QLabel("保存しました")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #1e6b34;")
        body = QLabel(f"読み取ったPDFを保存しました。マスキングはしていません。\n保存先 {Path(pdf_path).name}")
        body.setWordWrap(True)
        close = QPushButton("閉じる")
        _mark(close, "primary")
        close.setToolTip("この画面を閉じます。")
        close.clicked.connect(self.shade.hide)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)
        self.dialog_layout.addWidget(title)
        self.dialog_layout.addWidget(body)
        self.dialog_layout.addLayout(buttons)
        self.preview = False
        self._show_shade()

    def _show_verify(self, pdf_path: str, log_path: str | None, report: VerifyReport) -> None:
        self._clear_dialog()
        if report.passed:
            title = QLabel("保存しました")
            title.setStyleSheet("font-size: 18px; font-weight: 600; color: #1e6b34;")
            if report.checked_terms == 0:
                message = "確認する語句がありませんでした"
            else:
                message = "消した語句は見つかりませんでした"
            body = QLabel(message)
            body.setProperty("class", "okbig")
            detail = QLabel(
                f"確認した語句 {report.checked_terms}語（表記ゆれ含む {report.checked_surfaces}）\n"
                f"保存先 {Path(pdf_path).name}"
                + (f"\n墨消し記録 {Path(log_path).name}" if log_path else "")
            )
            detail.setWordWrap(True)
            self.dialog_layout.addWidget(title)
            self.dialog_layout.addWidget(body)
            self.dialog_layout.addWidget(detail)
        else:
            title = QLabel("残っている語句があります" if not report.clean else "メタデータが残っています")
            title.setStyleSheet("font-size: 18px; font-weight: 600;")
            count = QLabel(f"{len(report.leftovers)}件")
            count.setStyleSheet("font-size: 16px; color: #8f1f14;")
            self.dialog_layout.addWidget(title)
            self.dialog_layout.addWidget(count)
            holder = QWidget()
            holder_box = QVBoxLayout(holder)
            holder_box.setContentsMargins(0, 0, 0, 0)
            for leftover in report.leftovers[:8]:
                row = QHBoxLayout()
                label = "完全一致" if leftover.kind == MatchKind.EXACT else f"ゆるい一致（{round(leftover.score * 100)}%）"
                term = QLabel(leftover.term)
                term.setWordWrap(True)
                row.addWidget(term, 1)
                row.addWidget(QLabel(label))
                row.addWidget(QLabel(f"p.{leftover.page_index + 1}"))
                jump = QPushButton("移動")
                _mark(jump, "btn")
                jump.setToolTip("このページを開きます。")
                jump.clicked.connect(lambda _c=False, page=leftover.page_index: self._jump_from_verify(page))
                row.addWidget(jump)
                holder_box.addLayout(row)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(holder)
            scroll.setMaximumHeight(280)
            self.dialog_layout.addWidget(scroll)
        buttons = QHBoxLayout()
        if report.passed:
            folder = QPushButton("フォルダを開く")
            _mark(folder, "btn")
            folder.setToolTip("保存したファイルのフォルダを開きます。")
            folder.clicked.connect(lambda: os.startfile(str(Path(pdf_path).parent)) if hasattr(os, "startfile") else None)
            close = QPushButton("閉じる")
            _mark(close, "primary")
            close.clicked.connect(self.shade.hide)
            buttons.addStretch(1)
            buttons.addWidget(folder)
            buttons.addWidget(close)
        else:
            leave = QPushButton("このまま閉じる")
            _mark(leave, "btn")
            leave.clicked.connect(self.shade.hide)
            fix = QPushButton("修正する")
            _mark(fix, "primary")
            page = report.leftovers[0].page_index if report.leftovers else self.page_index
            fix.clicked.connect(lambda: self._jump_from_verify(page))
            buttons.addStretch(1)
            buttons.addWidget(leave)
            buttons.addWidget(fix)
        self.dialog_layout.addLayout(buttons)
        self.preview = True
        self._show_shade()
        self.refresh()

    def show_report(self, report: VerifyReport) -> None:
        """Used by the screenshot harness to open the real verify dialog."""
        self._show_verify("", None, report)

    def _jump_from_verify(self, page: int) -> None:
        self.shade.hide()
        self._goto(page)

    def _open_settings(self) -> None:
        current = self.session.settings if self.session else self.settings
        self._clear_dialog()
        title = QLabel("設定")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.fuzzy = QSlider(Qt.Orientation.Horizontal)
        self.fuzzy.setRange(50, 90)
        self.fuzzy.setValue(round(current.fuzzy_threshold * 100))
        self.fuzzy_label = QLabel(f"ゆるい一致 {self.fuzzy.value()}%")
        self.fuzzy.valueChanged.connect(lambda value: self.fuzzy_label.setText(f"ゆるい一致 {value}%"))
        self.review = QSpinBox()
        self.review.setRange(50, 99)
        self.review.setValue(round(current.review_below * 100))
        self.review_label = QLabel("要確認にする信頼度（%）")
        self.align = QSpinBox()
        self.align.setRange(1, 12)
        self.align.setValue(current.align_chars)
        self.align_label = QLabel("枠の幅（文字数）")
        buttons = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        _mark(cancel, "btn")
        cancel.clicked.connect(self.shade.hide)
        apply = QPushButton("適用")
        _mark(apply, "primary")
        apply.clicked.connect(self._apply_settings)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        self.dialog_layout.addWidget(title)
        self.dialog_layout.addWidget(self._info_row(
            self.fuzzy_label,
            "4文字以上だけに効きます（初期値60%）。下げると読み違いを多く拾い、上げると厳しい一致だけ残します。2〜3文字はこの％を使わず、全体が読み間違い表で一致する語句は残します。",
        ))
        self.dialog_layout.addWidget(self.fuzzy)
        self.dialog_layout.addWidget(self._info_row(
            self.review_label,
            "この％未満の読み取り行を要確認にします（初期値80%）。上げると多くの行が対象になり、下げると自信のない行だけです。手で直した行は対象外です。",
        ))
        self.dialog_layout.addWidget(self.review)
        self.dialog_layout.addWidget(self._info_row(
            self.align_label,
            "短いマスキング枠の最小の幅です（初期値5文字）。上げると元の長さが分かりにくくなり、下げると実際の長さに近づきます。もともと広い枠は縮みません。",
        ))
        self.dialog_layout.addWidget(self.align)
        self.dialog_layout.addLayout(buttons)
        self._show_shade()

    def _info_row(self, label: QLabel, tip: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        info = QPushButton("i")
        info.setObjectName("info")
        info.setToolTip(tip)
        info.setCursor(Qt.CursorShape.PointingHandCursor)
        info.clicked.connect(lambda _checked=False, button=info, text=tip: QToolTip.showText(button.mapToGlobal(QPoint(0, button.height())), text, button))
        layout.addWidget(label)
        layout.addWidget(info)
        layout.addStretch(1)
        return row

    def _apply_settings(self) -> None:
        updated = replace(
            self.session.settings if self.session else self.settings,
            fuzzy_threshold=self.fuzzy.value() / 100,
            review_below=self.review.value() / 100,
            align_chars=self.align.value(),
        )
        self.settings = updated
        if self.session:
            self.session.set_settings(updated)
        self.shade.hide()
        self.refresh()

    def _clear_dialog(self) -> None:
        self._discard_layout(self.dialog_layout)

    def _discard_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            child = item.layout()
            if child is not None:
                self._discard_layout(child)

    def _show_shade(self) -> None:
        self.shade.setGeometry(self.centralWidget().rect())
        self.shade.show()
        self.shade.raise_()

    @staticmethod
    def _pages(pages: set[int]) -> str:
        if not pages:
            return "なし"
        return ", ".join(str(number) for number in sorted(pages))


def _render_pdf(path: str, index: int, dpi: int) -> QPixmap:
    document = pymupdf.open(path)
    try:
        page = document[index]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False, colorspace=pymupdf.csRGB)
        image = QPixmap()
        from PySide6.QtGui import QImage

        qimage = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, QImage.Format.Format_RGB888).copy()
        image = QPixmap.fromImage(qimage)
        return image
    finally:
        document.close()
