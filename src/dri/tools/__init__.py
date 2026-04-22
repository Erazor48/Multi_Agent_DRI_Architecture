"""
Import all tools to trigger their ToolRegistry.register() calls.
Any module that needs the tool registry populated should import this package.
"""
from dri.tools import code_exec, file_ops, web_search  # noqa: F401
from dri.tools.base import BaseTool, ToolOutput, ToolRegistry

__all__ = ["BaseTool", "ToolOutput", "ToolRegistry"]
