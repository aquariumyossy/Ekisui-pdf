"""Refuse outbound TCP connections. Local file IO is untouched."""

from __future__ import annotations

import socket

_INSTALLED = False


class NetworkBlocked(RuntimeError):
    pass


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    def _refuse(address):
        raise NetworkBlocked(f"ekisui-pdf は通信しません: {address}")

    def _is_tcp(address) -> bool:
        return isinstance(address, tuple)

    class Guard(socket.socket):
        def connect(self, address):  # type: ignore[override]
            if _is_tcp(address):
                _refuse(address)
            return super().connect(address)

        def connect_ex(self, address):  # type: ignore[override]
            if _is_tcp(address):
                _refuse(address)
            return super().connect_ex(address)

    socket.socket = Guard  # type: ignore[misc]

    def _create_connection(*_args, **_kwargs):
        _refuse(_args[0] if _args else "?")

    socket.create_connection = _create_connection  # type: ignore[assignment]
    _INSTALLED = True
