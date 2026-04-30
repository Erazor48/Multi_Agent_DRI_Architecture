"""
Rich-based CLI — the only user-facing interface.
User speaks to this. Everything else is automated.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime

import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text

app = typer.Typer(name="dri", help="DRI Multi-Agent Company System", no_args_is_help=False)
# Disable legacy Windows console rendering (uses Win32 API limited to cp1252).
# Modern Windows 10/11 terminals support ANSI + UTF-8 natively.
if sys.platform == "win32":
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
console = Console(highlight=False, legacy_windows=False)


def _print_banner() -> None:
    console.print()
    console.print(
        Panel.fit(
            "[bold blue]DRI Multi-Agent Company System[/bold blue]\n"
            "[dim]Pitch your idea. Watch your company build itself.[/dim]",
            border_style="blue",
        )
    )
    console.print()


def _render_progress_panel(lines: list[str]) -> Panel:
    """Render agent tool-call activity as a color-coded live panel."""
    if not lines:
        return Panel(
            Text("  Working...", style="dim"),
            title="[bold]Team Activity[/bold]", border_style="blue", padding=(0, 1),
        )
    text = Text()
    for line in lines[-10:]:
        if "shell_exec" in line:
            text.append(f"  {line}\n", style="yellow")
        elif "web_search" in line:
            text.append(f"  {line}\n", style="cyan")
        elif "file_write" in line or "file_read" in line:
            text.append(f"  {line}\n", style="green")
        elif "spawn" in line.lower():
            text.append(f"  {line}\n", style="bold blue")
        else:
            text.append(f"  {line}\n", style="dim")
    return Panel(text, title="[bold]Team Activity[/bold]", border_style="blue", padding=(0, 1))


def _print_result(result: str) -> None:
    console.print()
    console.print(Rule("[bold green]Company Report[/bold green]", style="green"))
    console.print()
    console.print(Markdown(result))
    console.print()
    console.print(Rule(style="green"))
    console.print()


@app.command()
def run(
    pitch: str = typer.Option("", "--pitch", "-p", help="Company pitch (skip interactive prompt)"),
    budget: int = typer.Option(0, "--budget", "-b", help="Override session token budget"),
) -> None:
    """Launch a new company session."""
    _print_banner()

    # Override budget if provided
    if budget > 0:
        import os
        os.environ["BUDGET_MAX_TOKENS_PER_SESSION"] = str(budget)
        # Re-init settings singleton with new budget
        from dri.config.settings import get_settings
        get_settings.cache_clear()

    if not pitch:
        console.print("[bold]Describe your company idea:[/bold]")
        console.print("[dim]Be specific: what it does, who it's for, what makes it unique.[/dim]")
        console.print()
        pitch = Prompt.ask("[green]>[/green]")
        console.print()

    if not pitch.strip():
        console.print("[red]No pitch provided. Exiting.[/red]")
        raise typer.Exit(1)

    status_messages: list[str] = []

    def _on_status(msg: str) -> None:
        status_messages.append(msg)

    console.print(Panel(
        f"[italic]{pitch}[/italic]",
        title="[bold]Your Pitch[/bold]",
        border_style="dim",
    ))
    console.print()

    start_time = datetime.now()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Building your company...", total=None)

        async def _run() -> str:
            from dri.orchestration.executor import Executor

            executor = Executor()

            def _status_update(msg: str) -> None:
                progress.update(task, description=msg)
                _on_status(msg)

            return await executor.run(pitch, on_status=_status_update)

        try:
            result = asyncio.run(_run())
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
            raise typer.Exit(0)
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            if "--debug" in sys.argv:
                import traceback
                traceback.print_exc()
            raise typer.Exit(1)

    elapsed = (datetime.now() - start_time).total_seconds()
    console.print(f"[dim]Completed in {elapsed:.1f}s[/dim]")

    _print_result(result)


@app.command()
def org() -> None:
    """Show the org chart of the last session."""
    console.print("[dim]Org chart view — coming soon.[/dim]")


# ── Persistent company commands ────────────────────────────────────────────────

company_app = typer.Typer(name="company", help="Manage persistent companies.")
app.add_typer(company_app, name="company")


async def _resolve_company(company_id: str) -> "PersistentCompany | None":  # type: ignore[name-defined]
    """
    Resolve which company to use, in priority order:
      1. Explicit --id argument
      2. Active company from .dri_state
      3. Most recently created (get_latest fallback)
    """
    from dri.config.state import get_active_company_id
    from dri.storage.database import init_db, get_session
    from dri.storage.repositories import PersistentCompanyRepository

    await init_db()
    async with get_session() as db:
        repo = PersistentCompanyRepository(db)
        if company_id:
            return await repo.get(company_id)
        active_id = get_active_company_id()
        if active_id:
            c = await repo.get(active_id)
            if c is not None:
                return c
        return await repo.get_latest()


@company_app.command("create")
def company_create(
    pitch: str = typer.Option("", "--pitch", "-p", help="Company pitch"),
) -> None:
    """Create a new persistent company."""
    _print_banner()
    if not pitch:
        console.print("[bold]Describe your company:[/bold]")
        pitch = typer.prompt(">")
    if not pitch.strip():
        console.print("[red]No pitch provided.[/red]")
        raise typer.Exit(1)

    console.print(Panel(f"[italic]{pitch}[/italic]", title="[bold]Your Pitch[/bold]", border_style="dim"))

    async def _run() -> "PersistentCompany":  # type: ignore[name-defined]
        from dri.orchestration.company_executor import CompanyExecutor
        return await CompanyExecutor.create(pitch, on_status=lambda _: None)

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console) as p:
        p.add_task("Creating company...", total=None)
        try:
            company = asyncio.run(_run())
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)

    console.print()
    console.print(Panel(
        f"[bold green]{company.name}[/bold green]\n"
        f"[dim]{company.vision}[/dim]\n\n"
        f"[bold]Departments:[/bold]\n" +
        "\n".join(f"  • {d['title']}" for d in company.org_structure) +
        f"\n\n[dim]ID: {company.id}[/dim]",
        title="[bold]Company Created[/bold]",
        border_style="green",
    ))
    # Automatically set as active company so the user can skip --id immediately
    from dri.config.state import set_active_company_id
    set_active_company_id(company.id)
    console.print("\n[dim]Use [bold]dri company chat[/bold] to start working with your CEO.[/dim]")
    console.print(f"[dim]This company is now your active company. Switch with [bold]dri company use[/bold].[/dim]")


@company_app.command("list")
def company_list() -> None:
    """List all persistent companies. The active company is marked with [active]."""
    async def _run() -> None:
        from dri.config.state import get_active_company_id
        from dri.storage.database import init_db, get_session
        from dri.storage.repositories import PersistentCompanyRepository
        from dri.orchestration.company_executor import CompanyExecutor
        from rich.table import Table

        await init_db()
        async with get_session() as db:
            repo = PersistentCompanyRepository(db)
            companies = await repo.list_active()

        # Check for orphan workspaces in parallel with listing
        orphans = await CompanyExecutor.recover_scan()

        if not companies:
            console.print("[dim]No persistent companies found. Use [bold]dri company create[/bold].[/dim]")
            if orphans:
                console.print(
                    f"\n[yellow]⚠ {len(orphans)} orphan workspace(s) found on disk with no DB record:[/yellow]"
                )
                for o in orphans:
                    console.print(f"  [dim]• {o.folder_name}[/dim] → [bold]{o.inferred_name}[/bold]")
                console.print("[dim]Run [bold]dri company recover[/bold] to re-import them.[/dim]")
            return

        active_id = get_active_company_id()
        table = Table(title="Your Companies", show_lines=True)
        table.add_column("", width=2)  # active indicator
        table.add_column("ID", style="dim", width=10)
        table.add_column("Name", style="bold")
        table.add_column("Vision")
        table.add_column("Depts", justify="right")
        table.add_column("Created", style="dim")

        for c in companies:
            is_active = c.id == active_id
            indicator = "[bold green]*[/bold green]" if is_active else ""
            name = f"[bold green]{c.name}[/bold green]" if is_active else c.name
            table.add_row(
                indicator,
                c.id[:8] + "...",
                name,
                c.vision[:55] + "..." if len(c.vision) > 55 else c.vision,
                str(len(c.org_structure)),
                c.created_at.strftime("%Y-%m-%d %H:%M"),
            )
        console.print(table)
        if active_id:
            console.print("[dim]* = active company  |  [bold]dri company use <name-or-id>[/bold] to switch[/dim]")
        else:
            console.print("[dim]No active company set. Use [bold]dri company use <name-or-id>[/bold].[/dim]")

        if orphans:
            console.print(
                f"\n[yellow]⚠ {len(orphans)} orphan workspace(s) not in DB:[/yellow] "
                + ", ".join(o.folder_name for o in orphans)
                + " — run [bold]dri company recover[/bold]"
            )

    asyncio.run(_run())


@company_app.command("use")
def company_use(
    target: str = typer.Argument("", help="Company name (partial match) or ID prefix. Omit to show current."),
) -> None:
    """Set the active company (used by default when --id is not specified)."""
    async def _run() -> None:
        from dri.config.state import get_active_company_id, set_active_company_id
        from dri.storage.database import init_db, get_session
        from dri.storage.repositories import PersistentCompanyRepository

        await init_db()
        async with get_session() as db:
            repo = PersistentCompanyRepository(db)
            companies = await repo.list_active()

        if not target.strip():
            active_id = get_active_company_id()
            if not active_id:
                console.print("[dim]No active company. Use [bold]dri company use <name-or-id>[/bold].[/dim]")
                return
            match = next((c for c in companies if c.id == active_id), None)
            if match:
                console.print(f"Active company: [bold green]{match.name}[/bold green] [dim]({match.id[:8]}...)[/dim]")
            else:
                console.print(f"[yellow]Active ID {active_id[:8]}... not found in DB (stale state).[/yellow]")
            return

        q = target.strip().lower()
        match = next(
            (c for c in companies if q in c.id.lower() or q in c.name.lower()),
            None,
        )
        if match is None:
            console.print(f"[red]No company matching '{target}'. Run [bold]dri company list[/bold] to see options.[/red]")
            raise typer.Exit(1)

        set_active_company_id(match.id)
        console.print(f"Active company set to [bold green]{match.name}[/bold green] [dim]({match.id[:8]}...)[/dim]")
        console.print("[dim]All commands now default to this company.[/dim]")

    asyncio.run(_run())


@company_app.command("chat")
def company_chat(
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
) -> None:
    """Start an interactive session with your company CEO."""

    async def _session() -> None:
        from dri.orchestration.company_executor import CompanyExecutor

        c = await _resolve_company(company_id)
        if c is None:
            console.print("[red]No company found. Use [bold]dri company create[/bold] first.[/red]")
            console.print("[dim]Or set an active company with [bold]dri company use <name-or-id>[/bold].[/dim]")
            return

        cid, cname = c.id, c.name

        console.print()
        console.print(Panel(
            f"[bold blue]{cname}[/bold blue]\n[dim]Type your message. [bold]/quit[/bold] to exit.[/dim]",
            border_style="blue",
        ))
        console.print()

        while True:
            try:
                user_input = await asyncio.to_thread(console.input, "[green]You[/green]: ")
            except (KeyboardInterrupt, EOFError):
                break

            if user_input.strip().lower() in ("/quit", "/exit", "exit", "quit"):
                break
            if not user_input.strip():
                continue

            _prog_lines: list[str] = []
            with Live(_render_progress_panel([]), console=console, refresh_per_second=4, transient=True) as live:
                def _upd(m: str) -> None:
                    _prog_lines.append(m)
                    live.update(_render_progress_panel(_prog_lines))

                try:
                    reply = await CompanyExecutor.chat(cid, user_input, on_status=_upd)
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                    continue

            console.print()
            console.print(f"[bold blue]{cname} CEO[/bold blue]")
            console.print(Markdown(reply))
            console.print()

    asyncio.run(_session())


@company_app.command("task")
def company_task(
    task: str = typer.Option(..., "--task", "-t", help="Task to execute"),
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
) -> None:
    """Spawn a team to execute a task for your company."""
    async def _run() -> str:
        from dri.orchestration.company_executor import CompanyExecutor
        c = await _resolve_company(company_id)
        if c is None:
            raise ValueError("No company found. Use 'dri company create' or 'dri company use'.")
        _prog_lines: list[str] = []
        with Live(_render_progress_panel([]), console=console, refresh_per_second=4, transient=True) as live:
            def _upd(m: str) -> None:
                _prog_lines.append(m)
                live.update(_render_progress_panel(_prog_lines))
            return await CompanyExecutor.task(c.id, task, on_status=_upd)

    try:
        result = asyncio.run(_run())
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    _print_result(result)


# ── Approvals commands ─────────────────────────────────────────────────────────

approvals_app = typer.Typer(name="approvals", help="Review and decide on pending external actions.")
company_app.add_typer(approvals_app, name="approvals")


def _load_pending(workspace_root: str) -> tuple[list[dict], str]:
    """Load pending approvals file. Returns (actions, file_path)."""
    import json
    from pathlib import Path
    pending_file = Path(workspace_root) / "shared" / "_pending_approvals.json"
    if not pending_file.exists():
        return [], str(pending_file)
    try:
        return json.loads(pending_file.read_text(encoding="utf-8")), str(pending_file)
    except Exception:
        return [], str(pending_file)


def _save_pending(workspace_root: str, actions: list[dict]) -> None:
    import json
    from pathlib import Path
    pending_file = Path(workspace_root) / "shared" / "_pending_approvals.json"
    pending_file.write_text(json.dumps(actions, indent=2, ensure_ascii=False), encoding="utf-8")


async def _get_workspace(company_id: str) -> str | None:
    import re
    from dri.config.settings import get_settings
    c = await _resolve_company(company_id)
    if c is None:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", c.name.lower()).strip("-")
    return str(get_settings().workspace_dir / slug)


@approvals_app.command("list")
def approvals_list(
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
    all_: bool = typer.Option(False, "--all", "-a", help="Show decided actions too"),
) -> None:
    """List pending external actions awaiting founder approval."""
    from rich.table import Table

    async def _run() -> tuple[list[dict], str | None]:
        ws = await _get_workspace(company_id)
        if ws is None:
            return [], None
        actions, _ = _load_pending(ws)
        return actions, ws

    actions, ws = asyncio.run(_run())

    if ws is None:
        console.print("[red]No company found. Use [bold]dri company create[/bold] first.[/red]")
        raise typer.Exit(1)

    has_pending = any(a["status"] == "pending" for a in actions)

    if not all_ and not has_pending:
        console.print("[dim]No pending approvals.[/dim]")
        console.print("[dim]Use --all to see decided actions.[/dim]")
        return

    if all_ and not actions:
        console.print("[dim]No approvals yet.[/dim]")
        return

    table = Table(title="Pending External Actions", show_lines=True)
    table.add_column("#", style="bold", width=4)
    table.add_column("Status", width=12)
    table.add_column("Type", width=16)
    table.add_column("Proposed by", width=22)
    table.add_column("Recipient")
    table.add_column("Subject")

    status_colors = {"pending": "yellow", "approved": "green", "rejected": "red"}

    # Always use global 1-based position so that show/approve/reject indices match.
    for global_pos, a in enumerate(actions, start=1):
        if not all_ and a["status"] != "pending":
            continue
        color = status_colors.get(a["status"], "white")
        table.add_row(
            str(global_pos),
            f"[{color}]{a['status']}[/{color}]",
            a.get("action_type", ""),
            a.get("proposed_by", ""),
            a.get("recipient", "")[:40],
            a.get("subject", "")[:40] or "[dim](none)[/dim]",
        )

    console.print(table)
    console.print(f"\n[dim]Run [bold]dri company approvals show --id {company_id} <N>[/bold] to read full content.[/dim]")
    console.print(f"[dim]Run [bold]dri company approvals approve --id {company_id} <N>[/bold] to approve.[/dim]")


@approvals_app.command("show")
def approvals_show(
    action_id: int = typer.Argument(..., help="Action number as shown in 'approvals list'"),
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
) -> None:
    """Show the full content of a pending action."""
    async def _run() -> list[dict]:
        ws = await _get_workspace(company_id)
        if ws is None:
            return []
        actions, _ = _load_pending(ws)
        return actions

    actions = asyncio.run(_run())
    if not actions:
        console.print("[red]No pending approvals found.[/red]")
        raise typer.Exit(1)

    # Lookup by 1-based position in the full list (matches what 'list' displays)
    if action_id < 1 or action_id > len(actions):
        console.print(f"[red]Action #{action_id} not found. Valid range: 1–{len(actions)}.[/red]")
        raise typer.Exit(1)
    match = actions[action_id - 1]

    status_colors = {"pending": "yellow", "approved": "green", "rejected": "red"}
    color = status_colors.get(match["status"], "white")

    console.print()
    console.print(Panel(
        f"[bold]Type:[/bold] {match.get('action_type', '')}\n"
        f"[bold]Status:[/bold] [{color}]{match['status']}[/{color}]\n"
        f"[bold]Proposed by:[/bold] {match.get('proposed_by', '')}\n"
        f"[bold]Proposed at:[/bold] {match.get('proposed_at', '')}\n"
        f"[bold]Recipient:[/bold] {match.get('recipient', '')}\n"
        f"[bold]Subject:[/bold] {match.get('subject', '') or '(none)'}\n\n"
        f"[bold]Rationale:[/bold]\n{match.get('rationale', '')}\n\n"
        f"[bold]Content:[/bold]\n{match.get('content', '')}",
        title=f"[bold]Action #{action_id}[/bold]",
        border_style=color,
    ))
    if match.get("decision_note"):
        console.print(f"[dim]Decision note: {match['decision_note']}[/dim]")
    console.print()


@approvals_app.command("approve")
def approvals_approve(
    action_id: int = typer.Argument(..., help="Action number as shown in 'approvals list'"),
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
    note: str = typer.Option("", "--note", "-n", help="Optional note"),
) -> None:
    """Approve a pending action. bulk_file_delete actions are executed immediately on approval."""
    from datetime import datetime, timezone
    import shutil
    from pathlib import Path

    approved_action: dict = {}

    async def _run() -> bool:
        ws = await _get_workspace(company_id)
        if ws is None:
            return False
        actions, _ = _load_pending(ws)
        if action_id < 1 or action_id > len(actions):
            return False
        a = actions[action_id - 1]
        a["status"] = "approved"
        a["decided_at"] = datetime.now(timezone.utc).isoformat()
        a["decision_note"] = note or None
        _save_pending(ws, actions)
        approved_action.update(a)
        approved_action["_ws"] = ws
        return True

    found = asyncio.run(_run())
    if not found:
        console.print(f"[red]Action #{action_id} not found.[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Action #{action_id} approved.[/green]")

    # Execute bulk_file_delete immediately — parse file paths from content and delete them.
    if approved_action.get("action_type") == "bulk_file_delete":
        ws_root = Path(approved_action.get("_ws", ""))
        content = approved_action.get("content", "")
        paths_to_delete = [
            line.strip().lstrip("- ").strip()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        deleted, skipped = [], []
        for rel in paths_to_delete:
            if not rel:
                continue
            target = (ws_root / rel).resolve()
            if not str(target).startswith(str(ws_root.resolve())):
                skipped.append(f"{rel} (path escape blocked)")
                continue
            if not target.exists():
                skipped.append(f"{rel} (not found)")
                continue
            try:
                if target.is_file():
                    target.unlink()
                else:
                    shutil.rmtree(str(target))
                deleted.append(rel)
            except Exception as e:
                skipped.append(f"{rel} (error: {e})")
        if deleted:
            console.print(f"[green]Deleted {len(deleted)} path(s):[/green]")
            for p in deleted:
                console.print(f"  [dim]- {p}[/dim]")
        if skipped:
            console.print(f"[yellow]Skipped {len(skipped)} path(s):[/yellow]")
            for p in skipped:
                console.print(f"  [dim]- {p}[/dim]")
    else:
        # Dispatch to the appropriate connector (email, webhook, etc.)
        import dri.connectors  # noqa: F401 — trigger registration
        from dri.connectors.registry import ConnectorRegistry

        action_type = approved_action.get("action_type", "other")
        connector = ConnectorRegistry.get_for(action_type, approved_action)

        if connector is None:
            console.print(
                f"[dim]No connector available for '{action_type}'. "
                "Action approved and recorded — execute manually.[/dim]"
            )
        elif not connector.is_configured:
            console.print(
                f"[yellow]Connector found but not configured.[/yellow]\n"
                f"[dim]{connector.setup_hint}[/dim]"
            )
        else:
            console.print(f"[dim]Executing via {type(connector).__name__}...[/dim]")
            exec_result = asyncio.run(connector.execute(approved_action))
            if exec_result.success:
                console.print(f"[green]✓ Executed: {exec_result.message}[/green]")
                if exec_result.external_id:
                    console.print(f"[dim]External ID: {exec_result.external_id}[/dim]")
            else:
                console.print(f"[red]✗ Execution failed: {exec_result.message}[/red]")
                console.print("[dim]Action remains approved — retry manually if needed.[/dim]")


@approvals_app.command("reject")
def approvals_reject(
    action_id: int = typer.Argument(..., help="Action number as shown in 'approvals list'"),
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
    note: str = typer.Option("", "--note", "-n", help="Reason for rejection"),
) -> None:
    """Reject a pending external action."""
    from datetime import datetime, timezone

    async def _run() -> bool:
        ws = await _get_workspace(company_id)
        if ws is None:
            return False
        actions, _ = _load_pending(ws)
        if action_id < 1 or action_id > len(actions):
            return False
        a = actions[action_id - 1]
        a["status"] = "rejected"
        a["decided_at"] = datetime.now(timezone.utc).isoformat()
        a["decision_note"] = note or None
        _save_pending(ws, actions)
        return True

    found = asyncio.run(_run())
    if not found:
        console.print(f"[red]Action #{action_id} not found.[/red]")
        raise typer.Exit(1)
    console.print(f"[red]Action #{action_id} rejected.[/red]")


# ── Team commands ──────────────────────────────────────────────────────────────

team_app = typer.Typer(name="team", help="Manage persistent agent identities in a company.")
company_app.add_typer(team_app, name="team")


@team_app.command("list")
def team_list(
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
) -> None:
    """List all team members and their performance stats."""
    from rich.table import Table

    async def _run() -> tuple[list, str]:
        from dri.storage.database import init_db, get_session
        from dri.storage.repositories import CompanyAgentRepository
        c = await _resolve_company(company_id)
        if c is None:
            return [], ""
        await init_db()
        async with get_session() as db:
            repo = CompanyAgentRepository(db)
            agents = await repo.list_active(c.id)
        return agents, c.name

    agents, cname = asyncio.run(_run())
    if not cname:
        console.print("[red]No company found. Use [bold]dri company create[/bold] first.[/red]")
        raise typer.Exit(1)
    if not agents:
        console.print(f"[dim]No team members recorded for {cname} yet. Run a task to populate.[/dim]")
        return

    table = Table(title=f"Team — {cname}", show_lines=True)
    table.add_column("Title", style="bold")
    table.add_column("Role", width=10)
    table.add_column("Tasks", justify="right", width=7)
    table.add_column("Success", justify="right", width=9)
    table.add_column("Rate", justify="right", width=7)
    table.add_column("Budget", justify="right", width=10)
    table.add_column("Last Active", style="dim", width=17)
    table.add_column("Notes", style="dim")

    for a in agents:
        rate = f"{a.success_rate:.0%}"
        rate_color = "green" if a.success_rate >= 0.8 else ("yellow" if a.success_rate >= 0.5 else "red")
        budget_str = f"{a.token_budget:,}" if a.token_budget > 0 else "[dim]default[/dim]"
        table.add_row(
            a.title,
            a.role,
            str(a.task_count),
            str(a.success_count),
            f"[{rate_color}]{rate}[/{rate_color}]",
            budget_str,
            a.last_active_at.strftime("%Y-%m-%d %H:%M"),
            a.notes[:40] or "[dim]—[/dim]",
        )
    console.print(table)
    console.print("[dim]Use [bold]dri company team show <title>[/bold] for full profile.[/dim]")


@team_app.command("show")
def team_show(
    title: str = typer.Argument(..., help="Agent title (e.g. 'SEO Specialist')"),
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
) -> None:
    """Show the full profile of a team member."""
    async def _run():
        from dri.storage.database import init_db, get_session
        from dri.storage.repositories import CompanyAgentRepository
        c = await _resolve_company(company_id)
        if c is None:
            return None, None
        await init_db()
        async with get_session() as db:
            repo = CompanyAgentRepository(db)
            agent = await repo.get_by_title(c.id, title)
        return agent, c

    agent, company = asyncio.run(_run())
    if company is None:
        console.print("[red]No company found.[/red]")
        raise typer.Exit(1)
    if agent is None:
        console.print(f"[red]No team member named '{title}' found.[/red]")
        console.print("[dim]Use [bold]dri company team list[/bold] to see all members.[/dim]")
        raise typer.Exit(1)

    import re
    knowledge_path = (
        f"workspace/{re.sub(r'[^a-z0-9]+', '-', company.name.lower()).strip('-')}/"
        f"{agent.dept_slug}/_knowledge/"
        f"{re.sub(r'[^a-z0-9]+', '-', agent.title.lower()).strip('-')}/"
    )
    rate_color = "green" if agent.success_rate >= 0.8 else ("yellow" if agent.success_rate >= 0.5 else "red")

    console.print()
    console.print(Panel(
        f"[bold]Title:[/bold] {agent.title}\n"
        f"[bold]Role:[/bold] {agent.role}\n"
        f"[bold]Status:[/bold] {agent.status}\n"
        f"[bold]Tasks run:[/bold] {agent.task_count}  "
        f"[bold]Succeeded:[/bold] {agent.success_count}  "
        f"[bold]Rate:[/bold] [{rate_color}]{agent.success_rate:.0%}[/{rate_color}]\n"
        f"[bold]Token budget:[/bold] {agent.token_budget:,} (0 = system default)\n"
        f"[bold]Last active:[/bold] {agent.last_active_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"[bold]Joined:[/bold] {agent.created_at.strftime('%Y-%m-%d')}\n\n"
        f"[bold]Notes:[/bold]\n{agent.notes or '(none)'}\n\n"
        f"[bold]Persistent memory path:[/bold]\n[dim]{knowledge_path}[/dim]",
        title=f"[bold]{agent.title}[/bold]",
        border_style="blue",
    ))
    console.print()


@team_app.command("note")
def team_note(
    title: str = typer.Argument(..., help="Agent title"),
    note: str = typer.Argument(..., help="Note to attach to this agent"),
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
) -> None:
    """Attach a note to a team member (replaces existing note)."""
    async def _run() -> bool:
        from dri.storage.database import init_db, get_session
        from dri.storage.repositories import CompanyAgentRepository
        c = await _resolve_company(company_id)
        if c is None:
            return False
        await init_db()
        async with get_session() as db:
            repo = CompanyAgentRepository(db)
            agent = await repo.get_by_title(c.id, title)
            if agent is None:
                return False
            await repo.set_notes(agent.id, note)
        return True

    found = asyncio.run(_run())
    if not found:
        console.print(f"[red]Agent '{title}' not found.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Note updated for '{title}'.[/green]")


@team_app.command("remove")
def team_remove(
    title: str = typer.Argument(..., help="Agent title to deactivate"),
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Mark a team member as inactive (soft delete — history preserved)."""
    async def _run() -> tuple[bool, str]:
        from dri.storage.database import init_db, get_session
        from dri.storage.repositories import CompanyAgentRepository
        c = await _resolve_company(company_id)
        if c is None:
            return False, ""
        await init_db()
        async with get_session() as db:
            repo = CompanyAgentRepository(db)
            agent = await repo.get_by_title(c.id, title)
            if agent is None:
                return False, ""
            await repo.set_status(agent.id, "inactive")
        return True, c.name

    if not force:
        confirmed = typer.confirm(f"Mark '{title}' as inactive?", default=False)
        if not confirmed:
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

    found, cname = asyncio.run(_run())
    if not found:
        console.print(f"[red]Agent '{title}' not found.[/red]")
        raise typer.Exit(1)
    console.print(f"[yellow]'{title}' marked inactive. History preserved in DB.[/yellow]")


@team_app.command("promote")
def team_promote(
    title: str = typer.Argument(..., help="Agent title to promote"),
    budget: int = typer.Option(..., "--budget", "-b", help="New token budget for this agent"),
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
) -> None:
    """Set a custom token budget for a team member (stored for future task forces)."""
    async def _run() -> bool:
        from dri.storage.database import init_db, get_session
        from dri.storage.repositories import CompanyAgentRepository
        c = await _resolve_company(company_id)
        if c is None:
            return False
        await init_db()
        async with get_session() as db:
            repo = CompanyAgentRepository(db)
            agent = await repo.get_by_title(c.id, title)
            if agent is None:
                return False
            await repo.set_budget(agent.id, budget)
        return True

    found = asyncio.run(_run())
    if not found:
        console.print(f"[red]Agent '{title}' not found.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]'{title}' token budget set to {budget:,}.[/green]")
    console.print("[dim]Budget stored — applied to future task forces involving this agent.[/dim]")


@company_app.command("recover")
def company_recover(
    yes: bool = typer.Option(False, "--yes", "-y", help="Import all orphans without confirmation"),
) -> None:
    """Scan workspace/ for company folders not in the DB and offer to re-import them."""
    from rich.table import Table

    async def _scan():
        from dri.orchestration.company_executor import CompanyExecutor
        return await CompanyExecutor.recover_scan()

    orphans = asyncio.run(_scan())

    if not orphans:
        console.print("[green]No orphan workspaces found — everything is accounted for.[/green]")
        return

    table = Table(title="Orphan Workspaces", show_lines=True)
    table.add_column("#", width=3, justify="right")
    table.add_column("Folder", style="dim")
    table.add_column("Inferred name", style="bold")

    for i, o in enumerate(orphans, 1):
        table.add_row(str(i), o.folder_name, o.inferred_name)

    console.print()
    console.print(table)
    console.print(
        "\n[dim]These workspace folders exist on disk but have no matching company record in the DB.[/dim]"
    )
    console.print()

    for o in orphans:
        if not yes:
            confirmed = typer.confirm(f"Import '{o.folder_name}' as '{o.inferred_name}'?", default=True)
            if not confirmed:
                console.print(f"[dim]Skipped {o.folder_name}.[/dim]")
                continue

        async def _import(folder=o.folder_name, name=o.inferred_name):
            from dri.orchestration.company_executor import CompanyExecutor
            return await CompanyExecutor.recover_import(folder, name)

        try:
            company = asyncio.run(_import())
            from dri.config.state import set_active_company_id
            set_active_company_id(company.id)
            console.print(f"[green]Imported '{company.name}' (ID: {company.id[:8]}...).[/green]")
        except Exception as e:
            console.print(f"[red]Failed to import '{o.folder_name}': {e}[/red]")

    console.print()
    console.print("[dim]Use [bold]dri company list[/bold] to see all companies.[/dim]")


@company_app.command("budget")
def company_budget(
    company_id: str = typer.Option("", "--id", help="Company ID (uses active/latest if omitted)"),
) -> None:
    """Show token budget usage across all sessions for this company."""
    from rich.table import Table

    async def _run():
        from dri.storage.database import init_db, get_session
        from dri.storage.orm import AgentORM, SessionORM
        from sqlalchemy import select

        c = await _resolve_company(company_id)
        if c is None:
            return None, []

        await init_db()
        async with get_session() as db:
            result = await db.execute(
                select(SessionORM)
                .where(SessionORM.company_name == c.name)
                .order_by(SessionORM.created_at.desc())
                .limit(5)
            )
            sessions = list(result.scalars())

            session_data = []
            for s in sessions:
                agent_result = await db.execute(
                    select(AgentORM).where(AgentORM.session_id == s.id)
                )
                agents = list(agent_result.scalars())
                session_data.append((s, agents))

        return c, session_data

    company, session_data = asyncio.run(_run())

    if company is None:
        console.print("[red]No company found. Use [bold]dri company create[/bold] first.[/red]")
        raise typer.Exit(1)
    if not session_data:
        console.print(f"[dim]No session data found for {company.name}. Run a task to populate.[/dim]")
        return

    console.print()
    for session, agents in session_data:
        table = Table(
            title=f"Session {session.id[:8]}...  [{session.created_at.strftime('%Y-%m-%d %H:%M')}]",
            show_lines=True,
        )
        table.add_column("Agent", style="bold")
        table.add_column("Allocated", justify="right")
        table.add_column("Used", justify="right")
        table.add_column("Remaining", justify="right")
        table.add_column("%", justify="right")

        for a in sorted(agents, key=lambda x: x.budget_used, reverse=True):
            if a.budget_total == 0:
                continue
            remaining = a.budget_total - a.budget_used
            pct = a.budget_used / a.budget_total
            pct_color = "red" if pct > 0.9 else ("yellow" if pct > 0.7 else "green")
            table.add_row(
                a.title,
                f"{a.budget_total:,}",
                f"{a.budget_used:,}",
                f"{remaining:,}",
                f"[{pct_color}]{pct:.0%}[/{pct_color}]",
            )

        # Total row
        total_alloc = sum(a.budget_total for a in agents)
        total_used = sum(a.budget_used for a in agents)
        if total_alloc > 0:
            total_pct = total_used / total_alloc
            table.add_section()
            table.add_row(
                "[bold]TOTAL[/bold]",
                f"[bold]{total_alloc:,}[/bold]",
                f"[bold]{total_used:,}[/bold]",
                f"[bold]{total_alloc - total_used:,}[/bold]",
                f"[bold]{total_pct:.0%}[/bold]",
            )

        console.print(table)
        console.print()


@company_app.command("decommission")
def company_decommission(
    title: str = typer.Argument(..., help="Exact department title to decommission (e.g. 'Chief Marketing Officer')"),
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
    archive: bool = typer.Option(False, "--archive", "-a", help="Archive deliverables to shared/archive/ before removal"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Decommission a department: handle its files and remove it from the org chart."""
    import re
    import shutil
    from pathlib import Path
    from dri.config.settings import get_settings

    async def _get_company() -> tuple[str, str, str] | None:
        from dri.storage.database import init_db, get_session
        from dri.storage.repositories import PersistentCompanyRepository
        await init_db()
        async with get_session() as db:
            repo = PersistentCompanyRepository(db)
            c = await repo.get(company_id) if company_id else await repo.get_latest()
        if c is None:
            return None
        slug = re.sub(r"[^a-z0-9]+", "-", c.name.lower()).strip("-")
        dept_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        ws = str(get_settings().workspace_dir / slug)
        return c.id, ws, dept_slug

    info = asyncio.run(_get_company())
    if info is None:
        console.print("[red]No company found.[/red]")
        raise typer.Exit(1)

    cid, workspace_root, dept_slug = info
    dept_path = Path(workspace_root) / dept_slug

    # Show what exists
    console.print()
    if not dept_path.exists():
        console.print(f"[dim]Dept folder '{dept_slug}/' does not exist — only removing from org chart.[/dim]")
        files: list[Path] = []
    else:
        files = sorted(dept_path.rglob("*") if dept_path.exists() else [])
        files = [f for f in files if f.is_file()]
        wip_files = [f for f in files if "_wip" in str(f.relative_to(dept_path))]
        deliverables = [f for f in files if "_wip" not in str(f.relative_to(dept_path))]

        console.print(Panel(
            f"[bold]Department:[/bold] {title}\n"
            f"[bold]Folder:[/bold] {dept_slug}/\n"
            f"[bold]Deliverables:[/bold] {len(deliverables)} file(s)\n"
            f"[bold]WIP files:[/bold] {len(wip_files)} file(s)",
            title="[bold yellow]Decommission Preview[/bold yellow]",
            border_style="yellow",
        ))

        if deliverables:
            console.print("\n[bold]Deliverables (will be archived or deleted):[/bold]")
            for f in deliverables:
                console.print(f"  [dim]{f.relative_to(Path(workspace_root))}[/dim]")
        if wip_files:
            console.print("\n[bold]WIP files (will always be deleted):[/bold]")
            for f in wip_files:
                console.print(f"  [dim]{f.relative_to(Path(workspace_root))}[/dim]")
        console.print()

    if not force:
        action = "archive deliverables + delete WIP" if archive else "delete all files"
        confirmed = typer.confirm(
            f"Decommission '{title}' ({action}) and remove from org chart?",
            default=False,
        )
        if not confirmed:
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

    # Handle files
    if dept_path.exists() and files:
        if archive and deliverables:
            archive_dir = Path(workspace_root) / "shared" / "archive" / dept_slug
            archive_dir.mkdir(parents=True, exist_ok=True)
            for f in deliverables:
                dest = archive_dir / f.relative_to(dept_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))
            console.print(f"[green]Archived {len(deliverables)} deliverable(s) → shared/archive/{dept_slug}/[/green]")

        # Delete dept folder (WIP already gone if archived, otherwise delete everything)
        shutil.rmtree(str(dept_path))
        console.print(f"[green]Deleted folder: {dept_slug}/[/green]")

    # Remove from org chart in DB
    async def _remove() -> bool:
        from dri.storage.database import get_session
        from dri.storage.repositories import PersistentCompanyRepository
        async with get_session() as db:
            repo = PersistentCompanyRepository(db)
            removed = await repo.remove_department(cid, title)
        return removed

    removed = asyncio.run(_remove())
    if removed:
        console.print(f"[green]'{title}' removed from org chart.[/green]")
    else:
        console.print(f"[yellow]Warning: '{title}' not found in org chart (may have been renamed).[/yellow]")

    console.print()
    console.print(Panel(
        f"[bold green]{title}[/bold green] has been decommissioned.\n"
        + (f"Deliverables archived in [dim]shared/archive/{dept_slug}/[/dim]" if archive and files else "")
        + ("\nThe company continues with the remaining departments." if removed else ""),
        border_style="green",
    ))


@app.command()
def sessions() -> None:
    """List all past sessions."""
    async def _list() -> None:
        from dri.storage.database import init_db, get_session
        from dri.storage.orm import SessionORM
        from sqlalchemy import select

        await init_db()
        async with get_session() as db:
            result = await db.execute(
                select(SessionORM).order_by(SessionORM.created_at.desc()).limit(10)
            )
            rows = list(result.scalars())

        if not rows:
            console.print("[dim]No sessions found.[/dim]")
            return

        from rich.table import Table
        table = Table(title="Recent Sessions", show_lines=True)
        table.add_column("ID", style="dim", width=10)
        table.add_column("Company", style="bold")
        table.add_column("Status")
        table.add_column("Tokens", justify="right")
        table.add_column("Created", style="dim")

        for row in rows:
            status_color = {"done": "green", "running": "yellow", "failed": "red"}.get(row.status, "white")
            table.add_row(
                row.id[:8] + "...",
                row.company_name or "[italic]unnamed[/italic]",
                f"[{status_color}]{row.status}[/{status_color}]",
                f"{row.total_tokens_used:,}",
                row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else "",
            )

        console.print(table)

    asyncio.run(_list())


def main() -> None:
    """Entry point for `dri` CLI command."""
    app()


if __name__ == "__main__":
    main()
