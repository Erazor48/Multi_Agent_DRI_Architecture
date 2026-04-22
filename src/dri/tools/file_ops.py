"""
File operations tool — read, write, and list files within the workspace.
All paths are sandboxed to settings.workspace_dir — no escape possible.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from dri.tools.base import BaseTool, ToolOutput, ToolRegistry


def get_settings():
    from dri.config.settings import get_settings as _get
    return _get()


def _safe_path(relative_path: str) -> Path | None:
    """
    Resolve a relative path within the workspace.
    Returns None if the path would escape the workspace sandbox.
    Reads settings lazily so tests can override WORKSPACE_DIR via env vars.
    """
    workspace = get_settings().workspace_dir.resolve()
    try:
        target = (workspace / relative_path).resolve()
    except Exception:
        return None
    if not str(target).startswith(str(workspace)):
        return None
    return target


class FileReadTool(BaseTool):
    name = "file_read"
    description = (
        "Read the contents of a file from the workspace. "
        "Provide a path relative to the workspace root. "
        "Returns the file contents as a string."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path from workspace root (e.g. 'reports/summary.md').",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to read (default 10000).",
                "default": 10000,
            },
        },
        "required": ["path"],
    }

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        path = _safe_path(raw_input.get("path", ""))
        max_chars = int(raw_input.get("max_chars", 10000))

        if path is None:
            return ToolOutput.fail("Invalid path — must be relative and within the workspace.")

        if not path.exists():
            return ToolOutput.fail(f"File not found: {raw_input['path']}")

        if not path.is_file():
            return ToolOutput.fail(f"Path is not a file: {raw_input['path']}")

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n\n[...truncated at {max_chars} chars]"
            return ToolOutput.ok(content)
        except Exception as e:
            return ToolOutput.fail(f"Failed to read file: {e}")


class FileWriteTool(BaseTool):
    name = "file_write"
    description = (
        "Write or overwrite a file in the workspace. "
        "Parent directories are created automatically. "
        "Provide a path relative to the workspace root and the content to write."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path from workspace root (e.g. 'reports/summary.md').",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file (UTF-8).",
            },
            "append": {
                "type": "boolean",
                "description": "If true, append to existing content instead of overwriting.",
                "default": False,
            },
        },
        "required": ["path", "content"],
    }

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        path = _safe_path(raw_input.get("path", ""))
        content: str = raw_input.get("content", "")
        append: bool = bool(raw_input.get("append", False))

        if path is None:
            return ToolOutput.fail("Invalid path — must be relative and within the workspace.")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            path.open(mode, encoding="utf-8").write(content)
            return ToolOutput.ok(
                {"path": str(path.relative_to(get_settings().workspace_dir.resolve())), "bytes": len(content.encode())}
            )
        except Exception as e:
            return ToolOutput.fail(f"Failed to write file: {e}")


class FileListTool(BaseTool):
    name = "file_list"
    description = (
        "List files in a workspace directory. "
        "Provide a path relative to the workspace root (use '.' for the root itself). "
        "Returns a list of file paths relative to the workspace."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path relative to workspace root. Default: '.' (root).",
                "default": ".",
            },
            "recursive": {
                "type": "boolean",
                "description": "If true, list files in all subdirectories.",
                "default": False,
            },
        },
    }

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        rel_path = raw_input.get("path", ".")
        recursive: bool = bool(raw_input.get("recursive", False))

        path = _safe_path(rel_path)
        if path is None:
            return ToolOutput.fail("Invalid path.")

        if not path.exists():
            return ToolOutput.fail(f"Directory not found: {rel_path}")

        if not path.is_dir():
            return ToolOutput.fail(f"Path is not a directory: {rel_path}")

        workspace = get_settings().workspace_dir.resolve()
        try:
            if recursive:
                files = [str(f.relative_to(workspace)) for f in path.rglob("*") if f.is_file()]
            else:
                files = [str(f.relative_to(workspace)) for f in path.iterdir()]
            files.sort()
            return ToolOutput.ok(files)
        except Exception as e:
            return ToolOutput.fail(f"Failed to list directory: {e}")


ToolRegistry.register(FileReadTool())
ToolRegistry.register(FileWriteTool())
ToolRegistry.register(FileListTool())
