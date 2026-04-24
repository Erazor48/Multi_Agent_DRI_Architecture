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
console = Console()


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
    console.print("\n[dim]Use [bold]dri company chat[/bold] to start working with your CEO.[/dim]")


@company_app.command("list")
def company_list() -> None:
    """List all persistent companies."""
    async def _run() -> None:
        from dri.storage.database import init_db, get_session
        from dri.storage.repositories import PersistentCompanyRepository
        from rich.table import Table

        await init_db()
        async with get_session() as db:
            repo = PersistentCompanyRepository(db)
            companies = await repo.list_active()

        if not companies:
            console.print("[dim]No persistent companies found. Use [bold]dri company create[/bold].[/dim]")
            return

        table = Table(title="Your Companies", show_lines=True)
        table.add_column("ID", style="dim", width=10)
        table.add_column("Name", style="bold")
        table.add_column("Vision")
        table.add_column("Departments", justify="right")
        table.add_column("Created", style="dim")

        for c in companies:
            table.add_row(
                c.id[:8] + "...",
                c.name,
                c.vision[:60] + "..." if len(c.vision) > 60 else c.vision,
                str(len(c.org_structure)),
                c.created_at.strftime("%Y-%m-%d %H:%M"),
            )
        console.print(table)

    asyncio.run(_run())


@company_app.command("chat")
def company_chat(
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
) -> None:
    """Start an interactive session with your company CEO."""

    async def _session() -> None:
        from dri.storage.database import init_db, get_session
        from dri.storage.repositories import PersistentCompanyRepository
        from dri.orchestration.company_executor import CompanyExecutor

        await init_db()
        async with get_session() as db:
            repo = PersistentCompanyRepository(db)
            c = await repo.get(company_id) if company_id else await repo.get_latest()

        if c is None:
            console.print("[red]No company found. Use [bold]dri company create[/bold] first.[/red]")
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

            with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True) as p:
                progress_task = p.add_task("CEO is thinking...", total=None)

                def _upd(m: str) -> None:
                    p.update(progress_task, description=m)

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
        from dri.storage.database import init_db, get_session
        from dri.storage.repositories import PersistentCompanyRepository
        from dri.orchestration.company_executor import CompanyExecutor
        await init_db()
        async with get_session() as db:
            repo = PersistentCompanyRepository(db)
            c = await repo.get(company_id) if company_id else await repo.get_latest()
        if c is None:
            raise ValueError("No company found.")
        return await CompanyExecutor.task(c.id, task)

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console) as p:
        p.add_task("Executing task...", total=None)
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
    from dri.storage.database import init_db, get_session
    from dri.storage.repositories import PersistentCompanyRepository
    from dri.config.settings import get_settings

    await init_db()
    async with get_session() as db:
        repo = PersistentCompanyRepository(db)
        c = await repo.get(company_id) if company_id else await repo.get_latest()
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

    visible = actions if all_ else [a for a in actions if a["status"] == "pending"]

    if not visible:
        console.print("[dim]No pending approvals.[/dim]")
        if not all_:
            console.print("[dim]Use --all to see decided actions.[/dim]")
        return

    table = Table(title="Pending External Actions", show_lines=True)
    table.add_column("#", style="bold", width=4)
    table.add_column("Status", width=12)
    table.add_column("Type", width=16)
    table.add_column("Proposed by", width=22)
    table.add_column("Recipient")
    table.add_column("Subject")

    status_colors = {"pending": "yellow", "approved": "green", "rejected": "red"}

    for a in visible:
        color = status_colors.get(a["status"], "white")
        table.add_row(
            str(a["id"]),
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
    action_id: int = typer.Argument(..., help="Action ID to inspect"),
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

    match = next((a for a in actions if a["id"] == action_id), None)
    if match is None:
        console.print(f"[red]Action #{action_id} not found.[/red]")
        raise typer.Exit(1)

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
    action_id: int = typer.Argument(..., help="Action ID to approve"),
    company_id: str = typer.Option("", "--id", help="Company ID (uses latest if omitted)"),
    note: str = typer.Option("", "--note", "-n", help="Optional note"),
) -> None:
    """Approve a pending external action (marks it — execution depends on available integrations)."""
    from datetime import datetime, timezone

    async def _run() -> bool:
        ws = await _get_workspace(company_id)
        if ws is None:
            return False
        actions, _ = _load_pending(ws)
        for a in actions:
            if a["id"] == action_id:
                a["status"] = "approved"
                a["decided_at"] = datetime.now(timezone.utc).isoformat()
                a["decision_note"] = note or None
                _save_pending(ws, actions)
                return True
        return False

    found = asyncio.run(_run())
    if not found:
        console.print(f"[red]Action #{action_id} not found.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Action #{action_id} approved.[/green]")
    console.print("[dim]Note: actual execution requires a configured integration (email, etc.).[/dim]")


@approvals_app.command("reject")
def approvals_reject(
    action_id: int = typer.Argument(..., help="Action ID to reject"),
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
        for a in actions:
            if a["id"] == action_id:
                a["status"] = "rejected"
                a["decided_at"] = datetime.now(timezone.utc).isoformat()
                a["decision_note"] = note or None
                _save_pending(ws, actions)
                return True
        return False

    found = asyncio.run(_run())
    if not found:
        console.print(f"[red]Action #{action_id} not found.[/red]")
        raise typer.Exit(1)
    console.print(f"[red]Action #{action_id} rejected.[/red]")


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
