from __future__ import annotations

import queue
from pathlib import Path

from PySide6.QtCore import QThread, Signal


class OcrWorker(QThread):
    recognized = Signal(int, object)
    failed = Signal(str)

    def __init__(self, model_dir: Path) -> None:
        super().__init__()
        self.model_dir = model_dir
        self._queue: queue.Queue = queue.Queue()

    def submit(self, index: int, image, zoom: float) -> None:
        self._queue.put(("page", index, image, zoom))

    def stop(self) -> None:
        self._queue.put(("stop",))

    def run(self) -> None:
        try:
            from ekisui_pdf.core.ocr import create_engine, recognize_image

            engine = create_engine(self.model_dir)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        while True:
            item = self._queue.get()
            if item[0] == "stop":
                return
            _, index, image, zoom = item
            try:
                lines = recognize_image(engine, image, page_index=index, zoom=zoom)
            except Exception as exc:
                self.failed.emit(str(exc))
                return
            self.recognized.emit(index, lines)
