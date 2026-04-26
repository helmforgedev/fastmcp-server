import asyncio
import time

import jwt
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from authz import (
    AuthorizationDenied,
    HttpAuthMiddleware,
    authorize_http_request,
    build_auth_provider,
    default_scopes,
    enforce_no_auth_policy,
    env_flag,
    is_production_env,
    redact_secrets,
    validate_tool_policy,
)


class FakeComponent:
    def __init__(self, tags=None, annotations=None):
        self.tags = set(tags or [])
        self.annotations = annotations or {}


def make_request(token: str | None = None) -> Request:
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_default_bearer_scopes_are_empty_until_configured(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TYPE", "bearer")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")

    assert default_scopes() == []


def test_no_auth_is_blocked_in_production(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TYPE", "none")
    monkeypatch.setenv("MCP_ENV", "production")

    with pytest.raises(RuntimeError, match="MCP_AUTH_TYPE=none"):
        enforce_no_auth_policy()


def test_no_auth_can_be_explicitly_allowed_in_production(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TYPE", "none")
    monkeypatch.setenv("MCP_ENV", "production")
    monkeypatch.setenv("MCP_ALLOW_NO_AUTH", "true")

    enforce_no_auth_policy()


def test_unknown_auth_type_is_blocked_in_production(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TYPE", "surprise")
    monkeypatch.setenv("MCP_ENV", "production")

    with pytest.raises(RuntimeError, match="Unknown auth type"):
        build_auth_provider()


def test_bearer_without_token_is_blocked_in_production(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TYPE", "bearer")
    monkeypatch.setenv("MCP_ENV", "production")
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN"):
        build_auth_provider()


def test_multi_auth_without_valid_provider_is_blocked_in_production(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TYPE", "multi")
    monkeypatch.setenv("MCP_AUTH_PROVIDERS", "unknown")
    monkeypatch.setenv("MCP_ENV", "production")

    with pytest.raises(RuntimeError, match="no valid providers"):
        build_auth_provider()


def test_bearer_http_auth_accepts_valid_token_and_scope(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TYPE", "bearer")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")

    allowed, client_id, scopes = asyncio.run(
        authorize_http_request(make_request("secret-token"))
    )

    assert allowed is True
    assert client_id == "bearer-user"
    assert scopes == []


def test_bearer_http_auth_ignores_scopes(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TYPE", "bearer")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")

    allowed, _, scopes = asyncio.run(
        authorize_http_request(make_request("secret-token"))
    )

    assert allowed is True
    assert scopes == []


def test_jwt_http_auth_accepts_valid_token(monkeypatch):
    secret = "jwt-secret"
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "agent-1",
            "client_id": "agent-1",
            "scope": "github:read helmforge:validate",
            "iat": now,
            "exp": now + 300,
        },
        secret,
        algorithm="HS256",
    )
    monkeypatch.setenv("MCP_AUTH_TYPE", "jwt")
    monkeypatch.setenv("MCP_AUTH_JWT_PUBLIC_KEY", secret)
    monkeypatch.setenv("MCP_AUTH_JWT_ALGORITHM", "HS256")

    allowed, client_id, scopes = asyncio.run(
        authorize_http_request(make_request(token))
    )

    assert allowed is True
    assert client_id == "agent-1"
    assert scopes == []


def test_multi_auth_builds_real_multi_provider(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TYPE", "multi")
    monkeypatch.setenv("MCP_AUTH_PROVIDERS", "bearer,jwt")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")
    monkeypatch.setenv("MCP_AUTH_JWT_PUBLIC_KEY", "jwt-secret")
    monkeypatch.setenv("MCP_AUTH_JWT_ALGORITHM", "HS256")

    provider = build_auth_provider()

    assert provider is not None
    assert provider.__class__.__name__ == "MultiAuth"
    assert len(provider.verifiers) == 2


def test_redact_secrets_removes_tokens_from_strings(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")

    value = redact_secrets(
        "Authorization: Bearer secret-token url=https://x-access-token:ghp_secret@example.com/repo.git"
    )

    assert "secret-token" not in value
    assert "ghp_secret" not in value
    assert "[REDACTED]" in value


def test_runtime_does_not_apply_project_specific_github_policy():
    component = FakeComponent(tags={"github", "write"})

    validate_tool_policy(
        "github_commit_files",
        component,
        {"owner": "any-org", "repo": "any-repo", "branch": "main"},
    )


def test_destructive_tool_requires_human_approval():
    component = FakeComponent(
        tags={"admin"},
        annotations={"destructiveHint": True},
    )

    with pytest.raises(AuthorizationDenied, match="human_approved"):
        validate_tool_policy("run_gh", component, {"args": "repo delete"})

    args = {
        "args": "pr list",
        "human_approved": True,
        "approval_reason": "operator approved",
    }
    validate_tool_policy("run_gh", component, args)
    assert "human_approved" not in args
    assert "approval_reason" not in args


def test_http_auth_middleware_protects_ui_like_routes(monkeypatch):
    """Static UI and mounted HTTP routes can use the same auth policy."""
    monkeypatch.setenv("MCP_AUTH_TYPE", "bearer")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")

    async def ui(_request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/ui", ui)])
    app.add_middleware(HttpAuthMiddleware, protected_prefixes=["/ui"])
    client = TestClient(app)

    assert client.get("/ui").status_code == 401
    response = client.get("/ui", headers={"Authorization": "Bearer secret-token"})
    assert response.status_code == 200
    assert response.text == "ok"


def test_production_defaults_enable_error_masking(monkeypatch):
    """Production-like environments still enable error masking by default."""
    monkeypatch.setenv("MCP_ENV", "production")

    assert is_production_env()
    assert env_flag("MCP_MASK_ERROR_DETAILS", default=is_production_env())
