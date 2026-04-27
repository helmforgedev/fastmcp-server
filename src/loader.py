"""Multi-source loader for FastMCP server assets.

Supports four sources with merge precedence:
  1. Inline (ConfigMap, mounted at /app/inline/) - highest precedence
  2. OCI artifacts (ORAS pull) - second highest
  3. S3-compatible storage (AWS S3, MinIO, Cloudflare R2)
  4. Git repository - lowest precedence

Files are synced into the workspace directory organized by type:
  workspace/tools/*.py
  workspace/resources/*.py
  workspace/prompts/*.py
  workspace/knowledge/*
"""

import fnmatch
import logging
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("fastmcp-server.loader")

ASSET_DIRS = ["tools", "resources", "prompts", "knowledge"]
DEFAULT_SENSITIVE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".coverage",
    "htmlcov",
    ".ds_store",
    "thumbs.db",
    ".env",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "id_rsa",
    "*secret*",
]
DEFAULT_KNOWLEDGE_EXTENSIONS = {
    ".csv",
    ".htm",
    ".html",
    ".json",
    ".md",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
PYTHON_ASSET_DIRS = {"tools", "resources", "prompts"}


def sync_sources(workspace: str) -> None:
    """Sync all configured sources into the workspace directory."""
    ws = Path(workspace)

    # Ensure workspace structure exists
    for d in ASSET_DIRS:
        (ws / d).mkdir(parents=True, exist_ok=True)

    # Source 4 (lowest precedence): Git
    if os.environ.get("SOURCE_GIT_ENABLED", "false").lower() == "true":
        _sync_git(ws)

    # Source 3: S3
    if os.environ.get("SOURCE_S3_ENABLED", "false").lower() == "true":
        _sync_s3(ws)

    # Source 2: OCI
    if os.environ.get("SOURCE_OCI_ENABLED", "false").lower() == "true":
        _sync_oci(ws)

    # Source 1 (highest precedence): Inline (ConfigMap mounts)
    inline_dir = Path(os.environ.get("SOURCE_INLINE_DIR", "/app/inline"))
    if inline_dir.exists():
        _sync_inline(ws, inline_dir)

    # Log summary
    for d in ASSET_DIRS:
        files = list((ws / d).iterdir())
        if files:
            logger.info("Loaded %d file(s) from %s/", len(files), d)


def _sync_git(workspace: Path) -> None:
    """Clone or pull a Git repository into the workspace."""
    import git
    from authz import redact_secrets

    repo_url = os.environ.get("SOURCE_GIT_REPOSITORY", "")
    branch = os.environ.get("SOURCE_GIT_BRANCH", "main")
    subpath = os.environ.get("SOURCE_GIT_PATH", "")
    token = os.environ.get("SOURCE_GIT_TOKEN", "")

    if not repo_url:
        logger.warning("Git source enabled but SOURCE_GIT_REPOSITORY not set")
        return

    _validate_git_source(repo_url, branch, subpath)

    clone_dir = workspace / ".git-source"
    if clone_dir.exists():
        shutil.rmtree(clone_dir)

    logger.info("Cloning %s (branch: %s)...", redact_secrets(repo_url), branch)
    try:
        clone_env = os.environ.copy()
        clone_env["GIT_TERMINAL_PROMPT"] = "0"
        if token and repo_url.startswith("https://"):
            with tempfile.TemporaryDirectory(prefix="fastmcp-git-auth-") as temp_dir:
                clone_env["GIT_ASKPASS"] = _write_git_askpass(Path(temp_dir))
                repo = git.Repo.clone_from(
                    repo_url, str(clone_dir), branch=branch, depth=1, env=clone_env
                )
        else:
            repo = git.Repo.clone_from(
                repo_url, str(clone_dir), branch=branch, depth=1, env=clone_env
            )
    except Exception as exc:
        safe_error = redact_secrets(str(exc))
        logger.error("Git sync failed: %s", safe_error)
        raise RuntimeError(f"Git sync failed: {safe_error}") from None

    logger.info("Git clone complete: %s", repo.head.commit.hexsha[:8])

    source_root = _resolve_source_subpath(clone_dir, subpath)
    _merge_into_workspace(workspace, source_root)


def _sync_s3(workspace: Path) -> None:
    """Download assets from an S3-compatible bucket."""
    import boto3
    from botocore.config import Config

    endpoint = os.environ.get("SOURCE_S3_ENDPOINT", "")
    bucket = os.environ.get("SOURCE_S3_BUCKET", "")
    region = os.environ.get("SOURCE_S3_REGION", "us-east-1")
    prefix = os.environ.get("SOURCE_S3_PREFIX", "").strip("/")
    access_key = os.environ.get("SOURCE_S3_ACCESS_KEY", "")
    secret_key = os.environ.get("SOURCE_S3_SECRET_KEY", "")

    if not bucket:
        logger.warning("S3 source enabled but SOURCE_S3_BUCKET not set")
        return

    logger.info("Syncing from s3://%s/%s...", bucket, prefix)

    client_kwargs = {"region_name": region, "config": Config(signature_version="s3v4")}
    if endpoint:
        client_kwargs["endpoint_url"] = endpoint
    if access_key and secret_key:
        client_kwargs["aws_access_key_id"] = access_key
        client_kwargs["aws_secret_access_key"] = secret_key

    s3 = boto3.client("s3", **client_kwargs)

    paginator = s3.get_paginator("list_objects_v2")
    page_kwargs = {"Bucket": bucket}
    if prefix:
        page_kwargs["Prefix"] = prefix + "/"

    s3_dir = workspace / ".s3-source"
    if s3_dir.exists():
        shutil.rmtree(s3_dir)
    s3_dir.mkdir(parents=True)

    count = 0
    for page in paginator.paginate(**page_kwargs):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # Strip prefix to get relative path
            rel_path = key[len(prefix) :].lstrip("/") if prefix else key
            if not rel_path or rel_path.endswith("/"):
                continue

            local_path = s3_dir / rel_path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(local_path))
            count += 1

    logger.info("Downloaded %d file(s) from S3", count)
    _merge_into_workspace(workspace, s3_dir)


def _sync_oci(workspace: Path) -> None:
    """Pull assets from an OCI registry via ORAS."""
    import subprocess
    from authz import redact_secrets

    registry = os.environ.get("SOURCE_OCI_REGISTRY", "")
    tag = os.environ.get("SOURCE_OCI_TAG", "latest")
    username = os.environ.get("SOURCE_OCI_USERNAME", "")
    password = os.environ.get("SOURCE_OCI_PASSWORD", "")

    if not registry:
        logger.warning("OCI source enabled but SOURCE_OCI_REGISTRY not set")
        return

    oci_dir = workspace / ".oci-source"
    if oci_dir.exists():
        shutil.rmtree(oci_dir)
    oci_dir.mkdir(parents=True)

    ref = f"{registry}:{tag}"
    logger.info("Pulling OCI artifact %s...", ref)

    # Use oras CLI if available, otherwise try Python oras-py
    cmd = ["oras", "pull", ref, "--output", str(oci_dir)]
    if username and password:
        cmd.extend(["--username", username, "--password", password])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("OCI pull failed: %s", redact_secrets(result.stderr.strip()))
        return

    logger.info("OCI pull complete")
    _merge_into_workspace(workspace, oci_dir)


def _sync_inline(workspace: Path, inline_dir: Path) -> None:
    """Copy inline (ConfigMap-mounted) files into workspace."""
    logger.info("Loading inline sources from %s...", inline_dir)
    _merge_into_workspace(workspace, inline_dir)


def _merge_into_workspace(workspace: Path, source: Path) -> None:
    """Merge source directory into workspace, overwriting existing files.

    Expected source structure:
      source/tools/*.py
      source/resources/*.py
      source/prompts/*.py
      source/knowledge/*

    """
    max_file_size = _env_int("MCP_MAX_SOURCE_FILE_SIZE_BYTES", 1_048_576)
    max_knowledge_size = _env_int("MCP_MAX_KNOWLEDGE_BYTES", 10_485_760)

    for asset_dir in ASSET_DIRS:
        src = source / asset_dir
        if not src.is_dir():
            continue
        dst = workspace / asset_dir
        for item in src.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src)
                rel_str = str(rel)
                asset_rel = f"{asset_dir}/{rel_str}".replace("\\", "/")

                if _is_blocked_source_file(asset_rel):
                    logger.warning("Skipped blocked source file: %s", asset_rel)
                    continue
                if not _is_allowed_asset_type(asset_dir, rel):
                    logger.warning(
                        "Skipped unsupported %s file: %s", asset_dir, rel_str
                    )
                    continue
                if max_file_size > 0 and item.stat().st_size > max_file_size:
                    logger.warning("Skipped oversized source file: %s", asset_rel)
                    continue
                if asset_dir == "knowledge" and max_knowledge_size > 0:
                    current_size = _directory_size(dst)
                    if current_size + item.stat().st_size > max_knowledge_size:
                        logger.warning(
                            "Skipped knowledge file over total limit: %s", asset_rel
                        )
                        continue

                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                logger.debug("Merged: %s -> %s", rel, asset_dir)


def _validate_git_source(repo_url: str, _branch: str, subpath: str) -> None:
    """Validate Git source settings before clone."""
    parsed = urlparse(repo_url)
    if parsed.scheme not in {"https", "http", "ssh", "git"}:
        raise ValueError("SOURCE_GIT_REPOSITORY must use https, http, ssh, or git.")

    _validate_relative_path(subpath, "SOURCE_GIT_PATH")


def _resolve_source_subpath(root: Path, subpath: str) -> Path:
    """Resolve a configured source subpath and keep it under root."""
    if not subpath:
        return root
    _validate_relative_path(subpath, "SOURCE_GIT_PATH")
    resolved_root = root.resolve()
    resolved_path = (root / subpath).resolve()
    if not _is_relative_to(resolved_path, resolved_root):
        raise ValueError("SOURCE_GIT_PATH must stay inside the cloned repository.")
    return resolved_path


def _validate_relative_path(value: str, name: str) -> None:
    if not value:
        return
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{name} must be a relative path without '..'.")


def _write_git_askpass(directory: Path) -> str:
    """Create a temporary askpass helper that reads credentials from env vars."""
    if os.name == "nt":
        script = directory / "git-askpass.cmd"
        script.write_text(
            "@echo off\n"
            f'"{sys.executable}" -c '
            "\"import os,sys; p=' '.join(sys.argv[1:]).lower(); "
            "print(os.environ.get('SOURCE_GIT_USERNAME','x-access-token') "
            "if 'username' in p else os.environ.get('SOURCE_GIT_TOKEN',''))\" %*\n",
            encoding="utf-8",
        )
    else:
        script = directory / "git-askpass.py"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "import sys\n"
            "prompt = ' '.join(sys.argv[1:]).lower()\n"
            "if 'username' in prompt:\n"
            "    print(os.environ.get('SOURCE_GIT_USERNAME', 'x-access-token'))\n"
            "else:\n"
            "    print(os.environ.get('SOURCE_GIT_TOKEN', ''))\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def _is_blocked_source_file(asset_rel: str) -> bool:
    """Return True when a source file is sensitive."""
    normalized = asset_rel.replace("\\", "/")
    lower = normalized.lower()

    parts = Path(lower).parts
    name = Path(lower).name
    for pattern in DEFAULT_SENSITIVE_PATTERNS:
        if (
            fnmatch.fnmatch(name, pattern)
            or fnmatch.fnmatch(lower, pattern)
            or any(fnmatch.fnmatch(part, pattern) for part in parts)
        ):
            return True
    return False


def _is_allowed_asset_type(asset_dir: str, rel: Path) -> bool:
    if asset_dir in PYTHON_ASSET_DIRS:
        return rel.suffix == ".py"
    if asset_dir == "knowledge":
        extensions = set(_csv_env("MCP_ALLOWED_KNOWLEDGE_EXTENSIONS"))
        if not extensions:
            extensions = DEFAULT_KNOWLEDGE_EXTENSIONS
        extensions = {ext if ext.startswith(".") else f".{ext}" for ext in extensions}
        return rel.suffix.lower() in extensions
    return True


def _csv_env(name: str) -> list[str]:
    return [
        item.strip() for item in os.environ.get(name, "").split(",") if item.strip()
    ]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        logger.warning("Invalid integer for %s; using %d", name, default)
        return default


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
