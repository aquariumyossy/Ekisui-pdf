"""The OCR runtime must not open a TCP connection."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_ocr_load_makes_no_tcp_connection() -> None:
    script = textwrap.dedent(
        """
        import socket
        from ekisui.netguard import NetworkBlocked, install

        install()
        try:
            socket.create_connection(("203.0.113.1", 9), timeout=1)
        except NetworkBlocked:
            pass
        else:
            raise SystemExit("guard did not block create_connection")

        import numpy as np
        from ekisui.pdf.ocr_engine import PpOcrV5

        engine = PpOcrV5()
        image = np.full((80, 240, 3), 255, dtype=np.uint8)
        engine.read(image)

        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QLabel

        app = QApplication([])
        label = QLabel("開く")
        label.show()
        app.processEvents()
        print("ok")
        """
    )
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "ok" in result.stdout
