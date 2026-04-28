"""
File operations tool — read, write, list, and delete files within the workspace.

Two sandbox modes:
- Global (one-shot): sandboxed to settings.workspace_dir
- Company (persistent): sandboxed to the agent's workspace_root with RBAC
  enforced via workspace_permissions injected by BaseAgent._execute_tool().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from dri.tools.base import BaseTool, ToolOutput, ToolRegistry


def _get_workspace() -> Path:
    from dri.config.settings import get_settings
    return get_settings().workspace_dir.resolve()


def _resolve_sandbox(relative_path: str, workspace_root: str) -> Path | None:
    """Resolve path within the given workspace root. Returns None if escape attempted."""
    root = Path(workspace_root).resolve() if workspace_root else _get_workspace()
    try:
        target = (root / relative_path).resolve()
    except Exception:
        return None
    if not str(target).startswith(str(root)):
        return None
    return target


def _check_permission(
    rel_path: str,
    permissions: list[dict[str, Any]],
    operation: str,
) -> bool:
    """
    Check if `operation` (read/write/delete) is allowed on `rel_path`.
    Permissions are evaluated in order — first matching path wins.
    Empty path "" matches everything (catch-all).
    """
    for perm in permissions:
        perm_path = perm.get("path", "")
        matches = (
            perm_path == ""
            or rel_path == perm_path
            or rel_path.startswith(perm_path.rstrip("/") + "/")
        )
        if matches:
            return bool(perm.get(f"can_{operation}", False))
    return False


def _get_rel_path(target: Path, workspace_root: str) -> str:
    root = Path(workspace_root).resolve() if workspace_root else _get_workspace()
    try:
        return str(target.relative_to(root))
    except ValueError:
        return str(target)


def _audit(workspace_root: str, agent_id: str, operation: str, path: str) -> None:
    """Append one line to shared/_audit.log. Best-effort — never raises."""
    if not workspace_root:
        return
    from datetime import datetime, timezone
    try:
        audit_file = Path(workspace_root) / "shared" / "_audit.log"
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        normalized = path.replace("\\", "/")  # consistent across OS
        with audit_file.open("a", encoding="utf-8") as fh:
            fh.write(f"{ts} | {agent_id} | {operation} | {normalized}\n")
    except Exception:
        pass


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
            "path": {"type": "string", "description": "Relative path from workspace root."},
            "max_chars": {"type": "integer", "description": "Max characters to read.", "default": 10000},
        },
        "required": ["path"],
    }

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        workspace_root: str = raw_input.get("_workspace_root", "")
        permissions: list[dict] = raw_input.get("_permissions", [])
        rel = raw_input.get("path", "")
        max_chars = int(raw_input.get("max_chars", 10000))

        path = _resolve_sandbox(rel, workspace_root)
        if path is None:
            return ToolOutput.fail("Invalid path — must stay within the workspace.")

        if permissions and not _check_permission(rel, permissions, "read"):
            return ToolOutput.fail(f"Permission denied: read on '{rel}'.")

        if not path.exists():
            return ToolOutput.fail(f"File not found: {rel}")
        if not path.is_file():
            return ToolOutput.fail(f"Not a file: {rel}")

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n\n[...truncated at {max_chars} chars]"
            return ToolOutput.ok(content)
        except Exception as e:
            return ToolOutput.fail(f"Failed to read: {e}")


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
            "path": {"type": "string", "description": "Relative path from workspace root."},
            "content": {"type": "string", "description": "Content to write (UTF-8)."},
            "append": {"type": "boolean", "description": "Append instead of overwrite.", "default": False},
        },
        "required": ["path", "content"],
    }

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        workspace_root: str = raw_input.get("_workspace_root", "")
        permissions: list[dict] = raw_input.get("_permissions", [])
        rel = raw_input.get("path", "")
        content: str = raw_input.get("content", "")
        append: bool = bool(raw_input.get("append", False))

        path = _resolve_sandbox(rel, workspace_root)
        if path is None:
            return ToolOutput.fail("Invalid path — must stay within the workspace.")

        if permissions and not _check_permission(rel, permissions, "write"):
            return ToolOutput.fail(f"Permission denied: write on '{rel}'.")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with path.open(mode, encoding="utf-8") as fh:
                fh.write(content)
            rel = _get_rel_path(path, workspace_root)
            agent_id = raw_input.get("_agent_id", "unknown")
            op = "APPEND" if append else "WRITE"
            _audit(workspace_root, agent_id, op, rel)
            return ToolOutput.ok({"path": rel, "bytes": len(content.encode())})
        except Exception as e:
            return ToolOutput.fail(f"Failed to write: {e}")


class FileListTool(BaseTool):
    name = "file_list"
    description = (
        "List files in a workspace directory. "
        "Use '.' for the root. Returns file paths relative to the workspace."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path relative to workspace root.", "default": "."},
            "recursive": {"type": "boolean", "description": "List all subdirectories.", "default": False},
        },
    }

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        workspace_root: str = raw_input.get("_workspace_root", "")
        permissions: list[dict] = raw_input.get("_permissions", [])
        rel = raw_input.get("path", ".")
        recursive: bool = bool(raw_input.get("recursive", False))

        path = _resolve_sandbox(rel, workspace_root)
        if path is None:
            return ToolOutput.fail("Invalid path.")

        if permissions and not _check_permission(rel, permissions, "read"):
            return ToolOutput.fail(f"Permission denied: read on '{rel}'.")

        if not path.exists():
            return ToolOutput.fail(f"Directory not found: {rel}")
        if not path.is_dir():
            return ToolOutput.fail(f"Not a directory: {rel}")

        root = Path(workspace_root).resolve() if workspace_root else _get_workspace()
        try:
            iterator = path.rglob("*") if recursive else path.iterdir()
            files = sorted(str(f.relative_to(root)) for f in iterator if f.is_file())
            return ToolOutput.ok(files)
        except Exception as e:
            return ToolOutput.fail(f"Failed to list: {e}")


class FileDeleteTool(BaseTool):
    name = "file_delete"
    description = (
        "Delete a single file from the workspace. "
        "For deleting a folder or more than 3 files, you MUST use "
        "`propose_external_action` with action_type='bulk_file_delete' and list every "
        "file path in the `content` field — do NOT call this tool repeatedly on files "
        "in the same folder to bypass the bulk delete guard."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path of a SINGLE file to delete.",
            },
        },
        "required": ["path"],
    }

    # Per-agent-per-folder deletion counter. Key = "{agent_id}::{workspace}::{folder}".
    # Class-level dict is intentional — it's the registry. Each key is unique per agent.
    _delete_counts: dict[str, int] = {}
    _BULK_DELETE_THRESHOLD = 3

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        import shutil

        workspace_root: str = raw_input.get("_workspace_root", "")
        permissions: list[dict] = raw_input.get("_permissions", [])
        rel = raw_input.get("path", "")

        path = _resolve_sandbox(rel, workspace_root)
        if path is None:
            return ToolOutput.fail("Invalid path.")

        if permissions and not _check_permission(rel, permissions, "delete"):
            return ToolOutput.fail(f"Permission denied: delete on '{rel}'.")

        if not path.exists():
            return ToolOutput.fail(f"Not found: {rel}")

        if path.is_dir():
            files_inside = [f for f in path.rglob("*") if f.is_file()]
            if len(files_inside) > self._BULK_DELETE_THRESHOLD:
                file_list_preview = "\n".join(
                    f"  - {f.relative_to(path.parent).as_posix()}"
                    for f in sorted(files_inside)[:20]
                )
                suffix = f"\n  ... and {len(files_inside) - 20} more" if len(files_inside) > 20 else ""
                return ToolOutput.fail(
                    f"Bulk delete blocked: '{rel}' contains {len(files_inside)} files — "
                    f"above the {self._BULK_DELETE_THRESHOLD}-file threshold.\n\n"
                    f"Files that would be deleted:\n{file_list_preview}{suffix}\n\n"
                    "Use `propose_external_action` with action_type='bulk_file_delete':\n"
                    "  - content: list every file path\n"
                    "  - rationale: why each file is obsolete\n"
                    "Do NOT delete these files one by one to bypass this guard."
                )
            try:
                shutil.rmtree(str(path))
                _audit(workspace_root, raw_input.get("_agent_id", "unknown"), "DELETE_DIR", rel)
                return ToolOutput.ok({"deleted": rel, "type": "directory", "files_removed": len(files_inside)})
            except Exception as e:
                return ToolOutput.fail(f"Failed to delete directory: {e}")

        if not path.is_file():
            return ToolOutput.fail(f"Not a file or directory: {rel}")

        # Single file delete — track per agent per folder to detect looped bypass.
        # Keyed by agent ID so concurrent agents don't pollute each other's counters.
        agent_id = raw_input.get("_agent_id", "unknown")
        parent_key = f"{agent_id}::{workspace_root}::{path.parent.as_posix()}"
        self._delete_counts[parent_key] = self._delete_counts.get(parent_key, 0) + 1
        count = self._delete_counts[parent_key]

        if count > self._BULK_DELETE_THRESHOLD:
            return ToolOutput.fail(
                f"Bulk delete bypass detected: you have now deleted {count} files from "
                f"'{path.parent.relative_to(Path(workspace_root).resolve()).as_posix() if workspace_root else rel}' "
                f"in this session — above the {self._BULK_DELETE_THRESHOLD}-file threshold.\n"
                "Stop deleting individual files. Use `propose_external_action` with "
                "action_type='bulk_file_delete' to list the remaining files for founder approval."
            )

        try:
            path.unlink()
            _audit(workspace_root, agent_id, "DELETE", rel)
            return ToolOutput.ok({"deleted": rel, "type": "file"})
        except Exception as e:
            return ToolOutput.fail(f"Failed to delete: {e}")


ToolRegistry.register(FileReadTool())
ToolRegistry.register(FileWriteTool())
ToolRegistry.register(FileListTool())
ToolRegistry.register(FileDeleteTool())
