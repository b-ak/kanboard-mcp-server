import pytest

from kanboard_mcp.config import ConfigError, KanboardConfig, ServerConfig, normalize_jsonrpc_url


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("http://pi.local", "http://pi.local/jsonrpc.php"),
        ("https://kb.example.com/kanboard/", "https://kb.example.com/kanboard/jsonrpc.php"),
        ("http://localhost:8080/jsonrpc.php", "http://localhost:8080/jsonrpc.php"),
        ("192.168.1.10", "http://192.168.1.10/jsonrpc.php"),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_jsonrpc_url(raw) == expected


def test_kanboard_config_defaults_and_legacy_alias(monkeypatch):
    monkeypatch.setenv("KANBOARD_URL", "http://pi.local")
    monkeypatch.setenv("KANBOARD_API_TOKEN", "secret")
    monkeypatch.delenv("KANBOARD_USERNAME", raising=False)
    monkeypatch.setenv("KANBOARD_API_USER", "bob")
    cfg = KanboardConfig.from_env()
    assert cfg.username == "bob"
    assert cfg.verify_ssl is True


def test_missing_token(monkeypatch):
    monkeypatch.setenv("KANBOARD_URL", "http://pi.local")
    monkeypatch.delenv("KANBOARD_API_TOKEN", raising=False)
    with pytest.raises(ConfigError):
        KanboardConfig.from_env()


def test_http_on_public_interface_requires_auth():
    with pytest.raises(ConfigError, match="without authentication"):
        ServerConfig(transport="http", host="0.0.0.0").validate()
    ServerConfig(transport="http", host="127.0.0.1").validate()
    ServerConfig(transport="http", host="0.0.0.0", allow_unauthenticated=True).validate()


def test_bearer_token_length():
    with pytest.raises(ConfigError):
        ServerConfig(transport="http", auth="bearer", bearer_token="short").validate()


def test_github_requires_allowlist():
    cfg = ServerConfig(
        transport="http",
        auth="github",
        base_url="https://mcp.example.com",
        github_client_id="id",
        github_client_secret="secret",
    )
    with pytest.raises(ConfigError, match="MCP_ALLOWED_GITHUB_USERS"):
        cfg.validate()
