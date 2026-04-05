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

    # Configure authentication
    auth = _build_auth()
    mcp = FastMCP(name=server_name, auth=auth) if auth else FastMCP(name=server_name)

    # Load components and track counts
    tool_count = _load_tools(mcp, ws / "tools")
    resource_count = _load_resources(mcp, ws / "resources")
    prompt_count = _load_prompts(mcp, ws / "prompts")
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


def _build_auth():
    """Build authentication handler from environment variables."""
    auth_type = os.environ.get("MCP_AUTH_TYPE", "none").lower()

    if auth_type == "bearer":
        from fastmcp.server.auth import BearerTokenAuth

        token = os.environ.get("MCP_AUTH_TOKEN", "")
        if not token:
            logger.warning("Bearer auth enabled but MCP_AUTH_TOKEN not set")
            return None
        return BearerTokenAuth(token=token)

    if auth_type == "jwt":
        from fastmcp.server.auth import JWTAuth

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
        return JWTAuth(**kwargs)

    if auth_type != "none":
        logger.warning("Unknown auth type '%s', running without auth", auth_type)

    return None


def _load_tools(mcp: FastMCP, tools_dir: Path) -> int:
    """Load tool functions from Python files in the tools directory."""
    if not tools_dir.is_dir():
        return 0

    count = 0
    for py_file in sorted(tools_dir.glob("*.py")):
        module = _import_module(py_file)
        if module is None:
            continue

        registered = False
        for name in dir(module):
            if name.startswith("_"):
                continue
            obj = getattr(module, name)
            if callable(obj) and isinstance(obj, types.FunctionType):
                mcp.tool(obj)
                logger.info("Registered tool: %s (from %s)", name, py_file.name)
                count += 1
                registered = True

        if not registered:
            logger.warning("No tools found in %s", py_file.name)

    return count


def _load_resources(mcp: FastMCP, resources_dir: Path) -> int:
    """Load resource functions from Python files in the resources directory."""
    if not resources_dir.is_dir():
        return 0

    count = 0
    for py_file in sorted(resources_dir.glob("*.py")):
        module = _import_module(py_file)
        if module is None:
            continue

        resource_uri = getattr(module, "RESOURCE_URI", None)
        if not resource_uri:
            logger.warning("No RESOURCE_URI in %s, skipping", py_file.name)
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


def _load_prompts(mcp: FastMCP, prompts_dir: Path) -> int:
    """Load prompt functions from Python files in the prompts directory."""
    if not prompts_dir.is_dir():
        return 0

    count = 0
    for py_file in sorted(prompts_dir.glob("*.py")):
        module = _import_module(py_file)
        if module is None:
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
