from __future__ import annotations

import os
import socket

_ORIGINALS: dict[str, object] = {}
_INSTALLED = False


class NetworkDisabled(RuntimeError):
    pass


def _message(target: object) -> str:
    return f"ekisui-pdf はネットワークへ接続しません（{target}）。事件記録は外部へ送りません。"


def install_network_guard() -> None:
    """Python からの外向き接続と requests を拒否する。モデルの自動取得を止める最後の段。"""
    global _INSTALLED
    if _INSTALLED:
        return
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    _ORIGINALS["connect"] = socket.socket.connect
    _ORIGINALS["connect_ex"] = socket.socket.connect_ex
    _ORIGINALS["sendto"] = socket.socket.sendto
    _ORIGINALS["create_connection"] = socket.create_connection

    def connect(self, address):
        raise NetworkDisabled(_message(address))

    def connect_ex(self, address):
        raise NetworkDisabled(_message(address))

    def sendto(self, data, *args):
        raise NetworkDisabled("ekisui-pdf はネットワークへ送信しません。")

    def create_connection(address, *args, **kwargs):
        raise NetworkDisabled(_message(address))

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
    socket.create_connection = create_connection

    try:
        import requests

        _ORIGINALS["request"] = requests.sessions.Session.request

        def request(self, method, url, **kwargs):
            raise NetworkDisabled(_message(url))

        requests.sessions.Session.request = request
    except Exception:
        _ORIGINALS["request"] = None
    _INSTALLED = True


def uninstall_network_guard() -> None:
    global _INSTALLED
    if not _INSTALLED:
        return
    socket.socket.connect = _ORIGINALS["connect"]
    socket.socket.connect_ex = _ORIGINALS["connect_ex"]
    socket.socket.sendto = _ORIGINALS["sendto"]
    socket.create_connection = _ORIGINALS["create_connection"]
    if _ORIGINALS.get("request") is not None:
        import requests

        requests.sessions.Session.request = _ORIGINALS["request"]
    _INSTALLED = False
    _ORIGINALS.clear()
