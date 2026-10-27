from __future__ import annotations


class EkisuiError(Exception):
    """利用者が直せる失敗。"""


class SameFileError(EkisuiError):
    pass


class EncryptedPdfError(EkisuiError):
    pass


class ModelNotFoundError(EkisuiError):
    pass


class PseudonymMissing(EkisuiError):
    def __init__(self, labels: list[str]):
        self.labels = labels
        shown = "、".join(labels[:8]) or "(文字なし)"
        super().__init__(f"仮名が未設定の選択があります: {shown}")
