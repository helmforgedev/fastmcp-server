"""Authentication, authorization, and audit helpers for fastmcp-server."""

from __future__ import annotations

import hmac
import logging
import os
import re
import uuid
from collections.abc import Iterable
from typing import Any

from fastmcp.server.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("fastmcp-server.authz")
audit_logger = logging.getLogger("fastmcp-server.audit")

class AuthorizationDenied(PermissionError):
    """Raised when a request or tool call does not satisfy server policy."""


def csv_env(name: str, default: str = "") -> list[str]:
    """Parse a comma-separated environment variable."""
    value = os.environ.get(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def default_scopes() -> list[str]:
    """Return the server's default MCP scopes."""
    return csv_env("MCP_AUTH_SCOPES")


def required_global_scopes() -> list[str]:
    """Return scopes required on every authenticated request."""
    return csv_env("MCP_AUTH_REQUIRED_SCOPES")


def enforce_no_auth_policy() -> None:
    """Fail closed when no auth is enabled outside explicit local/dev usage."""
    auth_type = os.environ.get("MCP_AUTH_TYPE", "none").lower()
    if auth_type != "none":
        return

    env = _deployment_env()
    allow_no_auth = os.environ.get("MCP_ALLOW_NO_AUTH", "false").lower() == "true"
    if env in {"prod", "production", "staging"} and not allow_no_auth:
        raise RuntimeError(
            "MCP_AUTH_TYPE=none is allowed only for local/dev. "
            "Set MCP_AUTH_TYPE=bearer for this environment, or explicitly set "
            "MCP_ALLOW_NO_AUTH=true for a temporary exception."
        )


def build_auth_provider():
    """Build a FastMCP auth provider from environment variables."""
    from fastmcp.server.auth import JWTVerifier, MultiAuth, StaticTokenVerifier

    enforce_no_auth_policy()
    auth_type = os.environ.get("MCP_AUTH_TYPE", "none").lower()

    if auth_type == "none":
        return None
    if auth_type == "bearer":
        return _build_bearer_verifier(StaticTokenVerifier)
    if auth_type == "jwt":
        return _build_jwt_verifier(JWTVerifier)
    if auth_type == "multi":
        verifiers = []
        for provider in csv_env("MCP_AUTH_PROVIDERS"):
            if provider == "bearer":
                verifier = _build_bearer_verifier(StaticTokenVerifier)
            elif provider == "jwt":
                verifier = _build_jwt_verifier(JWTVerifier)
            else:
                logger.warning("Unknown auth provider in multi-auth: %s", provider)
                continue
            if verifier:
                verifiers.append(verifier)

        if not verifiers:
            _auth_config_error("Multi auth enabled but no valid providers configured")
            return None
        return MultiAuth(verifiers=verifiers, required_scopes=required_global_scopes())

    _auth_config_error(f"Unknown auth type '{auth_type}'")
    return None


def is_production_env() -> bool:
    """Return True when the deployment environment is production-like."""
    return _deployment_env() in {"prod", "production", "staging"}


def env_flag(name: str, default: bool = False) -> bool:
    """Read a boolean environment flag."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _deployment_env() -> str:
    return (
        os.environ.get("MCP_ENV")
        or os.environ.get("ENVIRONMENT")
        or os.environ.get("APP_ENV", "dev")
    ).lower()


def _build_bearer_verifier(static_token_verifier_cls):
    token = os.environ.get("MCP_AUTH_TOKEN", "")
    if not token:
        _auth_config_error("Bearer auth enabled but MCP_AUTH_TOKEN not set")
        return None

    client_id = os.environ.get("MCP_AUTH_CLIENT_ID", "bearer-user")
    return static_token_verifier_cls(
        tokens={
            token: {
                "client_id": client_id,
                "sub": client_id,
                "scopes": default_scopes(),
            }
        },
        required_scopes=required_global_scopes(),
    )


def _build_jwt_verifier(jwt_verifier_cls):
    kwargs: dict[str, Any] = {"required_scopes": required_global_scopes()}
    public_key = os.environ.get("MCP_AUTH_JWT_PUBLIC_KEY")
    issuer = os.environ.get("MCP_AUTH_JWT_ISSUER")
    audience = os.environ.get("MCP_AUTH_JWT_AUDIENCE")
    jwks_uri = os.environ.get("MCP_AUTH_JWT_JWKS_URI")
    algorithm = os.environ.get("MCP_AUTH_JWT_ALGORITHM")
    if public_key:
        kwargs["public_key"] = public_key
    if issuer:
        kwargs["issuer"] = issuer
    if audience:
        kwargs["audience"] = audience
    if jwks_uri:
        kwargs["jwks_uri"] = jwks_uri
    if algorithm:
        kwargs["algorithm"] = algorithm
    return jwt_verifier_cls(**kwargs)


def _auth_config_error(message: str) -> None:
    """Fail closed for invalid auth configuration in production-like environments."""
    if is_production_env():
        raise RuntimeError(message)
    logger.warning("%s; running without auth", message)


def tool_auth(required_scopes: Iterable[str] | None):
    """Return a FastMCP component auth check for a tool's required scopes."""
    scopes = [scope for scope in (required_scopes or []) if scope]
    if not scopes:
        return None

    from fastmcp.server.auth import require_scopes

    return require_scopes(*scopes)


async def authorize_http_request(
    request: Request, required_scopes: Iterable[str] | None = None
) -> tuple[bool, str | None, list[str]]:
    """Authorize non-MCP HTTP endpoints using the same server auth settings."""
    auth_type = os.environ.get("MCP_AUTH_TYPE", "none").lower()
    if auth_type == "none":
        enforce_no_auth_policy()
        return True, "anonymous", []

    token = _bearer_token_from_request(request)
    if not token:
        return False, None, []

    if auth_type == "bearer":
        expected = os.environ.get("MCP_AUTH_TOKEN", "")
        if not expected or not hmac.compare_digest(token, expected):
            return False, None, []
        scopes = default_scopes()
        if not _has_scopes(scopes, required_scopes):
            return False, os.environ.get("MCP_AUTH_CLIENT_ID", "bearer-user"), scopes
        return True, os.environ.get("MCP_AUTH_CLIENT_ID", "bearer-user"), scopes

    provider = build_auth_provider()
    if provider is None:
        return False, None, []
    access_token = await provider.verify_token(token)
    if access_token is None:
        return False, None, []
    scopes = list(access_token.scopes or [])
    if not _has_scopes(scopes, required_scopes):
        return False, access_token.client_id, scopes
    return True, access_token.client_id, scopes


def _bearer_token_from_request(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return ""
    return token.strip()


def _has_scopes(actual: Iterable[str], required: Iterable[str] | None) -> bool:
    required_set = {scope for scope in (required or []) if scope}
    if not required_set:
        return True
    return required_set.issubset(set(actual))


def safe_config_summary() -> dict[str, Any]:
    """Return non-sensitive auth policy for diagnostics."""
    return {
        "type": os.environ.get("MCP_AUTH_TYPE", "none"),
        "default_scopes": default_scopes(),
        "required_global_scopes": required_global_scopes(),
        "human_approval_required_for_destructive": _human_approval_required(),
    }


def redact_secrets(value: Any) -> Any:
    """Remove known secrets and token-like values from diagnostic data."""
    if isinstance(value, dict):
        return {key: redact_secrets(val) for key, val in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if not isinstance(value, str):
        return value

    redacted = value
    for secret in _known_secret_values():
        redacted = redacted.replace(secret, "[REDACTED]")

    redacted = re.sub(
        r"(https://)([^/\s:@]+:)?[^@\s/]+@",
        r"\1[REDACTED]@",
        redacted,
    )
    redacted = re.sub(
        r"(Bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted


def _known_secret_values() -> list[str]:
    names = [
        "MCP_AUTH_TOKEN",
        "SOURCE_GIT_TOKEN",
        "SOURCE_S3_ACCESS_KEY",
        "SOURCE_S3_SECRET_KEY",
        "SOURCE_OCI_PASSWORD",
        "GITHUB_TOKEN",
    ]
    secrets = []
    for name in names:
        value = os.environ.get(name, "")
        if value and len(value) >= 4:
            secrets.append(value)
    return secrets


def _human_approval_required() -> bool:
    return (
        os.environ.get("MCP_REQUIRE_HUMAN_APPROVAL_FOR_DESTRUCTIVE", "true").lower()
        != "false"
    )


def _annotation(component: Any, key: str, default: Any = None) -> Any:
    annotations = getattr(component, "annotations", None)
    if annotations is None:
        return default
    if isinstance(annotations, dict):
        return annotations.get(key, default)
    return getattr(annotations, key, default)


def validate_tool_policy(tool_name: str, component: Any, arguments: dict[str, Any]) -> None:
    """Enforce generic server-side policy before tool execution."""
    destructive = bool(_annotation(component, "destructiveHint", False))
    if destructive and _human_approval_required():
        approved = bool(arguments.pop("human_approved", False))
        arguments.pop("approval_reason", None)
        if not approved:
            raise AuthorizationDenied(
                f"Tool '{tool_name}' is marked destructive and requires human_approved=true."
            )


class AuthzAuditMiddleware(Middleware):
    """FastMCP middleware for policy enforcement and audit logs."""

    async def on_call_tool(self, context, call_next):
        tool_name = context.message.name
        trace_id = str(uuid.uuid4())
        arguments = dict(context.message.arguments or {})
        client_id = None
        request_id = None
        result = "denied"

        try:
            fastmcp_context = context.fastmcp_context
            if fastmcp_context is not None:
                client_id = fastmcp_context.client_id
                try:
                    request_id = fastmcp_context.request_id
                except RuntimeError:
                    request_id = None
                component = await fastmcp_context.fastmcp.get_tool(tool_name)
            else:
                component = None

            if component is None:
                raise AuthorizationDenied(f"Tool '{tool_name}' was not found.")

            validate_tool_policy(tool_name, component, arguments)
            context.message.arguments = arguments
            response = await call_next(context)
            result = "allowed"
            return response
        finally:
            audit_logger.info(
                "mcp_tool_call",
                extra={
                    "tool": tool_name,
                    "client_id": client_id,
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "repo": _audit_arg(arguments, "repo"),
                    "branch": _audit_branch(arguments),
                    "action": tool_name,
                    "result": result,
                },
            )


def _audit_arg(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    return str(value) if value is not None else None


def _audit_branch(arguments: dict[str, Any]) -> str | None:
    for key in ("branch", "branch_name", "target_branch", "head", "base", "ref"):
        value = arguments.get(key)
        if value:
            return str(value)
    return None


class HttpAuthMiddleware(BaseHTTPMiddleware):
    """Protect Starlette HTTP routes mounted outside the MCP transport."""

    def __init__(self, app, protected_prefixes: Iterable[str] | None = None):
        super().__init__(app)
        self.protected_prefixes = tuple(
            prefix.rstrip("/") or "/" for prefix in (protected_prefixes or [])
        )

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if self._is_protected(path):
            allowed, _, _ = await authorize_http_request(request)
            if not allowed:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    def _is_protected(self, path: str) -> bool:
        for prefix in self.protected_prefixes:
            if path == prefix or path.startswith(f"{prefix}/"):
                return True
        return False
