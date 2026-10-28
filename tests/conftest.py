"""Stop a test that never returns.

Offscreen Qt can block forever inside a menu that tries to grab the keyboard.
The alarm fails that test instead of leaving the run stuck. Windows has no
SIGALRM; the guard is the Unix CI and local runs.
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
