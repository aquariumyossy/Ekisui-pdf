class EkisuiError(Exception):
    """Expected failure the GUI can show as-is."""


class EncryptedPdf(EkisuiError):
    def __init__(self) -> None:
        super().__init__("このPDFは暗号化されているため開けません")


class WordConvertError(EkisuiError):
    """Microsoft Word could not turn a .doc or .docx into a PDF."""


class ModelMissing(EkisuiError):
    def __init__(self, directory: str) -> None:
        super().__init__(f"OCRモデルが見つかりません: {directory}")
