from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from kanboard_mcp.client import KanboardClient
from kanboard_mcp.config import KanboardConfig


class FakeKanboard:
    """In-memory stand-in for Kanboard's JSON-RPC endpoint."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.status_code = 200

    def on(self, method: str, result: Any = None, fn: Callable[..., Any] | None = None) -> None:
        self.handlers[method] = fn or (lambda **_: result)

    def methods(self) -> list[str]:
        return [m for m, _ in self.calls]

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.status_code != 200:
            return httpx.Response(self.status_code)
        body = json.loads(request.content)
        method, params = body["method"], body.get("params") or {}
        self.calls.append((method, params))
        if method not in self.handlers:
            error = {"code": -32601, "message": "Method not found"}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": error})
        result = self.handlers[method](**params)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})


@pytest.fixture
def fake() -> FakeKanboard:
    return FakeKanboard()


def make_client(fake: FakeKanboard, username: str = "alice") -> KanboardClient:
    cfg = KanboardConfig(url="http://kb.test/jsonrpc.php", username=username, token="t")
    return KanboardClient(cfg, transport=httpx.MockTransport(fake.handle))


@pytest.fixture
def client(fake: FakeKanboard) -> KanboardClient:
    return make_client(fake)
