"""Tests for the multi-source loader."""

import pytest
from unittest import mock

from loader import (
    ASSET_DIRS,
    _merge_into_workspace,
    _sync_git,
    _sync_inline,
    _validate_git_source,
    sync_sources,
)


def test_sync_inline(workspace, tmp_path):
    """Inline source copies files correctly into workspace."""
    inline_dir = tmp_path / "inline"
    inline_dir.mkdir()
    tools_dir = inline_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "hello.py").write_text("def hello(): return 'hi'")

    _sync_inline(workspace, inline_dir)

    assert (workspace / "tools" / "hello.py").exists()
    assert (workspace / "tools" / "hello.py").read_text() == "def hello(): return 'hi'"


def test_sync_inline_overwrites(workspace, tmp_path):
    """Inline source overwrites existing files."""
    (workspace / "tools" / "hello.py").write_text("old content")

    inline_dir = tmp_path / "inline"
    inline_dir.mkdir()
    tools_dir = inline_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "hello.py").write_text("new content")

    _sync_inline(workspace, inline_dir)

    assert (workspace / "tools" / "hello.py").read_text() == "new content"


def test_merge_into_workspace(workspace, tmp_path):
    """Merge correctly copies from all asset directories."""
    source = tmp_path / "source"
    for d in ASSET_DIRS:
        (source / d).mkdir(parents=True)

    (source / "tools" / "a.py").write_text("tool a")
    (source / "knowledge" / "doc.md").write_text("# Doc")

    _merge_into_workspace(workspace, source)

    assert (workspace / "tools" / "a.py").read_text() == "tool a"
    assert (workspace / "knowledge" / "doc.md").read_text() == "# Doc"


def test_merge_blocks_sensitive_files_by_default(workspace, tmp_path):
    """Sensitive-looking files are not copied unless explicitly allowlisted."""
    source = tmp_path / "source"
    (source / "knowledge").mkdir(parents=True)
    (source / "knowledge" / ".env").write_text("TOKEN=secret")
    (source / "knowledge" / "safe.md").write_text("# Safe")

    _merge_into_workspace(workspace, source)

    assert not (workspace / "knowledge" / ".env").exists()
    assert (workspace / "knowledge" / "safe.md").exists()


def test_merge_blocks_generated_python_cache_artifacts(workspace, tmp_path):
    """Generated Python caches never enter the runtime workspace."""
    source = tmp_path / "source"
    (source / "tools" / "__pycache__").mkdir(parents=True)
    (source / "resources").mkdir(parents=True)
    (source / "knowledge").mkdir(parents=True)
    (source / "tools" / "__pycache__" / "cached.py").write_text("def cached(): pass")
    (source / "resources" / "resource.cpython-314.pyc").write_bytes(b"cache")
    (source / "knowledge" / ".ruff_cache").write_text("cache")

    _merge_into_workspace(workspace, source)

    assert not (workspace / "tools" / "__pycache__" / "cached.py").exists()
    assert not (workspace / "resources" / "resource.cpython-314.pyc").exists()
    assert not (workspace / "knowledge" / ".ruff_cache").exists()


def test_merge_allows_explicit_sensitive_file_allowlist(
    workspace, tmp_path, monkeypatch
):
    """Sensitive files require an explicit allowlist pattern."""
    source = tmp_path / "source"
    (source / "knowledge").mkdir(parents=True)
    (source / "knowledge" / ".env").write_text("TOKEN=allowed")
    monkeypatch.setenv("SOURCE_BLOCKED_FILE_ALLOWLIST", "knowledge/.env")

    _merge_into_workspace(workspace, source)

    assert (workspace / "knowledge" / ".env").exists()


def test_merge_rejects_unsupported_asset_types(workspace, tmp_path):
    """Tool/resource/prompt directories only accept Python files."""
    source = tmp_path / "source"
    (source / "tools").mkdir(parents=True)
    (source / "knowledge").mkdir(parents=True)
    (source / "tools" / "notes.txt").write_text("not python")
    (source / "knowledge" / "binary.bin").write_text("not allowed")

    _merge_into_workspace(workspace, source)

    assert not (workspace / "tools" / "notes.txt").exists()
    assert not (workspace / "knowledge" / "binary.bin").exists()


def test_merge_enforces_file_size_limit(workspace, tmp_path, monkeypatch):
    """Oversized source files are skipped before they enter the workspace."""
    source = tmp_path / "source"
    (source / "knowledge").mkdir(parents=True)
    (source / "knowledge" / "large.md").write_text("x" * 20)
    monkeypatch.setenv("MCP_MAX_SOURCE_FILE_SIZE_BYTES", "10")

    _merge_into_workspace(workspace, source)

    assert not (workspace / "knowledge" / "large.md").exists()


def test_git_source_validates_allowlists(monkeypatch):
    """Git repository and branch can be restricted by configuration."""
    monkeypatch.setenv("SOURCE_GIT_ALLOWED_REPOSITORIES", "https://github.com/acme/*")
    monkeypatch.setenv("SOURCE_GIT_ALLOWED_BRANCHES", "main,release/*")

    _validate_git_source("https://github.com/acme/mcp.git", "release/1", "")

    with pytest.raises(ValueError, match="SOURCE_GIT_REPOSITORY"):
        _validate_git_source("https://github.com/other/mcp.git", "main", "")
    with pytest.raises(ValueError, match="SOURCE_GIT_BRANCH"):
        _validate_git_source("https://github.com/acme/mcp.git", "dev", "")


def test_git_source_blocks_path_traversal():
    """SOURCE_GIT_PATH must stay inside the cloned repository."""
    with pytest.raises(ValueError, match="SOURCE_GIT_PATH"):
        _validate_git_source("https://github.com/acme/mcp.git", "main", "../secrets")


def test_git_clone_uses_askpass_and_scrubs_token(workspace, monkeypatch):
    """Private Git token is provided through askpass and scrubbed from errors."""
    monkeypatch.setenv("SOURCE_GIT_REPOSITORY", "https://github.com/acme/mcp.git")
    monkeypatch.setenv("SOURCE_GIT_BRANCH", "main")
    monkeypatch.setenv("SOURCE_GIT_TOKEN", "supersecret")

    with mock.patch(
        "git.Repo.clone_from",
        side_effect=RuntimeError("fatal: https://x-access-token:supersecret@example"),
    ) as clone_mock:
        with pytest.raises(RuntimeError) as exc:
            _sync_git(workspace)

    assert "supersecret" not in str(exc.value)
    clone_url = clone_mock.call_args.args[0]
    clone_env = clone_mock.call_args.kwargs["env"]
    assert clone_url == "https://github.com/acme/mcp.git"
    assert "supersecret" not in clone_url
    assert clone_env["GIT_TERMINAL_PROMPT"] == "0"
    assert "GIT_ASKPASS" in clone_env


def test_sync_sources_empty(workspace, monkeypatch):
    """No sources enabled — workspace stays empty but dirs exist."""
    monkeypatch.setenv("SOURCE_INLINE_DIR", "/nonexistent")
    sync_sources(str(workspace))

    for d in ASSET_DIRS:
        assert (workspace / d).is_dir()
        assert list((workspace / d).iterdir()) == []


def test_sync_sources_inline_only(workspace, tmp_path, monkeypatch):
    """Only inline source enabled."""
    inline_dir = tmp_path / "inline"
    (inline_dir / "tools").mkdir(parents=True)
    (inline_dir / "tools" / "test.py").write_text("def test(): pass")

    monkeypatch.setenv("SOURCE_INLINE_DIR", str(inline_dir))
    sync_sources(str(workspace))

    assert (workspace / "tools" / "test.py").exists()


@pytest.fixture
def s3_mock():
    """Mock S3 using moto."""
    from moto import mock_aws

    with mock_aws():
        import boto3

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")

        # Upload test files
        s3.put_object(
            Bucket="test-bucket", Key="tools/hello.py", Body=b"def hello(): return 'hi'"
        )
        s3.put_object(
            Bucket="test-bucket", Key="knowledge/doc.md", Body=b"# Doc from S3"
        )

        yield s3


def test_sync_s3(workspace, s3_mock, monkeypatch):
    """S3 source downloads files correctly."""
    monkeypatch.setenv("SOURCE_S3_ENABLED", "true")
    monkeypatch.setenv("SOURCE_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("SOURCE_S3_REGION", "us-east-1")
    monkeypatch.setenv("SOURCE_INLINE_DIR", "/nonexistent")

    sync_sources(str(workspace))

    assert (workspace / "tools" / "hello.py").exists()
    assert (workspace / "tools" / "hello.py").read_text() == "def hello(): return 'hi'"
    assert (workspace / "knowledge" / "doc.md").read_text() == "# Doc from S3"


def test_sync_s3_with_prefix(workspace, monkeypatch):
    """S3 source with prefix filters correctly."""
    from moto import mock_aws

    with mock_aws():
        import boto3

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        s3.put_object(
            Bucket="test-bucket",
            Key="prod/tools/hello.py",
            Body=b"def hello(): return 'prod'",
        )
        s3.put_object(
            Bucket="test-bucket",
            Key="dev/tools/hello.py",
            Body=b"def hello(): return 'dev'",
        )

        monkeypatch.setenv("SOURCE_S3_ENABLED", "true")
        monkeypatch.setenv("SOURCE_S3_BUCKET", "test-bucket")
        monkeypatch.setenv("SOURCE_S3_PREFIX", "prod")
        monkeypatch.setenv("SOURCE_S3_REGION", "us-east-1")
        monkeypatch.setenv("SOURCE_INLINE_DIR", "/nonexistent")

        sync_sources(str(workspace))

        assert (
            workspace / "tools" / "hello.py"
        ).read_text() == "def hello(): return 'prod'"


def test_merge_precedence(workspace, tmp_path, monkeypatch):
    """Inline overrides S3 (inline has higher precedence)."""
    from moto import mock_aws

    with mock_aws():
        import boto3

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        s3.put_object(
            Bucket="test-bucket", Key="tools/greet.py", Body=b"def greet(): return 's3'"
        )

        inline_dir = tmp_path / "inline"
        (inline_dir / "tools").mkdir(parents=True)
        (inline_dir / "tools" / "greet.py").write_text("def greet(): return 'inline'")

        monkeypatch.setenv("SOURCE_S3_ENABLED", "true")
        monkeypatch.setenv("SOURCE_S3_BUCKET", "test-bucket")
        monkeypatch.setenv("SOURCE_S3_REGION", "us-east-1")
        monkeypatch.setenv("SOURCE_INLINE_DIR", str(inline_dir))

        sync_sources(str(workspace))

        # Inline should win over S3
        assert (
            workspace / "tools" / "greet.py"
        ).read_text() == "def greet(): return 'inline'"
