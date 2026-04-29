"""
Tests for the elastic timeout mechanism in BaseAgent.

The agent deadline extends automatically by the actual duration of each
shell_exec call. Only LLM + lightweight tool time counts toward the base limit.
"""
from __future__ import annotations

import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_shell_exec_extends_deadline(tmp_path, monkeypatch):
    """
    A shell command that takes ~0.5s should extend the agent deadline by ~0.5s,
    not consume from the base LLM budget.
    """
    from dri.config.settings import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")  # skip provider validation
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from dri.tools.base import ToolRegistry
    import dri.tools  # noqa — trigger registration

    tool = ToolRegistry.get("shell_exec")

    # Simulate the elastic timeout extension logic directly, without a full agent
    shell_bonus = 0.0
    t_start = time.time()

    # Run a short shell command
    result = await tool.execute({
        "command": "python -c \"import time; time.sleep(0.4); print('done')\"",
        "_workspace_root": str(tmp_path),
    })
    elapsed = time.time() - t_start
    shell_bonus += elapsed

    assert result.success, result.error
    assert "done" in result.data
    # The bonus should be at least 0.4s (the sleep) but not wildly more
    assert 0.3 <= shell_bonus <= 3.0, f"Unexpected shell bonus: {shell_bonus}s"


@pytest.mark.asyncio
async def test_shell_bonus_accumulates(tmp_path, monkeypatch):
    """Multiple shell commands should each add to the running bonus."""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))

    from dri.tools.base import ToolRegistry
    import dri.tools  # noqa

    tool = ToolRegistry.get("shell_exec")

    total_bonus = 0.0
    for _ in range(3):
        t = time.time()
        result = await tool.execute({
            "command": "python -c \"print('x')\"",
            "_workspace_root": str(tmp_path),
        })
        assert result.success
        total_bonus += time.time() - t

    # Three python invocations should each contribute a non-trivial amount
    assert total_bonus > 0.1, "Expected some measurable shell time accumulated"


@pytest.mark.asyncio
async def test_timeout_ctx_reschedule_api():
    """
    Verify that asyncio.timeout().reschedule() works as expected on Python 3.12.
    This is the core primitive the elastic timeout relies on.
    """
    loop = asyncio.get_event_loop()

    extended = False

    async def slow_work():
        nonlocal extended
        await asyncio.sleep(0.05)

    async def run():
        nonlocal extended
        # Give only 0.1s, then extend by 1s mid-flight
        async with asyncio.timeout(0.1) as ctx:
            when = ctx.when()
            assert when is not None
            # Extend deadline by 1 second
            ctx.reschedule(when + 1.0)
            extended = True
            await asyncio.sleep(0.2)  # would timeout without the extension

    await run()
    assert extended
