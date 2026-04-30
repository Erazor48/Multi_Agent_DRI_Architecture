"""
Shell execution tool — run system commands within the company workspace.

Commands are sandboxed by cwd (always resolved inside workspace root).
The executable allowlist prevents dangerous system operations.
No shell=True — args are parsed with shlex to prevent injection.
"""
from __future__ import annotations

import asyncio
import shlex
import sys
from pathlib import Path
from typing import Any

from dri.tools.base import BaseTool, ToolOutput, ToolRegistry


_EXEC_TIMEOUT = 120
_MAX_OUTPUT_CHARS = 20_000

# Only these executables may be invoked.
# Extend here if new tools are validated by the project owner.
_ALLOWED_EXECUTABLES: frozenset[str] = frozenset({
    # JavaScript / Node ecosystem
    "bun", "bunx",
    "npx", "npm", "node",
    # Python ecosystem
    "uv", "python", "python3",
    # Media processing
    "ffmpeg", "ffprobe",
    # Version control
    "git",
    # Image processing (ImageMagick v6 / v7)
    "magick", "convert",
    # HTTP requests — read-only, no system writes
    "curl", "wget",
})

# Git subcommands that destroy working-tree content unconditionally.
# These are blocked outright — no approval path.
_GIT_BLOCKED_SUBCOMMANDS: frozenset[str] = frozenset({
    "clean",    # deletes all untracked/ignored files — irreversible
    "rm",       # removes files from the index and disk
    "restore",  # discards uncommitted working-tree changes
})

# For `git reset`, only --hard / --mixed are destructive (touch working tree / index).
# --soft only moves HEAD and is safe.
_GIT_RESET_DESTRUCTIVE_FLAGS: frozenset[str] = frozenset({"--hard", "--mixed"})

# `git checkout -- <path>` discards uncommitted changes; detect the separator.
# `git checkout <branch>` is safe — only blocked when `--` is present (file-mode).
_GIT_CHECKOUT_DISCARD_FLAG = "--"


def _get_workspace() -> Path:
    from dri.config.settings import get_settings
    return get_settings().workspace_dir.resolve()


def _resolve_cwd(relative: str, workspace_root: str) -> Path | None:
    """Resolve a cwd path strictly inside workspace_root. Returns None on escape attempt."""
    root = Path(workspace_root).resolve() if workspace_root else _get_workspace()
    try:
        target = (root / (relative or ".")).resolve()
    except Exception:
        return None
    if not str(target).startswith(str(root)):
        return None
    return target


class ShellExecTool(BaseTool):
    name = "shell_exec"
    description = (
        "Run a shell command within the company workspace (cwd is always sandboxed inside the workspace). "
        f"Allowed executables: {', '.join(sorted(_ALLOWED_EXECUTABLES))}. "
        "IMPORTANT: set 'cwd' to the project subfolder for all project commands "
        "(e.g. 'developpement-nextjs/my-app'). "
        "stdout and stderr are captured and returned. Default timeout 120s, max 300s.\n\n"
        "## Next.js + shadcn/ui workflow (exact commands)\n"
        "# 1. Scaffold (run once from dept folder):\n"
        "bun create next-app@latest my-app --typescript --tailwind --eslint --app --src-dir --import-alias '@/*' --yes\n"
        "# 2. Init shadcn (run once inside project dir, cwd=dept/my-app):\n"
        "bunx shadcn@latest init --defaults --yes\n"
        "# 3. Add components (always pass --yes to avoid interactive prompt):\n"
        "bunx shadcn@latest add button card input table dialog form --yes\n"
        "# 4. Install packages:\n"
        "bun install\n"
        "bun add <package-name>\n"
        "# 5. Build (MANDATORY after every change — fix all errors before reporting done):\n"
        "bun run build\n\n"
        "## Other examples\n"
        "ffmpeg -i input.mp4 -vf scale=1280:720 output.mp4\n"
        "curl -L https://example.com/file.zip -o shared/file.zip\n"
        "wget https://example.com/image.png -O shared/image.png\n"
        "uv run script.py\n"
        "git add -A && git commit -m 'feat: initial scaffold'\n\n"
        "RULE: always pass --yes / --defaults / --no-interactive to any CLI tool "
        "that has interactive prompts — the shell has no stdin."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "Command to execute — must start with an allowed executable. "
                    "Example: 'bun create next-app@latest my-app --yes'"
                ),
            },
            "cwd": {
                "type": "string",
                "description": (
                    "Working directory relative to workspace root. "
                    "Created automatically if it does not exist. "
                    "Defaults to workspace root ('.')."
                ),
                "default": ".",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (1–300). Default: 120.",
                "default": 120,
                "minimum": 1,
                "maximum": 300,
            },
        },
        "required": ["command"],
    }

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        workspace_root: str = raw_input.get("_workspace_root", "")
        command: str = raw_input.get("command", "").strip()
        cwd_rel: str = raw_input.get("cwd", ".")
        timeout: int = min(int(raw_input.get("timeout", _EXEC_TIMEOUT)), 300)

        if not command:
            return ToolOutput.fail("No command provided.")

        # Parse safely — never use shell=True
        try:
            args = shlex.split(command, posix=True)
        except ValueError as e:
            return ToolOutput.fail(f"Invalid command syntax: {e}")

        if not args:
            return ToolOutput.fail("Empty command after parsing.")

        # Allowlist check — strip .exe suffix on Windows
        exe_name = Path(args[0]).name.lower()
        if sys.platform == "win32" and exe_name.endswith(".exe"):
            exe_name = exe_name[:-4]
        if exe_name not in _ALLOWED_EXECUTABLES:
            return ToolOutput.fail(
                f"Executable '{args[0]}' is not in the allowlist. "
                f"Allowed: {', '.join(sorted(_ALLOWED_EXECUTABLES))}."
            )

        # Git destructive subcommand guard — these operations destroy workspace content
        # and require explicit founder approval via propose_external_action.
        if exe_name == "git" and len(args) >= 2:
            subcmd = args[1].lower()
            if subcmd in _GIT_BLOCKED_SUBCOMMANDS:
                return ToolOutput.fail(
                    f"'git {subcmd}' is blocked — this command can permanently delete workspace files. "
                    "If cleanup is truly needed, use propose_external_action with "
                    "action_type='bulk_file_delete' to request founder approval, listing every file "
                    "with its rationale."
                )
            if subcmd == "reset" and any(f in args[2:] for f in _GIT_RESET_DESTRUCTIVE_FLAGS):
                destructive_flag = next(f for f in args[2:] if f in _GIT_RESET_DESTRUCTIVE_FLAGS)
                return ToolOutput.fail(
                    f"'git reset {destructive_flag}' is blocked — this discards uncommitted work. "
                    "Use 'git reset --soft' if you only need to move HEAD without touching files."
                )
            if subcmd == "checkout" and _GIT_CHECKOUT_DISCARD_FLAG in args[2:]:
                return ToolOutput.fail(
                    "'git checkout --' is blocked — this discards uncommitted file changes. "
                    "If you need to revert specific files, use propose_external_action for approval."
                )

        # Resolve cwd — must stay inside workspace
        cwd = _resolve_cwd(cwd_rel, workspace_root)
        if cwd is None:
            return ToolOutput.fail("cwd escapes the workspace boundary — rejected.")
        cwd.mkdir(parents=True, exist_ok=True)

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return ToolOutput.fail(f"Command timed out after {timeout}s.")
        except FileNotFoundError:
            return ToolOutput.fail(
                f"Executable '{args[0]}' not found on this system. "
                "Make sure it is installed and available in PATH."
            )
        except Exception as e:
            return ToolOutput.fail(f"Subprocess error: {e}")

        stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()

        # Truncate large outputs to protect context window
        if len(stdout_str) > _MAX_OUTPUT_CHARS:
            stdout_str = stdout_str[:_MAX_OUTPUT_CHARS] + f"\n[...stdout truncated at {_MAX_OUTPUT_CHARS} chars]"
        if len(stderr_str) > _MAX_OUTPUT_CHARS:
            stderr_str = stderr_str[:_MAX_OUTPUT_CHARS] + f"\n[...stderr truncated at {_MAX_OUTPUT_CHARS} chars]"

        parts: list[str] = []
        if stdout_str:
            parts.append(stdout_str)
        if stderr_str:
            parts.append(f"[stderr]:\n{stderr_str}")
        output = "\n".join(parts) if parts else "(no output)"

        if proc.returncode != 0:
            return ToolOutput.fail(
                f"Command exited with code {proc.returncode}.\n{output}"
            )

        return ToolOutput.ok(output)


ToolRegistry.register(ShellExecTool())
