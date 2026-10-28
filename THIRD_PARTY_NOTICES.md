# 第三者のソフトウェア

ekisui-pdf 本体は GNU Affero General Public License v3.0 です。全文は `LICENSE` です。
PyMuPDF（AGPL）を使っているため、このアプリ全体を AGPL-3.0 で配布します。

インストーラと同じフォルダに、このファイルと `LICENSE` が入ります。

## PyMuPDF / MuPDF

- 用途: PDF の読み書き、墨消し（`add_redact_annot` と `apply_redactions`）、メタデータの削除
- ライセンス: GNU Affero General Public License v3.0
- https://pymupdf.readthedocs.io/
- MuPDF: https://mupdf.com/

## PaddleOCR PP-OCRv5 モデル

- ファイル: `ch_PP-OCRv5_det_mobile.onnx`、`ch_PP-OCRv5_rec_mobile.onnx`、`ch_PP-LCNet_x0_25_textline_ori.onnx`、`ppocrv5_dict.txt`
- 認識モデルは簡体字・繁体字・英語・日本語を含む学習済み重みです
- 入手元: RapidAI/RapidOCR v3.10.0（ModelScope）。ハッシュは `models/SHA256SUMS`
- ライセンス: Apache License 2.0（PaddleOCR のモデル配布に従う）
- https://github.com/PaddlePaddle/PaddleOCR
- https://www.modelscope.cn/models/RapidAI/RapidOCR

このアプリは実行時にモデルをダウンロードしません。

## ONNX Runtime

- 用途: 上記モデルの CPU 実行
- ライセンス: MIT License
- https://github.com/microsoft/onnxruntime

## PySide6 / Qt

- 用途: 画面
- ライセンス: GNU Lesser General Public License v3（Qt）。PySide6 のバインディングは LGPL です
- 改変していない Qt を動的にリンクしています。対応するソースは https://download.qt.io/ から入手できます
- https://www.qt.io/

## OpenCV（opencv-python-headless）

- 用途: 傾き補正と OCR の前処理
- ライセンス: Apache License 2.0
- https://opencv.org/

## NumPy

- ライセンス: BSD 3-Clause
- https://numpy.org/

## Pillow

- 用途: テストとページ画像の保存
- ライセンス: HPND（MIT に近い寛容なライセンス）
- https://python-pillow.org/

## アプリアイコンの字形（Noto CJK）

アイコンの「蕭」は、次のフォントのアウトラインを図形にしたものです。フォントファイル自体は同梱していません。

- 16・24・32・48: Noto Sans CJK JP Bold 2.004
- 64・128・256 と 1024 の明朝マスター: Noto Serif CJK JP
- 著作権: Copyright © 2014-2021 Adobe. Reserved Font Name「Source」
- ライセンス: SIL Open Font License 1.1
- 全文: `assets/icon/OFL-NotoSansCJKJP.txt`、`assets/icon/OFL-NotoSerifCJKJP.txt`
- https://github.com/notofonts/noto-cjk

## 姓の一覧

`src/ekisui/resources/surnames.txt` は、公開されている同姓調査（明治安田生命「全国同姓調査」など）で繰り返し上位に挙がる姓を、事実の列挙としてまとめたものです。特定のデータベースの複製ではありません。表記ゆれ（渡辺/渡邊、斎藤/斉藤など）は別の行にしています。
