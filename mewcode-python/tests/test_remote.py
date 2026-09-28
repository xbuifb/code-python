"""R1 remote 鉴权单测：验证 /cost 等命令的传输层门禁。

覆盖：
- 无 token 访问 / 与 /ws → 401（拒绝握手）
- 错误 token → 401
- 正确 token → / 返回 200 HTML、/ws 返回 None（放行 WS 升级）
- 默认绑定 127.0.0.1（仅本机可连）
"""

from __future__ import annotations

import websockets
from websockets.http11 import Request

from mewcode.remote import RemoteServer


def _make_server() -> RemoteServer:
    # providers 为必填位置参数；构造不触发 _init_agent（在 run() 才跑），
    # 故可安全用于鉴权层的单测。
    return RemoteServer(providers=[])


def _req(path: str) -> Request:
    return Request(path=path, headers=websockets.Headers())


class TestRemoteAuth:
    def setup_method(self) -> None:
        self.server = _make_server()
        self.token = self.server._auth_token

    # --- /ws 握手校验（控制通道，最关键）---

    def test_ws_no_token_rejected(self) -> None:
        # /ws 不带 token → 拒绝 WS 升级，握手不完成
        resp = self.server._process_http_request(None, _req("/ws"))
        assert resp is not None
        assert resp.status_code == 401

    def test_ws_wrong_token_rejected(self) -> None:
        resp = self.server._process_http_request(None, _req("/ws?token=wrong-value"))
        assert resp is not None
        assert resp.status_code == 401

    def test_ws_correct_token_allows_upgrade(self) -> None:
        # 正确 token → 返回 None，表示继续 WebSocket 升级流程
        resp = self.server._process_http_request(
            None, _req(f"/ws?token={self.token}")
        )
        assert resp is None

    # --- / 页面鉴权（前端 HTML，纵深防御）---

    def test_index_no_token_rejected(self) -> None:
        resp = self.server._process_http_request(None, _req("/"))
        assert resp is not None
        assert resp.status_code == 401

    def test_index_correct_token_serves_html(self) -> None:
        resp = self.server._process_http_request(
            None, _req(f"/?token={self.token}")
        )
        assert resp is not None
        assert resp.status_code == 200
        assert b"<html" in resp.body.lower() or b"<!doctype" in resp.body.lower()

    # --- 其他路径 ---

    def test_unknown_path_returns_404_even_with_token(self) -> None:
        resp = self.server._process_http_request(
            None, _req(f"/admin?token={self.token}")
        )
        assert resp is not None
        assert resp.status_code == 404

    # --- 默认绑定地址（安全默认：仅本机）---

    def test_default_bind_is_localhost(self) -> None:
        # 不得默认绑 0.0.0.0（暴露到网络面）
        assert self.server.addr == "127.0.0.1"

    # --- _check_token 常数时间比较直接验证 ---

    def test_check_token_empty_query(self) -> None:
        assert self.server._check_token("/ws") is False

    def test_check_token_no_token_param(self) -> None:
        assert self.server._check_token("/ws?foo=bar") is False

    def test_check_token_matches(self) -> None:
        assert self.server._check_token(f"/ws?token={self.token}") is True
