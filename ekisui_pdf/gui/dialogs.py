from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ekisui_pdf.core.models import ExportResult, SaveOptions
from ekisui_pdf.gui.style import DISCLAIMER


class OcrProgressDialog(QDialog):
    def __init__(self, page_count: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OCR")
        self.setModal(True)
        self.cancelled = False
        self.resize(460, 180)
        layout = QVBoxLayout(self)
        self.message = QLabel("準備しています。")
        self.message.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, max(page_count, 1))
        self.bar.setValue(0)
        note = QLabel("モデルは同梱ファイルだけを使います。通信しません。中断すると、終わったページまで残します。")
        note.setWordWrap(True)
        cancel = QPushButton("中断")
        cancel.clicked.connect(self.reject)
        layout.addWidget(self.message)
        layout.addWidget(self.bar)
        layout.addWidget(note)
        layout.addWidget(cancel)

    def set_progress(self, done: int, total: int, message: str) -> None:
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(done)
        self.message.setText(message)

    def reject(self) -> None:
        self.cancelled = True
        super().reject()


class SaveOptionsDialog(QDialog):
    def __init__(self, suggested: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("名前を付けて保存")
        self.resize(560, 320)
        self.path_edit = QLineEdit(str(suggested))
        browse = QPushButton("参照")
        browse.setObjectName("quiet")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse)

        self.strip_box = QCheckBox("メタデータを削除する")
        self.strip_box.setChecked(True)
        self.strip_box.setToolTip("文書情報、XMP、添付ファイル、JavaScript、注釈、サムネイルを落とします。")
        strip_help = QLabel(
            "保存は常に別ファイルで、増分更新ではなく作り直します。元画像の残りと古い改訂は捨てます。"
            "チェックを外すと、文書情報や注釈は残ります。"
        )
        strip_help.setWordWrap(True)

        self.fixed_box = QCheckBox("黒塗りの幅を揃える")
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(40, 600)
        self.width_spin.setValue(160)
        self.width_spin.setSuffix(" pt")
        self.width_spin.setEnabled(False)
        self.fixed_box.toggled.connect(self.width_spin.setEnabled)
        fixed_help = QLabel(
            "幅は、指定した値と、選択の中でいちばん広いものの、大きい方に揃えます。"
            "短い名前の幅から文字数を読まれにくくするためです。隣の文字に被ることがあります。"
        )
        fixed_help.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("保存先", path_row)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.strip_box)
        layout.addWidget(strip_help)
        layout.addWidget(self.fixed_box)
        layout.addWidget(self.width_spin)
        layout.addWidget(fixed_help)
        disclaimer = QLabel(DISCLAIMER)
        disclaimer.setWordWrap(True)
        disclaimer.setObjectName("disclaimer")
        layout.addWidget(disclaimer)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        current = self.path_edit.text() or "output.pdf"
        chosen, _ = QFileDialog.getSaveFileName(self, "保存先", current, "PDF (*.pdf)")
        if chosen:
            if not chosen.lower().endswith(".pdf"):
                chosen += ".pdf"
            self.path_edit.setText(chosen)

    def values(self) -> tuple[Path, SaveOptions]:
        return Path(self.path_edit.text()), SaveOptions(
            strip_metadata=self.strip_box.isChecked(),
            fixed_width=self.fixed_box.isChecked(),
            fixed_width_pt=float(self.width_spin.value()),
        )


class VerifyResultDialog(QDialog):
    def __init__(self, result: ExportResult, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("保存後の検証")
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        if not result.report.checked_terms:
            title = QLabel("確認する文字列なし")
            title.setObjectName("fail")
        else:
            title = QLabel("合格" if result.report.passed else "残存あり")
            title.setObjectName("pass" if result.report.passed else "fail")
        layout.addWidget(title)
        detail = QLabel(result.report.summary)
        detail.setWordWrap(True)
        layout.addWidget(detail)
        counts = QLabel(
            f"墨消し {result.redaction_count}件、仮名への置換 {result.pseudonym_count}件。"
            + (
                f" 揃えた幅は約 {result.applied_box_width:.0f} pt です。"
                if result.applied_box_width
                else ""
            )
        )
        counts.setWordWrap(True)
        layout.addWidget(counts)
        path = QLabel(f"保存先: {result.output_path}")
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path)
        listing = QListWidget()
        if not result.report.checked_terms:
            listing.addItem("選択した文字列がないため、残存の確認はしていません。")
        elif result.report.leftovers:
            for leftover in result.report.leftovers:
                listing.addItem(leftover.describe())
        else:
            listing.addItem(
                "選んだ元の文字列は、ページ外の文字、しおり、文書情報、注釈、ページラベル、"
                "UTF-8 / UTF-16 とその16進表記からも見つかりませんでした。"
            )
        layout.addWidget(listing)
        note = QLabel(
            "検証は文字層と、しおりなどの文字列を見ます。画像の画素をもう一度OCRしてはいません。"
            "選んでいない出現や、OCRが読み落とした文字は残り得ます。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        disclaimer = QLabel(DISCLAIMER)
        disclaimer.setWordWrap(True)
        disclaimer.setObjectName("disclaimer")
        layout.addWidget(disclaimer)
        close = QPushButton("閉じる")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
