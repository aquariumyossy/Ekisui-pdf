QSS = """
* { font-size: 14px; }
QMainWindow, QDialog, QWidget { color: #1b1b1b; }
QToolTip {
  background: #2b2b2b; color: #ffffff; border: none;
  padding: 6px 10px; font-size: 13px;
}
#toolbar { background: #fbfbfb; border-bottom: 1px solid #e0e0e0; }
QPushButton[class="tb"] {
  background: transparent; border: 1px solid transparent; border-radius: 6px;
  padding: 4px 8px; min-width: 64px; min-height: 48px; font-size: 13px;
}
QPushButton[class="tb"]:hover { background: #ececec; }
QPushButton[class="tb"]:checked { background: #e6f0fa; border-color: #b9d3ee; color: #0f6cbd; }
QPushButton[class="tb"]:disabled { color: #a8a8a8; background: transparent; }
QPushButton[class="tbPrimary"] {
  background: #0f6cbd; color: #ffffff; border: 1px solid #0f6cbd; border-radius: 6px;
  padding: 4px 8px; min-width: 64px; min-height: 48px; font-size: 13px;
}
QPushButton[class="tbPrimary"]:hover { background: #115ea3; }
QPushButton[class="tbPrimary"]:disabled { background: #d0d0d0; color: #f7f7f7; border-color: #d0d0d0; }
QPushButton[class="dd"] {
  background: transparent; border: 1px solid transparent; border-radius: 6px;
  min-width: 22px; max-width: 28px; min-height: 48px; font-size: 13px; padding: 0;
}
QPushButton[class="dd"]:hover, QPushButton[class="dd"]:checked { background: #ececec; }
#offline {
  color: #2f6b31; background: #e9f4ea; border-radius: 12px; padding: 4px 10px; font-size: 13px;
}
#thumbs { background: #fbfbfb; border-right: 1px solid #e0e0e0; }
#side { background: #fbfbfb; border-left: 1px solid #e0e0e0; }
#vbar { background: #f3f3f3; border-bottom: 1px solid #e0e0e0; }
QPushButton[class="ib"] {
  background: #ffffff; border: 1px solid #e0e0e0; border-radius: 5px;
  min-height: 30px; padding: 0 8px; font-size: 13px;
}
QPushButton[class="ib"]:hover { background: #f0f0f0; }
QPushButton[class="ib"]:checked { background: #e6f0fa; border-color: #b9d3ee; color: #0f6cbd; }
#canvasHost { background: #d9dbde; }
QSplitter::handle { background: #e6e6e6; }
QSplitter::handle:hover { background: #0f6cbd; }
QPushButton#info {
  min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px;
  border: 1px solid #6a6a6a; border-radius: 11px; background: #ffffff;
  font-size: 12px; font-weight: 700; padding: 0;
}
QPushButton#info:hover { background: #e6f0fa; border-color: #0f6cbd; color: #0f6cbd; }
#drop { background: #f7f7f8; border: 2px dashed #b4b8be; border-radius: 12px; }
QPushButton[class="btn"] {
  background: #ffffff; border: 1px solid #c8c8c8; border-radius: 5px;
  min-height: 34px; padding: 0 14px; font-size: 14px;
}
QPushButton[class="btn"]:hover { background: #f2f2f2; }
QPushButton[class="primary"] {
  background: #0f6cbd; color: #ffffff; border: 1px solid #0f6cbd; border-radius: 5px;
  min-height: 34px; padding: 0 14px; font-size: 14px;
}
QPushButton[class="primary"]:hover { background: #115ea3; }
QPushButton[class="danger"] {
  background: #c42b1c; color: #ffffff; border: 1px solid #c42b1c; border-radius: 5px;
  min-height: 34px; padding: 0 14px; font-size: 14px;
}
QPushButton[class="chip"] {
  background: #ffffff; border: 1px solid #d0d0d0; border-radius: 14px;
  min-height: 28px; padding: 0 10px; font-size: 13px;
}
QPushButton[class="chip"]:checked { background: #e6f0fa; border-color: #0f6cbd; color: #0f6cbd; }
QPushButton[class="tab"] {
  background: transparent; border: none; border-bottom: 3px solid transparent;
  padding: 8px 12px; color: #5c5c5c; font-size: 14px;
}
QPushButton[class="tab"]:checked { color: #1b1b1b; font-weight: 600; border-bottom: 3px solid #0f6cbd; }
QLineEdit, QSpinBox {
  background: #ffffff; border: 1px solid #c8c8c8; border-radius: 5px;
  min-height: 32px; padding: 0 8px; font-size: 14px;
}
#thumbBtn { background: transparent; border: none; color: #5c5c5c; font-size: 13px; }
QPushButton#thumbBtn:checked { color: #0f6cbd; }
#shade { background: rgba(20, 20, 20, 150); }
#dialog { background: #ffffff; border: 1px solid #d0d0d0; border-radius: 10px; }
#pop { background: #ffffff; border: 1px solid #d6d6d6; border-radius: 8px; }
#card { background: #ffffff; border: 1px solid #d6d6d6; border-radius: 8px; }
QCheckBox { font-size: 14px; spacing: 8px; }
QStatusBar { background: #fbfbfb; border-top: 1px solid #e0e0e0; font-size: 13px; }
QLabel[class="sub"] { color: #5c5c5c; font-size: 13px; }
QLabel[class="exact"] { background: #e7f5ea; color: #1e6b34; border-radius: 4px; padding: 2px 6px; font-size: 13px; }
QLabel[class="fuzzy"] { background: #fff1e6; color: #9a4d12; border-radius: 4px; padding: 2px 6px; font-size: 13px; }
QLabel[class="pseudo"] { color: #0f6cbd; font-size: 14px; }
QLabel[class="warn"] { color: #8f1f14; font-size: 14px; }
QLabel[class="okbig"] { color: #1b1b1b; font-size: 16px; font-weight: 600; }
QFrame[class="row"] { background: transparent; border-bottom: 1px solid #ececec; }
QPushButton[class="seg"] {
  background: #f3f3f3; border: 1px solid #d0d0d0; min-height: 26px; padding: 0 8px; font-size: 13px;
}
QPushButton[class="seg"]:checked { background: #1b1b1b; color: #ffffff; border-color: #1b1b1b; }
QPushButton[class="segRep"] {
  background: #f3f3f3; border: 1px solid #d0d0d0; min-height: 26px; padding: 0 8px; font-size: 13px;
}
QPushButton[class="segRep"]:checked { background: #2f7d32; color: #ffffff; border-color: #2f7d32; }
QFrame[class="var"] { background: #f4f4f4; border: 1px solid #d0d0d0; border-radius: 4px; }
QFrame[class="sug"] { background: #ffffff; border: 1px dashed #c47a3a; border-radius: 4px; }
QLabel[class="badge"] {
  background: #d4a000; color: #ffffff; border-radius: 9px; padding: 0 5px; font-size: 13px;
}
QLabel[class="skew"] { color: #0f6cbd; font-size: 13px; }
"""
