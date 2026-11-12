import asyncio

from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider

from kanboard_mcp.auth import AllowlistGitHubProvider, BearerTokenVerifier


def test_bearer_verifier():
    v = BearerTokenVerifier("s" * 40)
    assert asyncio.run(v.verify_token("s" * 40)) is not None
    assert asyncio.run(v.verify_token("wrong")) is None


def test_github_allowlist(monkeypatch, tmp_path):
    monkeypatch.setenv("FASTMCP_HOME", str(tmp_path))
    provider = AllowlistGitHubProvider(
        client_id="id",
        client_secret="secret",
        base_url="https://mcp.example.com",
        allowed_users=frozenset({"b-ak"}),
    )

    async def fake_load(self, token):
        return AccessToken(token=token, client_id="1", scopes=[], claims={"login": token})

    monkeypatch.setattr(GitHubProvider, "load_access_token", fake_load)
    assert asyncio.run(provider.load_access_token("B-AK")) is not None
    assert asyncio.run(provider.load_access_token("someone-else")) is None
