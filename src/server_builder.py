"""Builds a FastMCP server from workspace files.

Dynamically loads tools, resources, and prompts from Python files
in the workspace directory and registers them with a FastMCP instance.

Directory structure expected:
  workspace/tools/*.py      - Each file exports functions decorated with markers
  workspace/resources/*.py  - Resource definitions
  workspace/prompts/*.py    - Prompt definitions
  workspace/knowledge/*     - Static files served as resources
"""

import importlib.util
import logging
import os
import sys
import types
from pathlib import Path

from fastmcp import FastMCP

logger = logging.getLogger("fastmcp-server.builder")


def build_server(workspace: str) -> tuple[FastMCP, dict]:
    """Build and return a configured FastMCP server instance and component counts."""
    ws = Path(workspace)
    server_name = os.environ.get("MCP_SERVER_NAME", "fastmcp-server")
    strict = os.environ.get("MCP_STRICT_LOADING", "false").lower() == "true"

    # Configure authentication
    auth = _build_auth()

    # Server-level options
    server_kwargs: dict = {"name": server_name}
    if auth:
        server_kwargs["auth"] = auth

    # Error masking (v0.3.0)
    if os.environ.get("MCP_MASK_ERROR_DETAILS", "false").lower() == "true":
        server_kwargs["mask_error_details"] = True

    # Duplicate handling (v0.3.0)
    dup_mode = os.environ.get("MCP_ON_DUPLICATE_TOOLS", "").lower()
    if dup_mode in ("warn", "error", "replace", "ignore"):
        server_kwargs["on_duplicate"] = dup_mode

    mcp = FastMCP(**server_kwargs)

    # Load components and track counts
    tool_count = _load_tools(mcp, ws / "tools", strict=strict)
    resource_count = _load_resources(mcp, ws / "resources", strict=strict)
    prompt_count = _load_prompts(mcp, ws / "prompts", strict=strict)
    knowledge_count = _load_knowledge(mcp, ws / "knowledge")

    counts = {
        "tool_count": tool_count,
        "resource_count": resource_count,
        "prompt_count": prompt_count,
        "knowledge_count": knowledge_count,
    }

    logger.info(
        "Server '%s' built: %d tools, %d resources, %d prompts, %d knowledge files",
        server_name,
        tool_count,
        resource_count,
        prompt_count,
        knowledge_count,
    )

    return mcp, counts


def rebuild_components(mcp, workspace: str) -> dict:
    """Rebuild and re-register all components (used by hot reload and periodic sync).

    Clears existing components from the local provider and reloads from workspace.
    """
    ws = Path(workspace)
    strict = os.environ.get("MCP_STRICT_LOADING", "false").lower() == "true"

    # Clear existing components
    try:
        mcp._local_provider._components.clear()
    except AttributeError:
        logger.warning("Could not clear components for rebuild")

    # Reload all components
    tool_count = _load_tools(mcp, ws / "tools", strict=strict)
    resource_count = _load_resources(mcp, ws / "resources", strict=strict)
    prompt_count = _load_prompts(mcp, ws / "prompts", strict=strict)
    knowledge_count = _load_knowledge(mcp, ws / "knowledge")

    counts = {
        "tool_count": tool_count,
        "resource_count": resource_count,
        "prompt_count": prompt_count,
        "knowledge_count": knowledge_count,
    }

    logger.info(
        "Rebuild complete: %d tools, %d resources, %d prompts, %d knowledge files",
        tool_count,
        resource_count,
        prompt_count,
        knowledge_count,
    )

    return counts


def _build_auth():
    """Build authentication handler from environment variables.

    Supported auth types:
      - none: No authentication
      - bearer: Static token via StaticTokenVerifier
      - jwt: JWT verification via JWTVerifier
      - multi: Multiple auth providers tried in order
    """
    auth_type = os.environ.get("MCP_AUTH_TYPE", "none").lower()

    if auth_type == "bearer":
        return _build_bearer_auth()

    if auth_type == "jwt":
        return _build_jwt_auth()

    if auth_type == "multi":
        return _build_multi_auth()

    if auth_type != "none":
        logger.warning("Unknown auth type '%s', running without auth", auth_type)

    return None


def _build_bearer_auth():
    """Build bearer token auth."""
    from fastmcp.server.auth import StaticTokenVerifier

    token = os.environ.get("MCP_AUTH_TOKEN", "")
    if not token:
        logger.warning("Bearer auth enabled but MCP_AUTH_TOKEN not set")
        return None
    return StaticTokenVerifier(tokens={token: {"sub": "bearer-user"}})


def _build_jwt_auth():
    """Build JWT auth."""
    from fastmcp.server.auth import JWTVerifier

    kwargs = {}
    issuer = os.environ.get("MCP_AUTH_JWT_ISSUER")
    audience = os.environ.get("MCP_AUTH_JWT_AUDIENCE")
    jwks_uri = os.environ.get("MCP_AUTH_JWT_JWKS_URI")
    if issuer:
        kwargs["issuer"] = issuer
    if audience:
        kwargs["audience"] = audience
    if jwks_uri:
        kwargs["jwks_uri"] = jwks_uri
    return JWTVerifier(**kwargs)


def _build_multi_auth():
    """Build multi-auth — try each configured provider in order.

    Uses MCP_AUTH_PROVIDERS to determine which providers to combine.
    Example: MCP_AUTH_PROVIDERS=bearer,jwt
    """
    providers_str = os.environ.get("MCP_AUTH_PROVIDERS", "")
    if not providers_str:
        logger.warning("Multi auth enabled but MCP_AUTH_PROVIDERS not set")
        return None

    providers = [p.strip() for p in providers_str.split(",") if p.strip()]
    auth_list = []

    for provider in providers:
        if provider == "bearer":
            auth = _build_bearer_auth()
            if auth:
                auth_list.append(auth)
        elif provider == "jwt":
            auth = _build_jwt_auth()
            if auth:
                auth_list.append(auth)
        else:
            logger.warning("Unknown auth provider in multi-auth: %s", provider)

    if not auth_list:
        logger.warning("No valid auth providers configured for multi-auth")
        return None

    if len(auth_list) == 1:
        return auth_list[0]

    # Use the first provider — FastMCP doesn't have a built-in MultiAuth yet,
    # so we use the first valid provider. When FastMCP adds MultiAuth, we'll use it.
    logger.info(
        "Multi-auth configured with %d providers (using first match)", len(auth_list)
    )
    return auth_list[0]


def _load_tools(mcp: FastMCP, tools_dir: Path, strict: bool = False) -> int:
    """Load tool functions from Python files in the tools directory."""
    if not tools_dir.is_dir():
        return 0

    from metrics import instrument_tool, is_enabled as metrics_enabled

    count = 0
    for py_file in sorted(tools_dir.glob("*.py")):
        module = _import_module(py_file)
        if module is None:
            if strict:
                raise RuntimeError(f"Strict loading: failed to import {py_file.name}")
            continue

        # Read optional module-level metadata (v0.3.0+)
        mod_tags = getattr(module, "__tags__", None)
        mod_timeout = getattr(module, "__timeout__", None)
        mod_annotations = getattr(module, "__annotations_mcp__", None)
        mod_scopes = getattr(module, "__required_scopes__", None)

        registered = False
        for name in dir(module):
            if name.startswith("_"):
                continue
            obj = getattr(module, name)
            if callable(obj) and isinstance(obj, types.FunctionType):
                # Instrument with metrics if enabled
                if metrics_enabled():
                    obj = instrument_tool(obj, name)

                # Build kwargs for mcp.tool()
                tool_kwargs: dict = {}
                if mod_tags is not None:
                    tool_kwargs["tags"] = set(mod_tags)
                if mod_timeout is not None:
                    tool_kwargs["timeout"] = float(mod_timeout)
                if mod_annotations is not None:
                    tool_kwargs["annotations"] = dict(mod_annotations)

                # Store required scopes in annotations (v0.7.0)
                if mod_scopes is not None:
                    annotations = tool_kwargs.get("annotations", {})
                    annotations["requiredScopes"] = list(mod_scopes)
                    tool_kwargs["annotations"] = annotations

                if tool_kwargs:
                    mcp.tool(obj, **tool_kwargs)
                else:
                    mcp.tool(obj)
                logger.info("Registered tool: %s (from %s)", name, py_file.name)
                count += 1
                registered = True

        if not registered:
            msg = f"No tools found in {py_file.name}"
            if strict:
                raise RuntimeError(f"Strict loading: {msg}")
            logger.warning(msg)

    return count


def _load_resources(mcp: FastMCP, resources_dir: Path, strict: bool = False) -> int:
    """Load resource functions from Python files in the resources directory."""
    if not resources_dir.is_dir():
        return 0

    count = 0
    for py_file in sorted(resources_dir.glob("*.py")):
        module = _import_module(py_file)
        if module is None:
            if strict:
                raise RuntimeError(f"Strict loading: failed to import {py_file.name}")
            continue

        # v0.3.0: Support RESOURCES dict for multiple resources per file
        resources_map = getattr(module, "RESOURCES", None)
        if isinstance(resources_map, dict):
            for uri, func_name in resources_map.items():
                func = getattr(module, func_name, None)
                if func and callable(func):
                    mcp.resource(uri)(func)
                    logger.info("Registered resource: %s -> %s", uri, func_name)
                    count += 1
                else:
                    msg = f"RESOURCES maps '{uri}' to '{func_name}' but function not found in {py_file.name}"
                    if strict:
                        raise RuntimeError(f"Strict loading: {msg}")
                    logger.warning(msg)
            continue

        # Legacy: single resource via RESOURCE_URI
        resource_uri = getattr(module, "RESOURCE_URI", None)
        if not resource_uri:
            msg = f"No RESOURCE_URI or RESOURCES in {py_file.name}, skipping"
            if strict:
                raise RuntimeError(f"Strict loading: {msg}")
            logger.warning(msg)
            continue

        for name in dir(module):
            if name.startswith("_"):
                continue
            obj = getattr(module, name)
            if (
                callable(obj)
                and isinstance(obj, types.FunctionType)
                and name != "RESOURCE_URI"
            ):
                mcp.resource(resource_uri)(obj)
                logger.info("Registered resource: %s -> %s", resource_uri, name)
                count += 1
                break

    return count


def _load_prompts(mcp: FastMCP, prompts_dir: Path, strict: bool = False) -> int:
    """Load prompt functions from Python files in the prompts directory."""
    if not prompts_dir.is_dir():
        return 0

    count = 0
    for py_file in sorted(prompts_dir.glob("*.py")):
        module = _import_module(py_file)
        if module is None:
            if strict:
                raise RuntimeError(f"Strict loading: failed to import {py_file.name}")
            continue

        for name in dir(module):
            if name.startswith("_"):
                continue
            obj = getattr(module, name)
            if callable(obj) and isinstance(obj, types.FunctionType):
                mcp.prompt(obj)
                logger.info("Registered prompt: %s (from %s)", name, py_file.name)
                count += 1

    return count


def _load_knowledge(mcp: FastMCP, knowledge_dir: Path) -> int:
    """Register knowledge base files as static resources."""
    if not knowledge_dir.is_dir():
        return 0

    count = 0
    for file_path in sorted(knowledge_dir.rglob("*")):
        if not file_path.is_file():
            continue

        rel_path = file_path.relative_to(knowledge_dir)
        uri = f"knowledge://{rel_path}"

        def _make_reader(fp: Path, rp: Path):
            def read_file() -> str:
                return fp.read_text(encoding="utf-8", errors="replace")

            read_file.__doc__ = f"Read knowledge base file: {rp}"
            read_file.__name__ = f"kb_{rp.stem}"
            return read_file

        mcp.resource(uri)(_make_reader(file_path, rel_path))
        logger.info("Registered knowledge: %s", uri)
        count += 1

    return count


def _import_module(path: Path) -> types.ModuleType | None:
    """Dynamically import a Python module from a file path."""
    module_name = f"dynamic.{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.error("Cannot load module spec from %s", path)
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        logger.exception("Failed to import %s", path)
        return None
