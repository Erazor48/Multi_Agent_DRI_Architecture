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
