"""
JRVS CLI — main entry point.

Usage
─────
  jrvs                        Show help banner
  jrvs search "<query>"       Brave + YouTube search → embed → FAISS → results
  jrvs ask    "<question>"    RAG query: FAISS context → Ollama → answer
  jrvs google <...>           Google Workspace commands
  jrvs agent  <...>           Autonomous agent commands
"""

from __future__ import annotations

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

_BANNER = (
    "[bold white]JRVS — Personal AI Assistant[/]\n\n"
    "[bold green]Search & Ask[/]\n"
    "  [bold cyan]jrvs search \"<query>\"[/]          Brave + YouTube search with FAISS memory\n"
    "  [bold cyan]jrvs ask    \"<question>\"[/]        RAG-powered answer from accumulated knowledge\n"
    "  [bold cyan]jrvs ask    \"<question>\" --raw[/]  Also show injected context\n\n"
    "[bold green]Google Workspace[/]\n"
    "  [bold cyan]jrvs google auth[/]                OAuth2 login\n"
    "  [bold cyan]jrvs google ask \"<request>\"[/]     Natural-language Google command\n"
    "  [bold cyan]jrvs google gmail list[/]           Gmail inbox\n"
    "  [bold cyan]jrvs google docs list[/]            Recent documents\n"
    "  [bold cyan]jrvs google sheets list[/]          Recent spreadsheets\n"
    "  [bold cyan]jrvs google calendar list[/]        Upcoming events\n\n"
    "[bold green]Autonomous Agent[/]\n"
    "  [bold cyan]jrvs agent run[/]                   Run scheduled goals\n"
    "  [bold cyan]jrvs agent goals[/]                 List configured goals\n"
    "  [bold cyan]jrvs agent status[/]                Recent runs\n"
    "  [bold cyan]jrvs agent pending[/]               Actions awaiting approval\n\n"
    "[dim]Run any command with --help for details.[/dim]"
)


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx) -> None:
    """JRVS — Personal AI Assistant."""
    if ctx.invoked_subcommand is None:
        console.print(Panel(
            _BANNER,
            title="[bold]JRVS[/]",
            border_style="blue",
            box=box.DOUBLE,
            expand=False,
            padding=(1, 3),
        ))


# ─────────────────────────────────────────────────────────────────────────────
# search command
# ─────────────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query")
@click.option("--count", "-n", default=None, type=int, help="Number of Brave results to fetch.")
@click.option("--yt-count", default=None, type=int, help="Number of YouTube results to fetch.")
def search(query: str, count: int | None, yt_count: int | None) -> None:
    """Search the web (Brave + YouTube), embed results, and display them.

    Results are embedded into FAISS for future semantic recall.
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from jrvs.web.brave_client import WebSearchEngine

    engine = WebSearchEngine()

    with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
        p.add_task("Searching…", total=None)
        web_context, raw_web, yt_context, raw_yt = engine.run(
            query, count=count, yt_count=yt_count,
        )

    # ── Brave results table ──────────────────────────────────────────────
    if raw_web:
        tbl = Table(title="Brave Search Results", box=box.SIMPLE_HEAD, show_lines=True)
        tbl.add_column("#", style="dim", width=3)
        tbl.add_column("Title", style="bold", max_width=50)
        tbl.add_column("URL", style="cyan", max_width=60)
        tbl.add_column("Snippet", max_width=60, overflow="fold")
        for i, r in enumerate(raw_web, 1):
            tbl.add_row(str(i), r.get("title", ""), r.get("url", ""), r.get("snippet", ""))
        console.print(tbl)
    else:
        console.print("[dim]No Brave results.[/dim]")

    # ── YouTube results table ────────────────────────────────────────────
    if raw_yt:
        tbl = Table(title="YouTube Results", box=box.SIMPLE_HEAD, show_lines=True)
        tbl.add_column("#", style="dim", width=3)
        tbl.add_column("Title", style="bold", max_width=50)
        tbl.add_column("Channel", style="green", max_width=25)
        tbl.add_column("URL", style="cyan", max_width=50)
        for i, v in enumerate(raw_yt, 1):
            url = f"https://www.youtube.com/watch?v={v.get('video_id', '')}"
            tbl.add_row(str(i), v.get("title", ""), v.get("channel_title", ""), url)
        console.print(tbl)
    else:
        console.print("[dim]No YouTube results.[/dim]")

    total = len(raw_web) + len(raw_yt)
    console.print(f"\n[green]Embedded {total} result(s) into FAISS semantic memory.[/green]")


# ─────────────────────────────────────────────────────────────────────────────
# ask command
# ─────────────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("question")
@click.option("--raw", is_flag=True, default=False, help="Also show the injected RAG context.")
def ask(question: str, raw: bool) -> None:
    """Ask a question — retrieves FAISS context and answers via Ollama."""
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from jrvs.llm.rag_engine import RAGEngine

    rag = RAGEngine()

    # Optionally show context
    if raw:
        web_ctx = rag.retrieve_web_context(question)
        yt_ctx = rag.retrieve_yt_search_context(question)
        ctx = "\n".join(filter(None, [web_ctx, yt_ctx]))
        if ctx:
            console.print(Panel(
                ctx,
                title="[bold yellow]Injected RAG Context[/]",
                border_style="yellow",
                expand=True,
            ))
        else:
            console.print("[dim]No prior context found in FAISS indexes.[/dim]")

    with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
        p.add_task("Thinking…", total=None)
        answer = rag.query(question)

    console.print()
    console.print(Panel(
        answer,
        title="[bold green]JRVS Answer[/]",
        border_style="green",
        expand=True,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Register sub-groups
# ─────────────────────────────────────────────────────────────────────────────

from jrvs.cli.google import google  # noqa: E402
from jrvs.cli.agent import agent    # noqa: E402

main.add_command(google)
main.add_command(agent)
