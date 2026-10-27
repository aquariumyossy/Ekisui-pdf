STYLE = """
* {
    font-family: "Yu Gothic UI", "Yu Gothic", "Meiryo", "Noto Sans CJK JP", "WenQuanYi Micro Hei", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog {
    background: #f6f3ec;
    color: #1e1a16;
}
QToolBar {
    background: #1d3557;
    border: 0;
    spacing: 8px;
    padding: 4px;
}
QToolBar QLabel, QToolBar QCheckBox {
    color: #f6f3ec;
}
QToolBar QLineEdit, QToolBar QSpinBox, QToolBar QComboBox {
    background: #ffffff;
    color: #1e1a16;
    padding: 4px;
    border-radius: 3px;
}
QPushButton {
    background: #1d3557;
    color: #ffffff;
    border: 0;
    border-radius: 4px;
    padding: 6px 12px;
}
QPushButton:hover { background: #274772; }
QPushButton:disabled { background: #9aa4b2; }
QPushButton#quiet {
    background: #efeae1;
    color: #1e1a16;
    border: 1px solid #c9c1b4;
}
QLineEdit, QSpinBox, QComboBox, QTableWidget, QListWidget, QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #d5cec2;
    border-radius: 3px;
    padding: 3px;
}
QGroupBox {
    border: 1px solid #d5cec2;
    border-radius: 6px;
    margin-top: 12px;
    padding: 8px;
    background: #fffdf8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QHeaderView::section {
    background: #efeae1;
    border: 0;
    padding: 4px;
}
QStatusBar { background: #efeae1; }
QLabel#disclaimer {
    background: #fff4d6;
    border: 1px solid #e2c98a;
    padding: 8px;
}
QLabel#pass {
    color: #0f6b3c;
    font-size: 22px;
    font-weight: 700;
}
QLabel#fail {
    color: #9b2c2c;
    font-size: 22px;
    font-weight: 700;
}
"""

DISCLAIMER = (
    "このソフトは無保証です。墨消しや仮名への置換の見落とし、OCRの誤認識について、"
    "作者は責任を負いません。出力したPDFは、検証に合格しても、必ずご自身の目で確認してください。"
)
