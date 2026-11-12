"""Authentication providers for the HTTP transport."""

from __future__ import annotations

import hmac
import logging

from fastmcp.server.auth import AccessToken, AuthProvider, TokenVerifier
from fastmcp.server.auth.providers.github import GitHubProvider

from .config import ServerConfig

logger = logging.getLogger(__name__)


class BearerTokenVerifier(TokenVerifier):
    """Accepts a single shared secret sent as ``Authorization: Bearer <token>``."""

    def __init__(self, token: str):
        super().__init__()
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token.encode(), self._token.encode()):
            return None
        return AccessToken(token=token, client_id="bearer", scopes=[], expires_at=None)


class AllowlistGitHubProvider(GitHubProvider):
    """GitHub OAuth that only admits an explicit list of GitHub usernames.

    Without an allowlist, any GitHub account could log in and edit your boards.
    """

    def __init__(self, *, allowed_users: frozenset[str], **kwargs):
        super().__init__(**kwargs)
        self._allowed_users = allowed_users

    async def load_access_token(self, token: str) -> AccessToken | None:
        access = await super().load_access_token(token)
        if access is None:
            return None
        login = str((access.claims or {}).get("login") or "").lower()
        if login not in self._allowed_users:
            logger.warning("Rejected GitHub user %r (not in MCP_ALLOWED_GITHUB_USERS)", login)
            return None
        return access


def build_auth(cfg: ServerConfig) -> AuthProvider | None:
    if cfg.transport != "http" or cfg.auth == "none":
        return None
    if cfg.auth == "bearer":
        return BearerTokenVerifier(cfg.bearer_token)
    return AllowlistGitHubProvider(
        client_id=cfg.github_client_id,
        client_secret=cfg.github_client_secret,
        base_url=cfg.base_url,
        allowed_users=cfg.allowed_github_users,
        jwt_signing_key=cfg.jwt_signing_key or None,
    )
