"""
Code execution tool — runs Python in a sandboxed subprocess.
Timeout-protected, stdout/stderr captured, no network access from within.
"""
from __future__ import annotations

import asyncio
import sys
import textwrap
from typing import Any

from dri.tools.base import BaseTool, ToolOutput, ToolRegistry


_EXEC_TIMEOUT = 30  # seconds


class CodeExecTool(BaseTool):
    name = "code_exec"
    description = (
        "Execute Python 3 code and return the output (stdout + stderr). "
        "Use for calculations, data processing, file generation, and verification. "
        "Code runs in an isolated subprocess with a 30-second timeout. "
        "Import standard library modules freely. Third-party packages available: "
        "requests, pandas, numpy, matplotlib (headless)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Valid Python 3 code to execute. Use print() to produce output.",
            },
            "timeout": {
                "type": "integer",
                "description": "Execution timeout in seconds (max 30).",
                "default": 30,
                "minimum": 1,
                "maximum": 30,
            },
        },
        "required": ["code"],
    }

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        code: str = raw_input.get("code", "").strip()
        timeout: int = min(int(raw_input.get("timeout", _EXEC_TIMEOUT)), _EXEC_TIMEOUT)

        if not code:
            return ToolOutput.fail("No code provided.")

        # Wrap to capture both stdout and stderr cleanly
        wrapped = textwrap.dedent(code)

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                wrapped,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return ToolOutput.fail(f"Code execution timed out after {timeout}s.")
        except Exception as e:
            return ToolOutput.fail(f"Subprocess error: {e}")

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            error_msg = stderr_str or f"Process exited with code {proc.returncode}"
            return ToolOutput.fail(f"Runtime error:\n{error_msg}")

        output = stdout_str
        if stderr_str:
            output = f"{stdout_str}\n[stderr]: {stderr_str}" if stdout_str else f"[stderr]: {stderr_str}"

        return ToolOutput.ok(output or "(no output)")


ToolRegistry.register(CodeExecTool())
