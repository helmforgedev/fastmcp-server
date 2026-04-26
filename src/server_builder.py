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
import inspect
import logging
import os
import sys
import types
from pathlib import Path

from fastmcp import FastMCP

from authz import (
    AuthzAuditMiddleware,
    build_auth_provider,
    env_flag,
    is_production_env,
    tool_auth,
)

logger = logging.getLogger("fastmcp-server.builder")
HELPER_MODULE_SUFFIXES = ("_helpers",)


def _get_explicit_tool_names(module: types.ModuleType) -> list[str] | None:
    """Return explicit tool export names when the module declares them."""
    explicit = getattr(module, "TOOLS", None)
    if explicit is None:
        return None

    if isinstance(explicit, (list, tuple, set)):
        return [str(name) for name in explicit]

    logger.warning(
        "Ignoring invalid TOOLS declaration in %s; expected list/tuple/set, got %s",
        module.__name__,
        type(explicit).__name__,
    )
    return None


def _is_supported_tool_signature(func: types.FunctionType) -> tuple[bool, str]:
    """Return whether a function signature is safe to register as an MCP tool."""
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError) as exc:
        return False, f"signature inspection failed: {exc}"

    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            return False, "functions with *args are not supported"
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return False, "functions with **kwargs are not supported"

    return True, ""


def _iter_tool_candidates(module: types.ModuleType, py_file: Path):
    """Yield tool candidates from a module using explicit exports or safe heuristics."""
    auto_register = getattr(module, "__mcp_auto_register__", True)
    explicit_names = _get_explicit_tool_names(module)
    module_stem = py_file.stem.lower()

    if not auto_register and explicit_names is None:
        logger.info(
            "Skipping tool auto-registration for %s (__mcp_auto_register__=False)",
            py_file.name,
        )
        return

    if explicit_names is None and (
        module_stem == "helpers" or module_stem.endswith(HELPER_MODULE_SUFFIXES)
    ):
        logger.info(
            "Skipping helper module %s during tool auto-registration",
            py_file.name,
        )
        return

    names = explicit_names if explicit_names is not None else dir(module)
    seen: set[str] = set()

    for name in names:
        if name in seen:
            continue
        seen.add(name)

        if name.startswith("_"):
            continue

        obj = getattr(module, name, None)
        if not (callable(obj) and isinstance(obj, types.FunctionType)):
            continue

        is_explicit = explicit_names is not None

        if not is_explicit and obj.__module__ != module.__name__:
            logger.debug(
                "Skipping imported function %s from %s (defined in %s)",
                name,
                py_file.name,
                obj.__module__,
            )
            continue

        supported, reason = _is_supported_tool_signature(obj)
        if not supported:
            logger.warning(
                "Skipping function %s from %s: %s",
                name,
                py_file.name,
                reason,
            )
            continue

        yield name, obj


def build_server(workspace: str) -> tuple[FastMCP, dict]:
    """Build and return a configured FastMCP server instance and component counts."""
    ws = Path(workspace)
    server_name = os.environ.get("MCP_SERVER_NAME", "fastmcp-server")
    strict = env_flag("MCP_STRICT_LOADING", default=is_production_env())

    # Configure authentication
    auth = build_auth_provider()

    # Server-level options
    server_kwargs: dict = {"name": server_name}
    if auth:
        server_kwargs["auth"] = auth

    # Error masking (v0.3.0)
    if env_flag("MCP_MASK_ERROR_DETAILS", default=is_production_env()):
        server_kwargs["mask_error_details"] = True

    # Duplicate handling (v0.3.0)
    dup_mode = os.environ.get("MCP_ON_DUPLICATE_TOOLS", "").lower()
    if dup_mode in ("warn", "error", "replace", "ignore"):
        server_kwargs["on_duplicate"] = dup_mode

    mcp = FastMCP(**server_kwargs)
    mcp.add_middleware(AuthzAuditMiddleware())

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


def _load_tools(mcp: FastMCP, tools_dir: Path, strict: bool = False) -> int:
    """Load tool functions from Python files in the tools directory."""
    if not tools_dir.is_dir():
        return 0

    from caching import cache_tool
    from metrics import instrument_tool, is_enabled as metrics_enabled
    from rate_limiter import rate_limit_tool
    from sandboxing import sandbox_tool

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

        # v1.0.0: sandboxing, rate limiting, caching
        mod_max_memory_mb = getattr(module, "__max_memory_mb__", 0)
        mod_max_output_size_kb = getattr(module, "__max_output_size_kb__", 0)
        mod_rate_limit = getattr(module, "__rate_limit__", None)
        mod_cache_ttl = getattr(module, "__cache_ttl__", 0)

        registered = False
        for name, obj in _iter_tool_candidates(module, py_file):
            # v1.0.0: Apply sandboxing (memory + output limits)
            obj = sandbox_tool(obj, name, mod_max_memory_mb, mod_max_output_size_kb)

            # v1.0.0: Apply rate limiting
            obj = rate_limit_tool(obj, name, mod_rate_limit)

            # v1.0.0: Apply caching
            if mod_cache_ttl > 0:
                obj = cache_tool(obj, name, float(mod_cache_ttl))

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
                auth_check = tool_auth(mod_scopes)
                if auth_check:
                    tool_kwargs["auth"] = auth_check

            # Mark idempotent hint if cached (v1.0.0)
            if mod_cache_ttl > 0:
                annotations = tool_kwargs.get("annotations", {})
                annotations["idempotentHint"] = True
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
        uri = f"knowledge://{rel_path.as_posix()}"

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
