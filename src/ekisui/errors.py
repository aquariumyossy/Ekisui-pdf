class EkisuiError(Exception):
    """Expected failure the GUI can show as-is."""


class EncryptedPdf(EkisuiError):
    def __init__(self) -> None:
        super().__init__("このPDFは暗号化されているため開けません")


class ModelMissing(EkisuiError):
    def __init__(self, directory: str) -> None:
        super().__init__(f"OCRモデルが見つかりません: {directory}")
