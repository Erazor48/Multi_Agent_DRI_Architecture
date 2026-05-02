"""Unit tests for tools (no API calls — only local tools tested)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import dri.tools  # noqa: F401 — ensure registration


@pytest.fixture(autouse=True)
def workspace_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    # Reset settings singleton to pick up new env var
    from dri.config.settings import get_settings
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_code_exec_simple():
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("code_exec")
    result = await tool.execute({"code": "print(2 + 2)"})
    assert result.success
    assert "4" in result.data


@pytest.mark.asyncio
async def test_code_exec_runtime_error():
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("code_exec")
    result = await tool.execute({"code": "raise ValueError('test error')"})
    assert not result.success
    assert "test error" in result.error


@pytest.mark.asyncio
async def test_code_exec_empty():
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("code_exec")
    result = await tool.execute({"code": ""})
    assert not result.success


@pytest.mark.asyncio
async def test_file_write_and_read(workspace_dir):
    from dri.tools.base import ToolRegistry
    write_tool = ToolRegistry.get("file_write")
    read_tool = ToolRegistry.get("file_read")

    write_result = await write_tool.execute({"path": "test.txt", "content": "Hello, DRI!"})
    assert write_result.success

    read_result = await read_tool.execute({"path": "test.txt"})
    assert read_result.success
    assert "Hello, DRI!" in read_result.data


@pytest.mark.asyncio
async def test_file_write_creates_subdirs(workspace_dir):
    from dri.tools.base import ToolRegistry
    write_tool = ToolRegistry.get("file_write")
    result = await write_tool.execute({"path": "deep/nested/dir/file.md", "content": "# Test"})
    assert result.success
    assert (workspace_dir / "deep" / "nested" / "dir" / "file.md").exists()


@pytest.mark.asyncio
async def test_file_read_not_found(workspace_dir):
    from dri.tools.base import ToolRegistry
    read_tool = ToolRegistry.get("file_read")
    result = await read_tool.execute({"path": "nonexistent.txt"})
    assert not result.success
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_file_list(workspace_dir):
    from dri.tools.base import ToolRegistry
    write_tool = ToolRegistry.get("file_write")
    list_tool = ToolRegistry.get("file_list")

    await write_tool.execute({"path": "a.txt", "content": "a"})
    await write_tool.execute({"path": "b.txt", "content": "b"})

    result = await list_tool.execute({"path": "."})
    assert result.success
    assert any("a.txt" in f for f in result.data)
    assert any("b.txt" in f for f in result.data)


@pytest.mark.asyncio
async def test_path_traversal_blocked(workspace_dir):
    from dri.tools.base import ToolRegistry
    read_tool = ToolRegistry.get("file_read")
    result = await read_tool.execute({"path": "../../../etc/passwd"})
    assert not result.success


@pytest.mark.asyncio
async def test_shell_exec_simple(workspace_dir):
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("shell_exec")
    result = await tool.execute({
        "command": "python -c \"print('hello from shell')\"",
        "_workspace_root": str(workspace_dir),
    })
    assert result.success, result.error
    assert "hello from shell" in result.data


@pytest.mark.asyncio
async def test_shell_exec_blocked_executable(workspace_dir):
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("shell_exec")
    result = await tool.execute({
        "command": "rm -rf /",
        "_workspace_root": str(workspace_dir),
    })
    assert not result.success
    assert "allowlist" in result.error.lower()


@pytest.mark.asyncio
async def test_shell_exec_cwd_sandbox(workspace_dir):
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("shell_exec")
    result = await tool.execute({
        "command": "python -c \"import os; print(os.getcwd())\"",
        "cwd": ".",
        "_workspace_root": str(workspace_dir),
    })
    assert result.success, result.error
    # cwd must be inside workspace
    assert str(workspace_dir).lower().replace("\\", "/") in result.data.lower().replace("\\", "/")


@pytest.mark.asyncio
async def test_shell_exec_cwd_traversal_blocked(workspace_dir):
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("shell_exec")
    result = await tool.execute({
        "command": "python -c \"print('x')\"",
        "cwd": "../../",
        "_workspace_root": str(workspace_dir),
    })
    assert not result.success
    assert "workspace" in result.error.lower()


@pytest.mark.asyncio
async def test_shell_exec_creates_cwd(workspace_dir):
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("shell_exec")
    subdir = "new_project/src"
    result = await tool.execute({
        "command": "python -c \"print('ok')\"",
        "cwd": subdir,
        "_workspace_root": str(workspace_dir),
    })
    assert result.success, result.error
    assert (workspace_dir / "new_project" / "src").is_dir()


@pytest.mark.asyncio
async def test_shell_exec_nonexistent_executable(workspace_dir):
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("shell_exec")
    # 'git' is in allowlist but may or may not be installed; use 'bun' which may not be
    # Instead test with a genuinely missing binary by temporarily patching the allowlist
    import dri.tools.shell_exec as se_module
    original = se_module._ALLOWED_EXECUTABLES
    se_module._ALLOWED_EXECUTABLES = frozenset({"__nonexistent_binary__"})
    try:
        result = await tool.execute({
            "command": "__nonexistent_binary__ --help",
            "_workspace_root": str(workspace_dir),
        })
        assert not result.success
    finally:
        se_module._ALLOWED_EXECUTABLES = original


@pytest.mark.asyncio
async def test_shell_exec_failed_exit_code(workspace_dir):
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("shell_exec")
    result = await tool.execute({
        "command": "python -c \"import sys; sys.exit(1)\"",
        "_workspace_root": str(workspace_dir),
    })
    assert not result.success
    assert "exit" in result.error.lower() or "code" in result.error.lower()


@pytest.mark.asyncio
async def test_shell_exec_curl_allowed(workspace_dir):
    """curl is in the allowlist since Sprint 6 — must not be blocked."""
    import dri.tools.shell_exec as se_module
    assert "curl" in se_module._ALLOWED_EXECUTABLES, "curl must be in the allowlist"
    assert "wget" in se_module._ALLOWED_EXECUTABLES, "wget must be in the allowlist"


@pytest.mark.asyncio
async def test_web_search_no_api_key(monkeypatch):
    # web_search.py binds `settings` at import time, so we patch the module variable directly.
    from types import SimpleNamespace
    monkeypatch.setattr(
        "dri.tools.web_search.settings",
        SimpleNamespace(has_web_search=False, tavily_api_key="", brave_api_key=""),
    )

    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("web_search")
    result = await tool.execute({"query": "test"})
    assert not result.success
    assert "API key" in result.error
