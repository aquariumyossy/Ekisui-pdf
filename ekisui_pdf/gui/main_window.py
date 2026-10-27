from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ekisui_pdf.core.errors import EkisuiError
from ekisui_pdf.core.geometry import char_indexes_in_rect, span_rect, union_rect
from ekisui_pdf.core.models import Action, OcrLine, Rect, ReplacementEntry, Selection
from ekisui_pdf.core.pdfio import export_pdf, open_document, paths_are_same, render_page_rgb
from ekisui_pdf.core.table import ReplacementTable, load_table, save_table
from ekisui_pdf.core.variants import TextHit, find_variants, group_surfaces, search_phrase
from ekisui_pdf.gui.dialogs import OcrProgressDialog, SaveOptionsDialog, VerifyResultDialog
from ekisui_pdf.gui.page_view import PageView, pixmap_to_qimage
from ekisui_pdf.gui.style import DISCLAIMER
from ekisui_pdf.gui.worker import OcrWorker
from ekisui_pdf.paths import models_dir


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("易水PDF")
        self.resize(1280, 840)
        self.document = None
        self.source_path: Path | None = None
        self.lines: list[OcrLine] = []
        self.selections: list[Selection] = []
        self.table = ReplacementTable()
        self.variant_groups: list[tuple[str, list[TextHit]]] = []
        self.page_index = 0
        self._worker: OcrWorker | None = None
        self._ocr_dialog: OcrProgressDialog | None = None
        self._ocr_buffer: list[OcrLine] = []
        self._ocr_next = 0
        self._ocr_done = False
        self._building_tables = False
        self._build()

    def _build(self) -> None:
        self.view = PageView()
        self.view.region_selected.connect(self._add_manual_region)
        self._build_menu()
        self._build_toolbar()

        self.selection_table = QTableWidget(0, 4)
        self.selection_table.setHorizontalHeaderLabels(["ページ", "文字列", "操作", "仮名"])
        self.selection_table.horizontalHeader().setStretchLastSection(True)
        self.selection_table.itemChanged.connect(self._selection_item_changed)
        self.selection_table.itemSelectionChanged.connect(self._jump_to_selected_row)
        selection_buttons = QHBoxLayout()
        jump = QPushButton("表示")
        jump.setObjectName("quiet")
        jump.clicked.connect(self._jump_to_selected_row)
        remove = QPushButton("削除")
        remove.setObjectName("quiet")
        remove.clicked.connect(self._remove_selected_row)
        clear = QPushButton("すべて削除")
        clear.setObjectName("quiet")
        clear.clicked.connect(self._clear_selections)
        selection_buttons.addWidget(jump)
        selection_buttons.addWidget(remove)
        selection_buttons.addWidget(clear)
        selection_box = QGroupBox("選択")
        selection_layout = QVBoxLayout(selection_box)
        selection_layout.addWidget(QLabel("ページ上をドラッグするか、語句を検索します。"))
        selection_layout.addWidget(self.selection_table)
        selection_layout.addLayout(selection_buttons)

        self.replacement_table = QTableWidget(0, 2)
        self.replacement_table.setHorizontalHeaderLabels(["原文", "仮名"])
        self.replacement_table.horizontalHeader().setStretchLastSection(True)
        self.replacement_table.itemChanged.connect(self._table_item_changed)
        table_buttons = QHBoxLayout()
        add_row = QPushButton("行を追加")
        add_row.setObjectName("quiet")
        add_row.clicked.connect(self._add_table_row)
        del_row = QPushButton("行を削除")
        del_row.setObjectName("quiet")
        del_row.clicked.connect(self._remove_table_row)
        find_var = QPushButton("表記ゆれを探す")
        find_var.setObjectName("quiet")
        find_var.clicked.connect(self._find_variants_for_row)
        table_buttons.addWidget(add_row)
        table_buttons.addWidget(del_row)
        table_buttons.addWidget(find_var)
        table_box = QGroupBox("置換表（PDFには入れません）")
        table_layout = QVBoxLayout(table_box)
        table_layout.addWidget(QLabel("同じ原文には同じ仮名を使います。表の保存先は別ファイルです。"))
        table_layout.addWidget(self.replacement_table)
        table_layout.addLayout(table_buttons)

        self.variant_list = QListWidget()
        variant_buttons = QHBoxLayout()
        add_table = QPushButton("表に追加")
        add_table.setObjectName("quiet")
        add_table.clicked.connect(self._add_variant_to_table)
        add_sel = QPushButton("選択に追加")
        add_sel.setObjectName("quiet")
        add_sel.clicked.connect(self._add_variant_to_selections)
        variant_buttons.addWidget(add_table)
        variant_buttons.addWidget(add_sel)
        variant_box = QGroupBox("表記ゆれ")
        variant_layout = QVBoxLayout(variant_box)
        variant_layout.addWidget(
            QLabel("全角半角、空白、株式会社などの違いです。確認してから表や選択に入れてください。")
        )
        variant_layout.addWidget(self.variant_list)
        variant_layout.addLayout(variant_buttons)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(selection_box, 3)
        side_layout.addWidget(table_box, 2)
        side_layout.addWidget(variant_box, 2)

        splitter = QSplitter()
        splitter.addWidget(self.view)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([820, 420])

        footer = QLabel(DISCLAIMER)
        footer.setObjectName("disclaimer")
        footer.setWordWrap(True)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(splitter)
        layout.addWidget(footer)
        self.setCentralWidget(central)
        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage("PDFを開いてください。ドラッグで範囲を選べます。Ctrl+ホイールで拡大します。")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("ファイル")
        open_action = QAction("開く", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._pick_pdf)
        save_action = QAction("名前を付けて保存", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._save)
        table_save = QAction("置換表を保存", self)
        table_save.triggered.connect(self._save_table)
        table_load = QAction("置換表を読み込む", self)
        table_load.triggered.connect(self._load_table)
        quit_action = QAction("終了", self)
        quit_action.triggered.connect(self.close)
        for action in (open_action, save_action, table_save, table_load, quit_action):
            file_menu.addAction(action)

        tool_menu = self.menuBar().addMenu("ツール")
        ocr_action = QAction("OCRを実行", self)
        ocr_action.setShortcut(QKeySequence("Ctrl+R"))
        ocr_action.triggered.connect(self._start_ocr)
        tool_menu.addAction(ocr_action)

        help_menu = self.menuBar().addMenu("ヘルプ")
        about = QAction("このアプリについて", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    def _build_toolbar(self) -> None:
        bar = self.addToolBar("操作")
        bar.setMovable(False)
        open_button = QPushButton("開く")
        open_button.clicked.connect(self._pick_pdf)
        ocr_button = QPushButton("OCR")
        ocr_button.clicked.connect(self._start_ocr)
        save_button = QPushButton("保存")
        save_button.clicked.connect(self._save)
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(self._page_changed)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(25, 400)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.valueChanged.connect(lambda value: self.view.set_zoom(value / 100))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("検索する語")
        self.search_box.setFixedWidth(180)
        self.search_box.returnPressed.connect(self._search)
        self.variant_check = QCheckBox("表記ゆれも含める")
        search_button = QPushButton("検索して選択")
        search_button.clicked.connect(self._search)
        for widget in (
            open_button,
            ocr_button,
            save_button,
            QLabel("ページ"),
            self.page_spin,
            QLabel("拡大"),
            self.zoom_slider,
            self.search_box,
            self.variant_check,
            search_button,
        ):
            bar.addWidget(widget)

    def _pick_pdf(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "PDFを開く", "", "PDF (*.pdf)")
        if chosen:
            self.open_pdf(Path(chosen))

    def open_pdf(self, path: Path) -> None:
        self._stop_worker()
        try:
            document = open_document(path)
        except EkisuiError as exc:
            QMessageBox.warning(self, "開く", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "開く", f"PDFを開けませんでした。\n{exc}")
            return
        if self.document is not None:
            self.document.close()
        self.document = document
        self.source_path = Path(path)
        self.lines = []
        self.selections = []
        self.variant_groups = []
        had_table = bool(self.table.entries)
        self.table = ReplacementTable()
        self.page_index = 0
        self._refresh_all()
        message = f"{path.name} を開きました。{document.page_count}ページ。OCRはまだです。"
        if had_table:
            message += " 別事件の仮名が残らないよう、置換表は空にしました。"
        self.statusBar().showMessage(message)

    def load_ocr_lines(self, lines: list[OcrLine]) -> None:
        self.lines = list(lines)
        self._refresh_all()
        self.statusBar().showMessage(f"文字層の元になる行を {len(self.lines)} 件読みました。保存するまでPDFは変わりません。")

    def _page_changed(self, number: int) -> None:
        if self.document is None:
            return
        self.page_index = number - 1
        self._show_page()

    def _show_page(self) -> None:
        if self.document is None:
            return
        page = self.document[self.page_index]
        image = pixmap_to_qimage(render_page_rgb(page, dpi=144))
        self.view.set_page_image(image, page.rect.width, page.rect.height)
        self.view.set_zoom(self.zoom_slider.value() / 100)
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(max(self.document.page_count, 1))
        self.page_spin.setValue(self.page_index + 1)
        self.page_spin.blockSignals(False)
        self._draw_overlays()

    def _draw_overlays(self) -> None:
        boxes = []
        for selection in self.selections:
            if selection.page_index != self.page_index:
                continue
            color = QColor("#9b2c2c") if selection.action == Action.REDACT else QColor("#1d4e89")
            boxes.append((selection.rect, color))
        self.view.set_overlays(boxes)

    def _refresh_all(self) -> None:
        self._refresh_selection_table()
        self._refresh_replacement_table()
        self._refresh_variant_list()
        if self.document is not None:
            self._show_page()

    def _add_manual_region(self, rect: Rect) -> None:
        if self.document is None:
            return
        created: list[Selection] = []
        for line in self.lines:
            if line.page_index != self.page_index:
                continue
            indexes = char_indexes_in_rect(line, rect)
            if not indexes:
                continue
            start, end = indexes[0], indexes[-1] + 1
            text_rect = span_rect(line, start, end)
            created.append(
                self._new_selection(
                    page_index=line.page_index,
                    rect=union_rect(rect, text_rect),
                    matched_text=line.text[start:end],
                    source="manual",
                    line_id=line.line_id,
                    char_start=start,
                    char_end=end,
                )
            )
        if not created:
            created.append(self._new_selection(self.page_index, rect, "", "manual"))
        self.selections.extend(created)
        self._refresh_selection_table()
        self._draw_overlays()
        self.statusBar().showMessage(f"範囲を {len(created)} 件追加しました。")

    def _search(self) -> None:
        query = self.search_box.text().strip()
        if not query:
            return
        if not self.lines:
            QMessageBox.information(self, "検索", "先にOCRを実行してください。検索はOCRの結果に対して行います。")
            return
        hits = find_variants(self.lines, query) if self.variant_check.isChecked() else search_phrase(self.lines, query)
        added = self._add_hits(hits)
        if not added:
            QMessageBox.information(self, "検索", "一致はありませんでした。")
            return
        self.statusBar().showMessage(f"「{query}」の一致 {added} 件を選択に追加しました。")

    def _add_hits(self, hits: list[TextHit], action: Action = Action.REDACT, pseudonym: str = "") -> int:
        added = 0
        existing = {(item.line_id, item.char_start, item.char_end) for item in self.selections}
        for hit in hits:
            key = (hit.line_id, hit.char_start, hit.char_end)
            if key in existing:
                continue
            existing.add(key)
            self.selections.append(
                self._new_selection(
                    page_index=hit.page_index,
                    rect=hit.rect,
                    matched_text=hit.surface,
                    source="search",
                    line_id=hit.line_id,
                    char_start=hit.char_start,
                    char_end=hit.char_end,
                    action=action,
                    pseudonym=pseudonym,
                )
            )
            added += 1
        if added:
            self._refresh_selection_table()
            self._draw_overlays()
        return added

    def _new_selection(self, page_index: int, rect: Rect, matched_text: str, source: str, **extra) -> Selection:
        pseudonym = extra.pop("pseudonym", "") or self.table.pseudonym_for(matched_text) or ""
        if not pseudonym and matched_text:
            pseudonym = self.table.pseudonym_for_core(matched_text) or ""
        return Selection(
            id=uuid.uuid4().hex[:12],
            page_index=page_index,
            rect=rect,
            matched_text=matched_text,
            pseudonym=pseudonym,
            source=source,
            **extra,
        )

    def _refresh_selection_table(self) -> None:
        self._building_tables = True
        self.selection_table.setRowCount(len(self.selections))
        for row, selection in enumerate(self.selections):
            page_item = QTableWidgetItem(str(selection.page_index + 1))
            page_item.setFlags(page_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            page_item.setData(Qt.ItemDataRole.UserRole, selection.id)
            text_item = QTableWidgetItem(selection.matched_text or "（文字なし）")
            text_item.setFlags(text_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            text_item.setData(Qt.ItemDataRole.UserRole, selection.id)
            pseudo = QTableWidgetItem(selection.pseudonym)
            pseudo.setData(Qt.ItemDataRole.UserRole, selection.id)
            pseudo.setToolTip("空欄のときは、保存時に置換表を見ます。")
            self.selection_table.setItem(row, 0, page_item)
            self.selection_table.setItem(row, 1, text_item)
            self.selection_table.setItem(row, 3, pseudo)
            combo = QComboBox()
            combo.addItem("墨消し（黒塗り）", Action.REDACT)
            combo.addItem("仮名に置換", Action.PSEUDONYM)
            combo.setCurrentIndex(1 if selection.action == Action.PSEUDONYM else 0)
            combo.currentIndexChanged.connect(lambda _index, sid=selection.id: self._set_action(sid))
            self.selection_table.setCellWidget(row, 2, combo)
        self.selection_table.resizeColumnsToContents()
        self._building_tables = False

    def _selection_by_id(self, selection_id: str) -> Selection | None:
        for selection in self.selections:
            if selection.id == selection_id:
                return selection
        return None

    def _set_action(self, selection_id: str) -> None:
        if self._building_tables:
            return
        selection = self._selection_by_id(selection_id)
        if selection is None:
            return
        row = self.selections.index(selection)
        combo = self.selection_table.cellWidget(row, 2)
        if isinstance(combo, QComboBox):
            selection.action = combo.currentData()
        self._draw_overlays()

    def _selection_item_changed(self, item: QTableWidgetItem) -> None:
        if self._building_tables or item.column() != 3:
            return
        selection = self._selection_by_id(item.data(Qt.ItemDataRole.UserRole))
        if selection is not None:
            selection.pseudonym = item.text().strip()

    def _current_selection_row(self) -> int:
        rows = self.selection_table.selectionModel().selectedRows()
        if rows:
            return rows[0].row()
        return self.selection_table.currentRow()

    def _jump_to_selected_row(self) -> None:
        row = self._current_selection_row()
        if row < 0 or row >= len(self.selections) or self.document is None:
            return
        self.page_index = self.selections[row].page_index
        self._show_page()

    def _remove_selected_row(self) -> None:
        row = self._current_selection_row()
        if row < 0 or row >= len(self.selections):
            return
        del self.selections[row]
        self._refresh_selection_table()
        self._draw_overlays()

    def _clear_selections(self) -> None:
        self.selections = []
        self._refresh_selection_table()
        self._draw_overlays()

    def _refresh_replacement_table(self) -> None:
        self._building_tables = True
        self.replacement_table.setRowCount(len(self.table.entries))
        for row, entry in enumerate(self.table.entries):
            self.replacement_table.setItem(row, 0, QTableWidgetItem(entry.term))
            self.replacement_table.setItem(row, 1, QTableWidgetItem(entry.pseudonym))
        self._building_tables = False

    def _table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._building_tables:
            return
        row = item.row()
        if row >= len(self.table.entries):
            return
        entry = self.table.entries[row]
        if item.column() == 0:
            entry.term = item.text().strip()
        else:
            entry.pseudonym = item.text().strip()

    def _add_table_row(self) -> None:
        term = self.search_box.text().strip()
        if term:
            self.table.upsert(term, self.table.pseudonym_for(term) or "")
        else:
            self.table.entries.append(ReplacementEntry(term="", pseudonym=""))
        self._refresh_replacement_table()

    def _remove_table_row(self) -> None:
        row = self.replacement_table.currentRow()
        self.table.remove_at(row)
        self._refresh_replacement_table()

    def _find_variants_for_row(self) -> None:
        row = self.replacement_table.currentRow()
        if row < 0 or row >= len(self.table.entries):
            term = self.search_box.text().strip()
        else:
            term = self.table.entries[row].term.strip()
        if not term:
            return
        if not self.lines:
            QMessageBox.information(self, "表記ゆれ", "先にOCRを実行してください。")
            return
        hits = find_variants(self.lines, term)
        self.variant_groups = [(surface, group) for surface, group in group_surfaces(hits) if surface != term]
        self._refresh_variant_list()
        self.statusBar().showMessage(f"「{term}」の表記ゆれ {len(self.variant_groups)} 種です。")

    def _refresh_variant_list(self) -> None:
        self.variant_list.clear()
        for surface, hits in self.variant_groups:
            self.variant_list.addItem(f"{surface}（{len(hits)}件）")

    def _selected_variant(self) -> tuple[str, list[TextHit]] | None:
        row = self.variant_list.currentRow()
        if row < 0 or row >= len(self.variant_groups):
            return None
        return self.variant_groups[row]

    def _add_variant_to_table(self) -> None:
        chosen = self._selected_variant()
        if chosen is None:
            return
        surface, _hits = chosen
        pseudonym = self.table.pseudonym_for_core(surface) or ""
        self.table.upsert(surface, pseudonym)
        self._refresh_replacement_table()

    def _add_variant_to_selections(self) -> None:
        chosen = self._selected_variant()
        if chosen is None:
            return
        surface, hits = chosen
        pseudonym = self.table.pseudonym_for(surface) or self.table.pseudonym_for_core(surface) or ""
        action = Action.PSEUDONYM if pseudonym else Action.REDACT
        added = self._add_hits(hits, action=action, pseudonym=pseudonym)
        self.statusBar().showMessage(f"「{surface}」を {added} 件、選択に追加しました。")

    def _save_table(self) -> None:
        suggested = "置換表.json"
        if self.source_path is not None:
            suggested = str(self.source_path.with_name(self.source_path.stem + "-置換表.json"))
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "置換表を保存",
            suggested,
            "JSON (*.json);;CSV (*.csv)",
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() not in {".json", ".csv"}:
            path = path.with_suffix(".json")
        save_table(path, self.table)
        self.statusBar().showMessage(f"置換表を保存しました。PDFには入れていません。{path}")

    def _load_table(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "置換表を読み込む", "", "表 (*.json *.csv)")
        if not chosen:
            return
        try:
            self.table = load_table(Path(chosen))
        except Exception as exc:
            QMessageBox.warning(self, "置換表", f"読み込めませんでした。\n{exc}")
            return
        self._refresh_replacement_table()

    def _start_ocr(self) -> None:
        if self.document is None:
            QMessageBox.information(self, "OCR", "先にPDFを開いてください。")
            return
        self._stop_worker()
        self._ocr_buffer = []
        self._ocr_next = 0
        self._ocr_done = False
        self._ocr_dialog = OcrProgressDialog(self.document.page_count, self)
        self._worker = OcrWorker(models_dir(), self)
        self._worker.recognized.connect(self._on_ocr_page)
        self._worker.failed.connect(self._on_ocr_failed)
        self._worker.start()
        QTimer.singleShot(0, self._submit_ocr_page)
        self._ocr_dialog.exec()
        if not self._ocr_done:
            self._complete_ocr(stopped=True)
        self._stop_worker()
        self._ocr_dialog = None

    def _submit_ocr_page(self) -> None:
        dialog = self._ocr_dialog
        if self._ocr_done or dialog is None or dialog.cancelled or self.document is None or self._worker is None:
            self._complete_ocr(stopped=True)
            return
        index = self._ocr_next
        total = self.document.page_count
        dialog.set_progress(index, total, f"{index + 1} / {total} ページを読み取っています。通信はしていません。")
        from ekisui_pdf.core.ocr import render_page_bgr

        image, zoom = render_page_bgr(self.document[index], dpi=200)
        self._worker.submit(index, image, zoom)

    def _on_ocr_page(self, index: int, lines: object) -> None:
        if self._ocr_done:
            return
        self._ocr_buffer.extend(lines)
        self._ocr_next = index + 1
        total = self.document.page_count if self.document is not None else self._ocr_next
        if self._ocr_dialog is not None:
            self._ocr_dialog.set_progress(self._ocr_next, total, f"{self._ocr_next} / {total} ページまで終わりました。")
        if self._ocr_dialog is None or self._ocr_dialog.cancelled or self._ocr_next >= total:
            self._complete_ocr(stopped=bool(self._ocr_dialog and self._ocr_dialog.cancelled))
            return
        QTimer.singleShot(0, self._submit_ocr_page)

    def _on_ocr_failed(self, message: str) -> None:
        if self._ocr_done:
            return
        self._ocr_done = True
        QMessageBox.critical(self, "OCR", message)
        if self._ocr_dialog is not None:
            self._ocr_dialog.done(0)

    def _complete_ocr(self, stopped: bool) -> None:
        if self._ocr_done:
            return
        self._ocr_done = True
        if self._ocr_buffer:
            self.lines = list(self._ocr_buffer)
        if stopped:
            self.statusBar().showMessage(f"OCRを中断しました。{len(self.lines)}行まで保持しています。")
        else:
            self.statusBar().showMessage(
                f"OCRが完了しました。{len(self.lines)}行。保存すると、透明な文字層が入ります。"
            )
        if self._ocr_dialog is not None:
            self._ocr_dialog.done(0)

    def closeEvent(self, event) -> None:
        self._ocr_done = True
        self._stop_worker()
        if self.document is not None:
            self.document.close()
            self.document = None
        super().closeEvent(event)

    def _stop_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        if worker.isRunning():
            worker.stop()
            worker.wait()

    def _suggested_pdf(self) -> Path:
        if self.source_path is None:
            return Path.home() / "易水.pdf"
        return self.source_path.with_name(self.source_path.stem + "-易水.pdf")

    def _save(self) -> None:
        if self.document is None or self.source_path is None:
            QMessageBox.information(self, "保存", "先にPDFを開いてください。")
            return
        dialog = SaveOptionsDialog(self._suggested_pdf(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dest, options = dialog.values()
        if not str(dest).strip():
            return
        if paths_are_same(self.source_path, dest):
            QMessageBox.warning(self, "保存", "元のファイルは上書きしません。別の名前で保存してください。")
            return
        if dest.exists():
            answer = QMessageBox.question(self, "保存", f"すでにファイルがあります。上書きしますか？\n{dest}")
            if answer != QMessageBox.StandardButton.Yes:
                return
        conflicts = self.table.conflicting_cores()
        if conflicts:
            QMessageBox.warning(
                self,
                "置換表",
                "同じ語なのに仮名が分かれています。表を確認してください。\n" + "、".join(conflicts[:6]),
            )
            return
        try:
            result = export_pdf(
                self.document,
                dest,
                self.lines,
                self.selections,
                self.table,
                options,
                source_path=self.source_path,
            )
        except EkisuiError as exc:
            QMessageBox.warning(self, "保存", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "保存", f"保存できませんでした。\n{exc}")
            return
        VerifyResultDialog(result, self).exec()
        self.statusBar().showMessage(result.report.summary + f" {result.output_path}")

    def _about(self) -> None:
        QMessageBox.information(
            self,
            "易水PDF",
            "易水会のワークショップのお礼として配る、手元だけで動くPDFツールです。\n\n"
            "OCRは PP-OCRv5（日本語を含む中国語系モデル）を ONNX Runtime で動かします。"
            "PaddlePaddle は同梱していません。実行中にモデルを取りに行きません。\n\n"
            + DISCLAIMER,
        )
