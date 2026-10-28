"""Stop a test that never returns.

A Python alarm fires only when the interpreter next runs. It does not
interrupt a Qt menu that has grabbed the keyboard and never returns.
Handle tests therefore avoid QMenu.exec. The alarm still stops a test
that is stuck in Python. Windows has no SIGALRM.
"""

import signal
import sys

import pytest

_LIMIT_SECONDS = 120


@pytest.fixture(autouse=True)
def fail_hung_test():
    if sys.platform == "win32" or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _timed_out(_signum, _frame):
        raise TimeoutError(f"test exceeded {_LIMIT_SECONDS}s")

    previous = signal.signal(signal.SIGALRM, _timed_out)
    signal.alarm(_LIMIT_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
