# 第三者のライセンス

易水PDF（ekisui-pdf）本体は GNU Affero General Public License v3.0（AGPL-3.0）です。
全文はリポジトリ直下の `LICENSE` と、インストール先の `LICENSE` です。

バイナリには次のソフトウェアが、改変せず同梱されます。各ライセンスの全文は `licenses/` にあります。

| もの | ライセンス | 著作 |
| --- | --- | --- |
| PyMuPDF | AGPL-3.0（Artifex の商用ライセンスとのデュアル） | Artifex Software, Inc. |
| Qt / PySide6 | LGPL-3.0 | The Qt Company、Riverbank Computing |
| GNU GPL-3.0 | LGPL-3.0 が取り込む本文 | Free Software Foundation |
| PaddleOCR と PP-OCRv5 モデル | Apache-2.0 | PaddlePaddle Authors |
| RapidOCR | Apache-2.0 | RapidAI |
| ONNX Runtime | MIT | Microsoft Corporation |
| OpenCV（opencv-python-headless） | Apache-2.0 | OpenCV team |
| NumPy | BSD-3-Clause | NumPy Developers |
| Pillow、Shapely、pyclipper、PyYAML、omegaconf、requests、tqdm、colorlog など | 各パッケージの表記に従う（MIT / BSD / Apache-2.0 が中心） | 各作者 |

PP-OCRv5 の ONNX ファイルは、PaddleOCR のモデルを RapidAI が ONNX に変換して配布しているものです（RapidOCR モデル `v3.10.0`）。検出は `ch_PP-OCRv5_det_mobile`、認識は `ch_PP-OCRv5_rec_mobile` です。認識モデルは簡体字・繁体字・英語・日本語を一つのモデルで扱います。

Qt / PySide6 は LGPL-3.0 です。このアプリは Qt を改変せず、PySide6 の共有ライブラリとして同梱しています。対応するソースは Qt プロジェクトと PySide6 の配布元にあります。LGPL-3.0 が参照する GPL-3.0 の全文も `licenses/GPL-3.0.txt` に入れています。

ONNX Runtime、Pillow などの MIT 文面は `licenses/MIT.txt`、NumPy の BSD 文面は `licenses/BSD-3-Clause.txt` です。著作権表示は各プロジェクトのものです。

ソースコードの所在: https://github.com/aquariumyossy/Ekisui-pdf
