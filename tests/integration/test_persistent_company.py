"""
Integration tests — persistent company workflow with mocked LLM.

Covers:
- CompanyExecutor.create(): company design + workspace scaffold
- CompanyExecutor.task(): task force execution (CEO → manager → worker chain)
- Audit log written on file ops
- Approval queue written by propose_external_action

Does NOT make real API calls — LLM is mocked at the provider level.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dri.llm.base import LLMResponse, ToolCall
from dri.storage.database import drop_db, init_db


# ── Helpers ────────────────────────────────────────────────────────────────────

def _text(text: str) -> LLMResponse:
    return LLMResponse(text=text, input_tokens=100, output_tokens=50)


def _tool(name: str, inp: dict) -> LLMResponse:
    return LLMResponse(
        text="",
        tool_calls=[ToolCall(id=f"call_{name}", name=name, input=inp)],
        input_tokens=200,
        output_tokens=100,
        stop_reason="tool_use",
    )


def _make_provider(responses: list[LLMResponse]) -> MagicMock:
    """Build a mock provider that returns responses in sequence (repeats last)."""
    idx = 0

    async def _call(**kwargs) -> LLMResponse:
        nonlocal idx
        resp = responses[min(idx, len(responses) - 1)]
        idx += 1
        return resp

    p = MagicMock()
    p.call = _call
    return p


def _patch_all_providers(provider: MagicMock):
    """
    Context manager that patches create_provider in every module that imports it.

    unittest.mock.patch replaces the name WHERE IT IS LOOKED UP (not where defined).
    Agents import create_provider into dri.agents.base, the CEO loop imports it into
    dri.orchestration.company_executor — both must be patched to the same instance.
    """
    from contextlib import ExitStack
    from unittest.mock import patch

    stack = ExitStack()
    for target in (
        "dri.agents.base.create_provider",
        "dri.orchestration.company_executor.create_provider",
    ):
        stack.enter_context(patch(target, return_value=provider))
    return stack


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
async def clean_db():
    from dri.storage.database import reset_engine
    reset_engine(test_db_url="sqlite+aiosqlite:///:memory:")
    await init_db()
    yield
    await drop_db()
    reset_engine()


@pytest.fixture
def workspace(tmp_path):
    """
    Override the settings singleton's workspace_dir to a temp directory.
    The singleton is imported at module level everywhere, so we patch the attribute
    directly rather than using monkeypatch.setenv (which only affects re-construction).
    """
    from dri.config.settings import settings as _s
    original = _s.workspace_dir
    _s.workspace_dir = tmp_path  # type: ignore[misc]
    tmp_path.mkdir(parents=True, exist_ok=True)
    yield tmp_path
    _s.workspace_dir = original  # type: ignore[misc]


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_company_create_scaffolds_workspace(workspace):
    """CompanyExecutor.create() must scaffold the workspace directories."""
    provider = _make_provider([_tool("design_company", {
        "company_name": "AcmeTest",
        "company_vision": "Test everything.",
        "departments": [{"title": "Chief Marketing Officer", "mission": "Market things."}],
    })])

    with _patch_all_providers(provider):
        from dri.orchestration.company_executor import CompanyExecutor
        company = await CompanyExecutor.create("Build a test company.")

    assert company.name == "AcmeTest"
    ws = workspace / "acmetest"
    assert (ws / "shared").is_dir()
    assert (ws / "chief-marketing-officer").is_dir()


@pytest.mark.asyncio
async def test_task_force_creates_files(workspace):
    """
    task() must run a manager→worker chain that writes a file to the workspace.
    Audit log must be created.
    """
    # 1) Create company
    create_provider = _make_provider([_tool("design_company", {
        "company_name": "FileTest",
        "company_vision": "Write files.",
        "departments": [{"title": "Operations", "mission": "Handle ops."}],
    })])
    with _patch_all_providers(create_provider):
        from dri.orchestration.company_executor import CompanyExecutor
        company = await CompanyExecutor.create("Write some files.")

    ws = workspace / "filetest"

    # 2) Run task force: manager plans one worker, worker writes a file, manager synthesizes.
    # Sequence: plan→write→worker_done→synthesis (manager reads file, then returns text).
    task_provider = _make_provider([
        _tool("create_org_plan", {
            "team_members": [{
                "title": "Writer",
                "role": "worker",
                "mission": "Write the report.",
                "task": "Write shared/report.md with content 'Hello from worker'.",
                "tools": ["file_write"],
                "budget_share": 1.0,
            }],
            "synthesis_approach": "Return worker output.",
        }),
        _tool("file_write", {"path": "shared/report.md", "content": "Hello from worker"}),
        _text("File written successfully."),
        _tool("file_read", {"path": "shared/report.md"}),  # manager synthesis reads the file
        _text("Report complete: Hello from worker."),
    ])

    with _patch_all_providers(task_provider):
        statuses: list[str] = []
        result = await CompanyExecutor.task(
            company.id,
            "Write a report.",
            on_status=lambda m: statuses.append(m),
        )

    assert result, "Task force must return a non-empty result"
    report = ws / "shared" / "report.md"
    assert report.exists(), "Worker must have written shared/report.md"
    assert "Hello" in report.read_text(encoding="utf-8")
    audit = ws / "shared" / "_audit.log"
    assert audit.exists(), "Audit log must be created on file write"
    log_content = audit.read_text(encoding="utf-8")
    assert "WRITE" in log_content
    assert "shared/report.md" in log_content


@pytest.mark.asyncio
async def test_external_action_logged_to_approval_queue(workspace):
    """
    propose_external_action must write to _pending_approvals.json with a UUID id.
    """
    # Create company
    create_p = _make_provider([_tool("design_company", {
        "company_name": "ActionTest",
        "company_vision": "Send emails.",
        "departments": [{"title": "Marketing", "mission": "Do outreach."}],
    })])
    with _patch_all_providers(create_p):
        from dri.orchestration.company_executor import CompanyExecutor
        company = await CompanyExecutor.create("Send an email.")

    ws = workspace / "actiontest"

    task_provider = _make_provider([
        _tool("create_org_plan", {
            "team_members": [{
                "title": "Outreach Agent",
                "role": "worker",
                "mission": "Send an email.",
                "task": "Propose an email to client@example.com.",
                "tools": ["propose_external_action"],
                "budget_share": 1.0,
            }],
            "synthesis_approach": "Report approval queue status.",
        }),
        _tool("propose_external_action", {
            "action_type": "email",
            "recipient": "client@example.com",
            "subject": "Hello",
            "content": "Dear client, we are reaching out.",
            "rationale": "Initial outreach to potential customer.",
        }),
        _text("Email proposed. Action pending approval."),
        _text("Outreach action queued for founder approval."),
    ])

    with _patch_all_providers(task_provider):
        result = await CompanyExecutor.task(company.id, "Send outreach email.")

    assert result

    pending_file = ws / "shared" / "_pending_approvals.json"
    assert pending_file.exists(), "Approval queue must be created"
    actions = json.loads(pending_file.read_text(encoding="utf-8"))
    assert len(actions) == 1
    action = actions[0]
    assert action["status"] == "pending"
    assert action["action_type"] == "email"
    assert isinstance(action["id"], str) and len(action["id"]) == 36, "ID must be a UUID string"


@pytest.mark.asyncio
async def test_context_pruning_does_not_break_loop(workspace):
    """
    An agentic loop with more than _MAX_HISTORY_ROUNDS rounds must still complete
    (context pruning must not corrupt message ordering).
    """
    # Create a company first
    create_p = _make_provider([_tool("design_company", {
        "company_name": "PruneTest",
        "company_vision": "Test pruning.",
        "departments": [{"title": "Ops", "mission": "Ops things."}],
    })])
    with _patch_all_providers(create_p):
        from dri.orchestration.company_executor import CompanyExecutor
        company = await CompanyExecutor.create("Test context pruning.")

    # Worker does 10 file_list calls (> _MAX_HISTORY_ROUNDS=8), then returns text.
    # Pruning must silently drop old rounds without crashing.
    list_call = _tool("file_list", {"path": "."})
    task_provider = _make_provider(
        [_tool("create_org_plan", {
            "team_members": [{
                "title": "Looping Worker",
                "role": "worker",
                "mission": "Call file_list many times.",
                "task": "List the workspace 10 times.",
                "tools": ["file_list"],
                "budget_share": 1.0,
            }],
            "synthesis_approach": "Confirm worker completed.",
        })]
        + [list_call] * 10
        + [_text("Done listing."), _text("Synthesis complete.")]
    )

    with _patch_all_providers(task_provider):
        result = await CompanyExecutor.task(company.id, "List files many times.")

    assert result
