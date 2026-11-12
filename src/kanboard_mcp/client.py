"""Minimal Kanboard JSON-RPC client."""

from __future__ import annotations

import itertools
import logging
from typing import Any

import httpx

from .config import KanboardConfig

logger = logging.getLogger(__name__)


class KanboardError(RuntimeError):
    """Raised for transport, authentication or JSON-RPC errors."""


class KanboardClient:
    """Thin wrapper around Kanboard's JSON-RPC API.

    Works with either the application API (username ``jsonrpc`` + global token)
    or the user API (your username + personal access token).
    """

    def __init__(self, config: KanboardConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        self._ids = itertools.count(1)
        self._http = httpx.Client(
            auth=(config.username, config.token),
            timeout=config.timeout,
            verify=config.verify_ssl,
            transport=transport,
            headers={"User-Agent": "kanboard-mcp-server"},
        )

    @property
    def is_app_api(self) -> bool:
        return self.config.username == "jsonrpc"

    def call(self, method: str, **params: Any) -> Any:
        payload = {"jsonrpc": "2.0", "method": method, "id": next(self._ids), "params": params}
        logger.debug("Kanboard RPC %s", method)
        try:
            response = self._http.post(self.config.url, json=payload)
        except httpx.HTTPError as exc:
            raise KanboardError(f"Cannot reach Kanboard at {self.config.url}: {exc}") from exc

        if response.status_code in (401, 403):
            raise KanboardError(
                "Kanboard rejected the credentials "
                f"(HTTP {response.status_code}). Check KANBOARD_USERNAME/KANBOARD_API_TOKEN."
            )
        if response.status_code >= 400:
            raise KanboardError(f"Kanboard returned HTTP {response.status_code} for {method}")
        try:
            data = response.json()
        except ValueError as exc:
            raise KanboardError(
                f"Kanboard returned a non-JSON response for {method}. "
                "Is KANBOARD_URL pointing at your Kanboard instance?"
            ) from exc

        error = data.get("error")
        if error:
            message = error.get("message", error) if isinstance(error, dict) else error
            raise KanboardError(f"{method} failed: {message}")
        return data.get("result")

    def close(self) -> None:
        self._http.close()
