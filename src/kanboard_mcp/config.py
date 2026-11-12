"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

_TRUE = {"1", "true", "yes", "on"}
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class ConfigError(ValueError):
    """Raised when the environment is misconfigured."""


def _env(name: str, default: str = "", *aliases: str) -> str:
    for key in (name, *aliases):
        value = os.getenv(key)
        if value is not None and value.strip():
            return value.strip()
    return default


def _bool(name: str, default: bool) -> bool:
    raw = _env(name)
    return raw.lower() in _TRUE if raw else default


def normalize_jsonrpc_url(url: str) -> str:
    """Accept either the Kanboard base URL or the full jsonrpc.php URL."""
    url = url.strip().rstrip("/")
    if not url:
        raise ConfigError("KANBOARD_URL is required")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    if not url.endswith("jsonrpc.php"):
        url += "/jsonrpc.php"
    return url


@dataclass(frozen=True)
class KanboardConfig:
    url: str
    username: str
    token: str
    verify_ssl: bool = True
    timeout: float = 20.0
    default_user_id: int | None = None

    @classmethod
    def from_env(cls) -> KanboardConfig:
        token = _env("KANBOARD_API_TOKEN")
        if not token:
            raise ConfigError("KANBOARD_API_TOKEN is required")
        default_user = _env("KANBOARD_DEFAULT_USER_ID")
        return cls(
            url=normalize_jsonrpc_url(_env("KANBOARD_URL")),
            # KANBOARD_API_USER is accepted for backwards compatibility.
            username=_env("KANBOARD_USERNAME", "jsonrpc", "KANBOARD_API_USER"),
            token=token,
            verify_ssl=_bool("KANBOARD_VERIFY_SSL", True),
            timeout=float(_env("KANBOARD_TIMEOUT", "20")),
            default_user_id=int(default_user) if default_user else None,
        )


@dataclass(frozen=True)
class ServerConfig:
    transport: str = "stdio"  # stdio | http
    host: str = "127.0.0.1"
    port: int = 8000
    auth: str = "none"  # none | bearer | github
    bearer_token: str = ""
    base_url: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    allowed_github_users: frozenset[str] = field(default_factory=frozenset)
    jwt_signing_key: str = ""
    allow_unauthenticated: bool = False

    @classmethod
    def from_env(cls) -> ServerConfig:
        users = _env("MCP_ALLOWED_GITHUB_USERS")
        cfg = cls(
            transport=_env("MCP_TRANSPORT", "stdio").lower(),
            host=_env("MCP_HOST", "127.0.0.1"),
            port=int(_env("MCP_PORT", "8000")),
            auth=_env("MCP_AUTH", "none").lower(),
            bearer_token=_env("MCP_BEARER_TOKEN"),
            base_url=_env("MCP_BASE_URL").rstrip("/"),
            github_client_id=_env("GITHUB_CLIENT_ID"),
            github_client_secret=_env("GITHUB_CLIENT_SECRET"),
            allowed_github_users=frozenset(
                u.strip().lower() for u in users.split(",") if u.strip()
            ),
            jwt_signing_key=_env("MCP_JWT_SIGNING_KEY"),
            allow_unauthenticated=_bool("MCP_ALLOW_UNAUTHENTICATED", False),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.transport not in {"stdio", "http"}:
            raise ConfigError("MCP_TRANSPORT must be 'stdio' or 'http'")
        if self.auth not in {"none", "bearer", "github"}:
            raise ConfigError("MCP_AUTH must be 'none', 'bearer' or 'github'")
        if self.transport != "http":
            return
        if self.auth == "none" and self.host not in _LOOPBACK and not self.allow_unauthenticated:
            raise ConfigError(
                f"Refusing to serve HTTP on {self.host} without authentication. "
                "Set MCP_AUTH=github or MCP_AUTH=bearer "
                "(or MCP_ALLOW_UNAUTHENTICATED=true if a proxy handles auth)."
            )
        if self.auth == "bearer" and len(self.bearer_token) < 32:
            raise ConfigError("MCP_BEARER_TOKEN must be at least 32 characters")
        if self.auth == "github":
            missing = [
                name
                for name, value in [
                    ("MCP_BASE_URL", self.base_url),
                    ("GITHUB_CLIENT_ID", self.github_client_id),
                    ("GITHUB_CLIENT_SECRET", self.github_client_secret),
                    ("MCP_ALLOWED_GITHUB_USERS", self.allowed_github_users),
                ]
                if not value
            ]
            if missing:
                raise ConfigError(f"MCP_AUTH=github requires: {', '.join(missing)}")
