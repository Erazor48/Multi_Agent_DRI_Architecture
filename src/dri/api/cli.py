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
