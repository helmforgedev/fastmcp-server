import os
import sys
from pathlib import Path

import pytest

# Add src/ to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace with standard directory structure."""
    for d in ["tools", "resources", "prompts", "knowledge"]:
        (tmp_path / d).mkdir()
    return tmp_path


@pytest.fixture
def sample_tool(workspace):
    """Create a sample tool file in the workspace."""
    tool_file = workspace / "tools" / "greet.py"
    tool_file.write_text(
        'def greet(name: str) -> str:\n    """Greet someone."""\n    return f"Hello, {name}!"\n'
    )
    return tool_file


@pytest.fixture
def sample_resource(workspace):
    """Create a sample resource file in the workspace."""
    res_file = workspace / "resources" / "config.py"
    res_file.write_text(
        'import json\n\n'
        'RESOURCE_URI = "config://app"\n\n'
        'def get_config() -> str:\n    """Config."""\n    return json.dumps({"version": "1.0"}, indent=2)\n'
    )
    return res_file


@pytest.fixture
def sample_prompt(workspace):
    """Create a sample prompt file in the workspace."""
    prompt_file = workspace / "prompts" / "summarize.py"
    prompt_file.write_text(
        'def summarize(text: str) -> str:\n    """Summarize."""\n    return f"Summarize: {text}"\n'
    )
    return prompt_file


@pytest.fixture
def sample_knowledge(workspace):
    """Create sample knowledge files in the workspace."""
    kb_file = workspace / "knowledge" / "readme.md"
    kb_file.write_text("# Readme\nThis is a knowledge file.\n")
    return kb_file


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Clean MCP/SOURCE env vars between tests."""
    for key in list(os.environ.keys()):
        if key.startswith("MCP_") or key.startswith("SOURCE_"):
            monkeypatch.delenv(key, raising=False)
