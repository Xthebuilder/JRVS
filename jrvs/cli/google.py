"""
JRVS Google Workspace CLI sub-commands.

Usage
─────
  jrvs google auth                              # First-time OAuth2 setup
  jrvs google ask "show me my last 5 emails"    # Natural-language → LLM routes → API → LLM answer

  # Gmail
  jrvs google gmail list
  jrvs google gmail search "from:boss@co.com"
  jrvs google gmail read <message-id>
  jrvs google gmail send --to x@y.com --subject "Hi" --body "Hello!"

  # Docs
  jrvs google docs list
  jrvs google docs read <doc-id>
  jrvs google docs find "Q4 Report"
  jrvs google docs create --title "New Doc" --content "First line"
  jrvs google docs append <doc-id> --text "New paragraph"

  # Sheets
  jrvs google sheets list
  jrvs google sheets read <spreadsheet-id>
  jrvs google sheets find "Budget 2026"
  jrvs google sheets append <spreadsheet-id> --range Sheet1 --values '[[1,2,3],[4,5,6]]'
  jrvs google sheets create --title "My Sheet"
"""

from __future__ import annotations

import json
import time

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from jrvs.config import Config
from jrvs.utils.logger import setup_logger, log_command, log_performance, log_error

logger  = setup_logger("jrvs.google")
console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Top-level group
# ─────────────────────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.pass_context
def google(ctx) -> None:
    """Google Workspace commands — Gmail, Docs & Sheets via AI routing."""
    if ctx.invoked_subcommand is None:
        console.print(Panel(
            "[bold white]Google Workspace Commands[/]\n\n"
            "[bold green]Setup[/]\n"
            "  [bold cyan]jrvs google auth[/]                    OAuth2 login (run once)\n\n"
            "[bold green]Natural Language (AI routes the API call for you)[/]\n"
            "  [bold cyan]jrvs google ask \"<request>\"[/]         Any Gmail / Docs / Sheets request\n\n"
            "[bold green]Gmail[/]\n"
            "  [bold cyan]jrvs google gmail list[/]              Recent inbox emails\n"
            "  [bold cyan]jrvs google gmail search \"query\"[/]    Search with Gmail syntax\n"
            "  [bold cyan]jrvs google gmail read <id>[/]         Read full email body\n"
            "  [bold cyan]jrvs google gmail send[/]              Compose and send email\n"
            "  [bold cyan]jrvs google gmail reply <id>[/]        Reply to a thread\n"
            "  [bold cyan]jrvs google gmail labels[/]            List all Gmail labels\n\n"
            "[bold green]Google Docs[/]\n"
            "  [bold cyan]jrvs google docs list[/]               Recent documents\n"
            "  [bold cyan]jrvs google docs find \"name\"[/]        Find & read doc by name\n"
            "  [bold cyan]jrvs google docs read <id>[/]          Read full doc text\n"
            "  [bold cyan]jrvs google docs create[/]             Create new document\n"
            "  [bold cyan]jrvs google docs create --ai[/]        AI writes content (RAG-assisted)\n"
            "  [bold cyan]jrvs google docs append <id>[/]        Append text to doc\n"
            "  [bold cyan]jrvs google docs append <id> --ai[/]   AI appends content (RAG-assisted)\n"
            "  [bold cyan]jrvs google docs replace <id>[/]       Find & replace text in doc\n\n"
            "[bold green]Google Sheets[/]\n"
            "  [bold cyan]jrvs google sheets list[/]             Recent spreadsheets\n"
            "  [bold cyan]jrvs google sheets find \"name\"[/]      Find spreadsheet by name\n"
            "  [bold cyan]jrvs google sheets read <id>[/]        Read sheet data\n"
            "  [bold cyan]jrvs google sheets info <id>[/]        Sheet names & metadata\n"
            "  [bold cyan]jrvs google sheets append <id>[/]      Append rows\n"
            "  [bold cyan]jrvs google sheets write <id>[/]       Write to a specific range\n"
            "  [bold cyan]jrvs google sheets write <id> --ai[/]  AI fills data (RAG-assisted)\n"
            "  [bold cyan]jrvs google sheets clear <id>[/]       Clear a range\n"
            "  [bold cyan]jrvs google sheets create[/]           Create new spreadsheet\n\n"
            "[bold green]Google Calendar[/]\n"
            "  [bold cyan]jrvs google calendar list[/]           Upcoming events\n"
            "  [bold cyan]jrvs google calendar find \"keyword\"[/] Search events\n"
            "  [bold cyan]jrvs google calendar create[/]         Create an event\n"
            "  [bold cyan]jrvs google calendar update <id>[/]    Edit an existing event\n"
            "  [bold cyan]jrvs google calendar delete <id>[/]    Delete an event\n"
            "  [bold cyan]jrvs google calendar calendars[/]      List all calendars\n\n"
            "[bold yellow]Example:[/]\n"
            "  jrvs google ask \"list my last 10 unread emails\"\n"
            "  jrvs google docs create --title \"Q2 Strategy\" --ai\n"
            "  jrvs google sheets write <id> --range Sheet1!A1:C3 --ai --topic \"revenue Q1\"",

            title="[bold]jrvs google[/]",
            border_style="green",
            box=box.DOUBLE,
            expand=False,
            padding=(1, 3),
        ))


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

@google.command()
def auth() -> None:
    """Run the Google OAuth2 consent flow and save credentials."""
    try:
        from jrvs.google.auth import run_auth_flow
        console.print("\n[dim]Opening browser for Google OAuth2 consent…[/dim]\n")
        run_auth_flow()
        console.print(
            Panel(
                f"[bold green]✓ Authorised successfully![/]\n"
                f"Token saved to: [cyan]{Config.GOOGLE_TOKEN_FILE}[/]",
                border_style="green",
                expand=False,
            )
        )
    except Exception as exc:
        console.print(f"[bold red]Auth failed:[/bold red] {exc}")
        raise SystemExit(1) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Natural-language ask (main entry point for most users)
# ─────────────────────────────────────────────────────────────────────────────

@google.command()
@click.argument("request")
@click.option("--raw", is_flag=True, default=False, help="Also print raw API JSON result.")
def ask(request: str, raw: bool) -> None:
    """Route any natural-language Google Workspace request through the AI.

    Examples:\n
      jrvs google ask "show me my last 5 emails"\n
      jrvs google ask "create a doc called YouTube Strategy 2026"\n
      jrvs google ask "read row 1 to 20 from spreadsheet 1AbC..."\n
      jrvs google ask "send an email to alice@example.com saying the report is done"\n
    """
    start = time.time()
    log_command("google_ask", {"request": request})

    try:
        from jrvs.google.google_agent import GoogleAgent

        console.print()
        console.print(Panel(
            f"[bold white]Google Request:[/]  [dim]{request}[/]",
            style="green",
            expand=False,
        ))

        agent = GoogleAgent()

        # ── Route first, without executing ───────────────────────────────
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Analysing request…", total=None)
            tool_calls = agent.route(request)

        # Normalise tool names (LLM sometimes returns a list)
        for tc in tool_calls:
            if isinstance(tc.get("tool"), list):
                tc["tool"] = tc["tool"][0] if tc["tool"] else ""

        # ── Email send? Draft → preview → confirm loop ────────────────────
        email_tools = {i for i, tc in enumerate(tool_calls) if tc.get("tool") == "gmail_send"}
        if email_tools:
            for idx in email_tools:
                tc = tool_calls[idx]
                # Draft / compose the email via LLM (fills subject+body if missing)
                with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
                    p.add_task("Drafting email…", total=None)
                    draft = agent.compose_email(request)

                # Merge any args the router already filled in
                draft.setdefault("to",      tc["args"].get("to", ""))
                draft.setdefault("subject", tc["args"].get("subject", ""))
                draft.setdefault("body",    tc["args"].get("body", ""))

                while True:
                    # Show the draft
                    console.print()
                    console.print(Panel(
                        f"[bold]To:[/]      {draft.get('to', '')}\n"
                        f"[bold]Subject:[/] {draft.get('subject', '')}\n\n"
                        f"{draft.get('body', '')}",
                        title="[bold yellow]📧 Email Draft — Review Before Sending[/]",
                        border_style="yellow",
                        expand=False,
                    ))
                    console.print("[bold][[S][/]end  [bold][E][/]dit  [bold][C][/]ancel]", end="  ")
                    choice = click.prompt("", default="s").strip().lower()

                    if choice == "c":
                        console.print("[yellow]Email cancelled.[/]")
                        return
                    elif choice == "e":
                        feedback = click.prompt("What should be changed?")
                        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
                            p.add_task("Revising email…", total=None)
                            draft = agent.revise_email(request, draft, feedback)
                    else:  # send
                        # Patch the tool call args with the approved draft
                        tool_calls[idx]["args"] = {
                            "to":      draft.get("to", ""),
                            "subject": draft.get("subject", ""),
                            "body":    draft.get("body", ""),
                        }
                        break

        # ── Execute and synthesise ────────────────────────────────────────
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Executing…", total=None)
            answer, executed = agent.execute_and_synthesise(request, tool_calls)

        # Show which tools were called
        if executed:
            tbl = Table(title="Tools Executed", box=box.SIMPLE, show_lines=False)
            tbl.add_column("Tool", style="cyan")
            tbl.add_column("Args", style="dim", max_width=60)
            tbl.add_column("Status", style="bold")
            for tc in executed:
                has_error = isinstance(tc["result"], dict) and "error" in tc["result"]
                status = "[red]error[/]" if has_error else "[green]ok[/]"
                tool_label = tc["tool"][0] if isinstance(tc["tool"], list) else tc["tool"]
                tbl.add_row(str(tool_label), str(tc["args"])[:60], status)
            console.print(tbl)

        # LLM answer
        console.print()
        console.print(Panel(answer, title="[bold green]JRVS Answer[/]", border_style="green", expand=True))

        if raw and executed:
            for tc in executed:
                console.print(f"\n[dim]Raw result ({tc['tool']}):[/]")
                console.print_json(json.dumps(tc["result"], default=str, indent=2)[:4000])

        log_performance("google_ask", time.time() - start)

    except RuntimeError as exc:
        console.print(f"\n[bold red]Setup error:[/bold red] {exc}")
        raise SystemExit(1) from exc
    except Exception as exc:
        log_error(exc, {"command": "google_ask", "request": request})
        console.print(f"[red]Error: {exc}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Gmail sub-group
# ─────────────────────────────────────────────────────────────────────────────

@google.group()
def gmail() -> None:
    """Gmail commands — list, search, read, send."""


@gmail.command("list")
@click.option("--limit", "-n", default=None, type=int, help="Max results (default: GOOGLE_LIST_LIMIT).")
@click.option("--label", default="INBOX", help="Gmail label (default: INBOX).")
@click.option("--query", "-q", default="", help="Gmail search filter.")
def gmail_list(limit: int | None, label: str, query: str) -> None:
    """List recent emails."""
    _gmail_list_impl(limit, label, query)


def _gmail_list_impl(limit, label, query):
    start = time.time()
    try:
        from jrvs.google.gmail_client import GmailClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Fetching Gmail messages…", total=None)
            msgs = GmailClient().list_messages(max_results=limit, label=label, query=query)

        console.print()
        tbl = Table(title=f"Gmail — {label}", box=box.ROUNDED, show_lines=True)
        tbl.add_column("#",        style="dim", width=3)
        tbl.add_column("From",     max_width=28)
        tbl.add_column("Subject",  max_width=45, style="bold white")
        tbl.add_column("Date",     max_width=20, style="dim")
        tbl.add_column("ID",       max_width=18, style="dim cyan")
        for i, m in enumerate(msgs, 1):
            tbl.add_row(str(i), m["from"][:28], m["subject"][:45], m["date"][:20], m["id"][:18])
        console.print(tbl)
        log_performance("gmail_list", time.time() - start)
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@gmail.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=None, type=int)
def gmail_search(query: str, limit: int | None) -> None:
    """Search emails with Gmail query syntax."""
    _gmail_list_impl(limit, "INBOX", query)


@gmail.command("read")
@click.argument("message_id")
def gmail_read(message_id: str) -> None:
    """Read full email body by message ID."""
    try:
        from jrvs.google.gmail_client import GmailClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Fetching email…", total=None)
            msg = GmailClient().read_message(message_id)

        console.print()
        console.print(Panel(
            f"[bold]From:[/]    {msg['from']}\n"
            f"[bold]To:[/]      {msg['to']}\n"
            f"[bold]Subject:[/] {msg['subject']}\n"
            f"[bold]Date:[/]    {msg['date']}\n"
            f"[bold]Labels:[/]  {', '.join(msg.get('labels', []))}\n\n"
            f"{msg['body'][:3000] or '[no plain-text body]'}",
            title="[bold green]Email[/]",
            border_style="cyan",
            expand=True,
        ))
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@gmail.command("labels")
def gmail_labels() -> None:
    """List all Gmail labels/folders."""
    try:
        from jrvs.google.gmail_client import GmailClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Fetching labels…", total=None)
            labels = GmailClient().list_labels()
        tbl = Table(title="Gmail Labels", box=box.ROUNDED, show_lines=True)
        tbl.add_column("Name",  style="bold white", max_width=40)
        tbl.add_column("ID",    style="dim cyan",   max_width=40)
        tbl.add_column("Type",  style="dim",        max_width=12)
        for lbl in sorted(labels, key=lambda x: x.get("name", "")):
            tbl.add_row(lbl.get("name", ""), lbl.get("id", ""), lbl.get("type", ""))
        console.print(tbl)
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@gmail.command("reply")
@click.argument("message_id")
@click.option("--body", required=True, help="Reply body text.")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation.")
def gmail_reply(message_id: str, body: str, yes: bool) -> None:
    """Reply to an email thread."""
    try:
        if not yes:
            console.print()
            console.print(Panel(
                f"[bold]Reply to thread:[/] {message_id}\n\n{body}",
                title="[bold yellow]📧 Reply Draft — Review Before Sending[/]",
                border_style="yellow", expand=False,
            ))
            if not click.confirm("Send this reply?", default=True):
                console.print("[yellow]Cancelled.[/]")
                return
        from jrvs.google.gmail_client import GmailClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Sending reply…", total=None)
            result = GmailClient().reply_to_message(message_id, body)
        console.print(Panel(
            f"[bold green]✓ Reply sent![/]\nMessage ID: [cyan]{result.get('id', '')}[/]",
            border_style="green", expand=False,
        ))
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@gmail.command("send")
@click.option("--to",      required=True, help="Recipient email address.")
@click.option("--subject", required=True, help="Email subject.")
@click.option("--body",    required=True, help="Email body text.")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation.")
def gmail_send(to: str, subject: str, body: str, yes: bool) -> None:
    """Send a new email (shows a preview first)."""
    try:
        if not yes:
            console.print()
            console.print(Panel(
                f"[bold]To:[/]      {to}\n"
                f"[bold]Subject:[/] {subject}\n\n"
                f"{body}",
                title="[bold yellow]📧 Email Draft — Review Before Sending[/]",
                border_style="yellow",
                expand=False,
            ))
            if not click.confirm("Send this email?", default=True):
                console.print("[yellow]Cancelled.[/]")
                return

        from jrvs.google.gmail_client import GmailClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task(f"Sending email to {to}…", total=None)
            result = GmailClient().send_message(to, subject, body)
        console.print(Panel(
            f"[bold green]✓ Email sent![/]\nMessage ID: [cyan]{result.get('id', '')}[/]",
            border_style="green", expand=False,
        ))
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Docs sub-group
# ─────────────────────────────────────────────────────────────────────────────

@google.group()
def docs() -> None:
    """Google Docs commands — list, read, find, create, append."""


@docs.command("list")
@click.option("--limit", "-n", default=None, type=int)
def docs_list(limit: int | None) -> None:
    """List recent Google Docs."""
    try:
        from jrvs.google.docs_client import DocsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Fetching Google Docs…", total=None)
            files = DocsClient().list_documents(max_results=limit)

        tbl = Table(title="Google Docs", box=box.ROUNDED, show_lines=True)
        tbl.add_column("#",        style="dim", width=3)
        tbl.add_column("Name",     max_width=45, style="bold white")
        tbl.add_column("Modified", max_width=22, style="dim")
        tbl.add_column("ID",       max_width=44, style="dim cyan")
        for i, f in enumerate(files, 1):
            tbl.add_row(str(i), f["name"][:45], f["modified"][:22], f["id"])
        console.print(tbl)
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@docs.command("find")
@click.argument("name")
def docs_find(name: str) -> None:
    """Find a doc by name and print its content."""
    try:
        from jrvs.google.docs_client import DocsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task(f"Searching for \"{name}\"…", total=None)
            doc = DocsClient().find_document_by_name(name)
        if not doc:
            console.print(f"[yellow]No document found matching '{name}'[/]")
            return
        _print_doc(doc)
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@docs.command("read")
@click.argument("document_id")
def docs_read(document_id: str) -> None:
    """Read full text of a Google Doc by its ID."""
    try:
        from jrvs.google.docs_client import DocsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Reading document…", total=None)
            doc = DocsClient().read_document(document_id)
        _print_doc(doc)
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@docs.command("create")
@click.option("--title",   required=True, help="Document title.")
@click.option("--content", default="",    help="Initial text content.")
@click.option("--ai",      is_flag=True,  help="Use AI + RAG to generate the content.")
@click.option("--topic",   default="",    help="Topic/prompt for AI content generation (used with --ai).")
def docs_create(title: str, content: str, ai: bool, topic: str) -> None:
    """Create a new Google Doc.  Pass --ai to let the LLM write the content using your knowledge base."""
    try:
        if ai:
            prompt_topic = topic or title
            console.print(f"\n[bold blue]Generating AI content for:[/] {prompt_topic}\n")
            with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
                p.add_task("Searching knowledge base + generating content…", total=None)
                content = _ai_generate_content(prompt_topic)
            # Preview
            console.print(Panel(content[:2000] + ("…" if len(content) > 2000 else ""),
                title="[bold yellow]AI-Generated Content — Preview[/]", border_style="yellow", expand=True))
            if not click.confirm("Use this content?", default=True):
                content = click.edit(content) or content

        from jrvs.google.docs_client import DocsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task(f"Creating '{title}'…", total=None)
            doc = DocsClient().create_document(title, content)
        console.print(Panel(
            f"[bold green]✓ Document created![/]\n"
            f"Title: [bold]{doc['title']}[/]\n"
            f"ID:    [cyan]{doc['id']}[/]\n"
            f"URL:   {doc['url']}",
            border_style="green", expand=False,
        ))
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@docs.command("append")
@click.argument("document_id")
@click.option("--text",  default="", help="Text to append.")
@click.option("--ai",    is_flag=True, help="Use AI + RAG to generate the appended text.")
@click.option("--topic", default="",  help="Topic/prompt for AI generation (used with --ai).")
def docs_append(document_id: str, text: str, ai: bool, topic: str) -> None:
    """Append text to an existing Google Doc.  Pass --ai to let the LLM generate the text."""
    try:
        if ai:
            prompt_topic = topic or click.prompt("Topic / instructions for the AI")
            console.print(f"\n[bold blue]Generating AI content for:[/] {prompt_topic}\n")
            with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
                p.add_task("Searching knowledge base + generating content…", total=None)
                text = _ai_generate_content(prompt_topic)
            console.print(Panel(text[:2000] + ("…" if len(text) > 2000 else ""),
                title="[bold yellow]AI-Generated Snippet — Preview[/]", border_style="yellow", expand=True))
            if not click.confirm("Append this content?", default=True):
                text = click.edit(text) or text
        elif not text:
            console.print("[red]Provide --text or use --ai to generate content.[/]")
            return

        from jrvs.google.docs_client import DocsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Appending text…", total=None)
            result = DocsClient().append_to_document(document_id, text)
        console.print(f"[green]✓ Appended {result['appended_chars']} characters to document {document_id}[/]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@docs.command("replace")
@click.argument("document_id")
@click.option("--find",         required=True, help="Text to find.")
@click.option("--replace-with", required=True, help="Replacement text.")
def docs_replace(document_id: str, find: str, replace_with: str) -> None:
    """Find and replace text inside a Google Doc."""
    try:
        from jrvs.google.docs_client import DocsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Replacing text…", total=None)
            result = DocsClient().replace_in_document(document_id, find, replace_with)
        console.print(f"[green]✓ Replaced {result.get('replacements_made', '?')} occurrence(s).[/]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Sheets sub-group
# ─────────────────────────────────────────────────────────────────────────────

@google.group()
def sheets() -> None:
    """Google Sheets commands — list, read, find, write, create."""


@sheets.command("list")
@click.option("--limit", "-n", default=None, type=int)
def sheets_list(limit: int | None) -> None:
    """List recent Google Sheets."""
    try:
        from jrvs.google.sheets_client import SheetsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Fetching Google Sheets…", total=None)
            files = SheetsClient().list_spreadsheets(max_results=limit)

        tbl = Table(title="Google Sheets", box=box.ROUNDED, show_lines=True)
        tbl.add_column("#",        style="dim", width=3)
        tbl.add_column("Name",     max_width=45, style="bold white")
        tbl.add_column("Modified", max_width=22, style="dim")
        tbl.add_column("ID",       max_width=44, style="dim cyan")
        for i, f in enumerate(files, 1):
            tbl.add_row(str(i), f["name"][:45], f["modified"][:22], f["id"])
        console.print(tbl)
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@sheets.command("find")
@click.argument("name")
def sheets_find(name: str) -> None:
    """Find a spreadsheet by name."""
    try:
        from jrvs.google.sheets_client import SheetsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task(f"Searching for \"{name}\"…", total=None)
            result = SheetsClient().find_spreadsheet_by_name(name)
        if not result:
            console.print(f"[yellow]No spreadsheet found matching '{name}'[/]")
            return
        console.print(Panel(
            f"[bold]Name:[/] {result['name']}\n"
            f"[bold]ID:[/]   [cyan]{result['id']}[/]\n"
            f"[bold]URL:[/]  {result['url']}",
            title="[bold green]Spreadsheet Found[/]", border_style="green", expand=False,
        ))
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@sheets.command("read")
@click.argument("spreadsheet_id")
@click.option("--range", "-r", "range_", default="Sheet1", help="Range e.g. Sheet1!A1:D20.")
@click.option("--limit", "-n", default=50,  type=int, help="Max rows to display.")
def sheets_read(spreadsheet_id: str, range_: str, limit: int) -> None:
    """Read cell values from a spreadsheet."""
    try:
        from jrvs.google.sheets_client import SheetsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Reading sheet data…", total=None)
            data = SheetsClient().read_range(spreadsheet_id, range_)

        values = data["values"][:limit]
        if not values:
            console.print("[yellow]No data found in that range.[/]")
            return

        tbl = Table(title=f"{range_}  ({data['rows']} rows × {data['cols']} cols)", box=box.ROUNDED, show_lines=True)
        # Use first row as header if it looks like one
        headers = values[0] if values else []
        for h in headers:
            tbl.add_column(str(h)[:20], style="bold cyan")
        for row in values[1:]:
            tbl.add_row(*[str(c)[:20] for c in row])
        console.print(tbl)
        if data["rows"] > limit:
            console.print(f"[dim](showing first {limit} of {data['rows']} rows)[/]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@sheets.command("append")
@click.argument("spreadsheet_id")
@click.option("--range",  "-r", "range_",  default="Sheet1", help="Target range.")
@click.option("--values", "-v", required=True, help="JSON 2-D array e.g. '[[\"a\",1],[\"b\",2]]'.")
def sheets_append(spreadsheet_id: str, range_: str, values: str) -> None:
    """Append rows to a spreadsheet."""
    try:
        rows = json.loads(values)
        from jrvs.google.sheets_client import SheetsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Appending rows…", total=None)
            result = SheetsClient().append_rows(spreadsheet_id, range_, rows)
        console.print(Panel(
            f"[bold green]✓ Appended {result['appended_rows']} row(s)[/]\n"
            f"Range: [cyan]{result['appended_range']}[/]",
            border_style="green", expand=False,
        ))
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON in --values: {exc}[/]")
        raise SystemExit(1) from exc
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@sheets.command("info")
@click.argument("spreadsheet_id")
def sheets_info(spreadsheet_id: str) -> None:
    """Show spreadsheet metadata — sheet names, row/column counts."""
    try:
        from jrvs.google.sheets_client import SheetsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Fetching spreadsheet info…", total=None)
            info = SheetsClient().get_spreadsheet_info(spreadsheet_id)
        console.print(Panel(
            f"[bold]Title:[/] {info['title']}\n"
            f"[bold]ID:[/]    [cyan]{info['id']}[/]\n"
            f"[bold]URL:[/]   {info.get('url', '')}\n\n"
            + "\n".join(
                f"  [bold]{s['title']}[/]  {s.get('row_count','?')} rows × {s.get('col_count','?')} cols"
                for s in info.get('sheets', [])
            ),
            title="[bold green]Spreadsheet Info[/]", border_style="cyan", expand=False,
        ))
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@sheets.command("write")
@click.argument("spreadsheet_id")
@click.option("--range",  "-r", "range_",  required=True, help="Target range e.g. Sheet1!A1:C3.")
@click.option("--values", "-v", default="",              help="JSON 2-D array e.g. '[[\"a\",1]]'.")
@click.option("--ai",           is_flag=True,            help="Use AI + RAG to generate the values.")
@click.option("--topic",        default="",              help="Topic/prompt for AI generation (--ai).")
def sheets_write(spreadsheet_id: str, range_: str, values: str, ai: bool, topic: str) -> None:
    """Write values to a specific range.  Pass --ai to let the LLM generate the data."""
    try:
        rows: list
        if ai:
            prompt_topic = topic or range_
            console.print(f"\n[bold blue]Generating AI data for:[/] {prompt_topic}\n")
            with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
                p.add_task("Searching knowledge base + generating table data…", total=None)
                raw_text = _ai_generate_content(
                    prompt_topic,
                    "Return ONLY a JSON 2-D array (list of lists) suitable for a spreadsheet. No explanation.",
                )
            # Try to parse JSON array from LLM response
            import re
            m = re.search(r"(\[\s*\[.+?\]\s*\])", raw_text, re.DOTALL)
            if m:
                rows = json.loads(m.group(1))
            else:
                console.print("[red]AI could not produce a valid 2-D array. Try specifying a clearer --topic.[/]")
                return
            # Preview
            tbl_prev = Table(box=box.SIMPLE, title="AI-Generated Data Preview")
            if rows:
                for h in rows[0]: tbl_prev.add_column(str(h)[:20])
                for row in rows[1:]: tbl_prev.add_row(*[str(c)[:20] for c in row])
            console.print(tbl_prev)
            if not click.confirm("Write this data to the sheet?", default=True):
                console.print("[yellow]Aborted.[/]")
                return
        elif values:
            rows = json.loads(values)
        else:
            console.print("[red]Provide --values or use --ai to generate data.[/]")
            return

        from jrvs.google.sheets_client import SheetsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Writing data…", total=None)
            result = SheetsClient().write_range(spreadsheet_id, range_, rows)
        console.print(Panel(
            f"[bold green]✓ Written {result.get('updated_cells', '?')} cell(s)[/]\n"
            f"Range: [cyan]{result.get('updated_range', range_)}[/]",
            border_style="green", expand=False,
        ))
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON in --values: {exc}[/]")
        raise SystemExit(1) from exc
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@sheets.command("clear")
@click.argument("spreadsheet_id")
@click.option("--range", "-r", "range_", required=True, help="Range to clear e.g. Sheet1!A1:Z100.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
def sheets_clear(spreadsheet_id: str, range_: str, yes: bool) -> None:
    """Clear all values in a spreadsheet range."""
    try:
        if not yes and not click.confirm(f"Clear range {range_} in {spreadsheet_id}?"):
            console.print("[yellow]Aborted.[/]")
            return
        from jrvs.google.sheets_client import SheetsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Clearing range…", total=None)
            result = SheetsClient().clear_range(spreadsheet_id, range_)
        console.print(f"[green]✓ Cleared {result.get('cleared_range', range_)}.[/]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@sheets.command("create")
@click.option("--title",       required=True,  help="Spreadsheet title.")
@click.option("--sheet-names", default=None,   help="Comma-separated sheet names.")
def sheets_create(title: str, sheet_names: str | None) -> None:
    """Create a new Google Sheets spreadsheet."""
    try:
        names = [s.strip() for s in sheet_names.split(",")] if sheet_names else None
        from jrvs.google.sheets_client import SheetsClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task(f"Creating '{title}'…", total=None)
            ss = SheetsClient().create_spreadsheet(title, names)
        console.print(Panel(
            f"[bold green]✓ Spreadsheet created![/]\n"
            f"Title: [bold]{ss['title']}[/]\n"
            f"ID:    [cyan]{ss['id']}[/]\n"
            f"URL:   {ss['url']}",
            border_style="green", expand=False,
        ))
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Calendar sub-group
# ─────────────────────────────────────────────────────────────────────────────

@google.group()
def calendar() -> None:
    """Google Calendar commands — list, find, create, delete."""


@calendar.command("list")
@click.option("--limit", "-n",   default=None,       type=int,  help="Max events.")
@click.option("--from",  "from_", default=None,                  help="Start datetime (ISO 8601).")
@click.option("--to",    "to_",   default=None,                  help="End datetime (ISO 8601).")
@click.option("--cal",           default="primary",              help="Calendar ID (default: primary).")
def calendar_list(limit: int | None, from_: str | None, to_: str | None, cal: str) -> None:
    """List upcoming calendar events."""
    try:
        from jrvs.google.calendar_client import CalendarClient
        kw = {"calendar_id": cal}
        if limit:  kw["max_results"] = limit
        if from_:  kw["time_min"] = from_
        if to_:    kw["time_max"] = to_
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Fetching calendar events…", total=None)
            events = CalendarClient().list_events(**kw)
        _print_events(events, f"Calendar: {cal}")
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@calendar.command("find")
@click.argument("query")
@click.option("--limit", "-n", default=None, type=int)
@click.option("--cal",         default="primary")
def calendar_find(query: str, limit: int | None, cal: str) -> None:
    """Search events by keyword."""
    try:
        from jrvs.google.calendar_client import CalendarClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task(f"Searching for \"{query}\"…", total=None)
            events = CalendarClient().find_events(query, cal, limit)
        _print_events(events, f"Search: {query}")
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@calendar.command("create")
@click.option("--title",       required=True,  help="Event title.")
@click.option("--start",       required=True,  help="Start datetime e.g. '2026-03-01T10:00:00'.")
@click.option("--end",         required=True,  help="End datetime.")
@click.option("--description", default="",     help="Event description.")
@click.option("--location",    default="",     help="Event location.")
@click.option("--attendees",   default=None,   help="Comma-separated email addresses.")
@click.option("--cal",         default="primary")
@click.option("--all-day",     is_flag=True,   help="All-day event (use YYYY-MM-DD for start/end).")
def calendar_create(
    title: str, start: str, end: str, description: str,
    location: str, attendees: str | None, cal: str, all_day: bool,
) -> None:
    """Create a new calendar event."""
    try:
        att_list = [e.strip() for e in attendees.split(",")] if attendees else None
        from jrvs.google.calendar_client import CalendarClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task(f"Creating event '{title}'…", total=None)
            ev = CalendarClient().create_event(
                summary=title, start=start, end=end,
                description=description, location=location,
                attendees=att_list, calendar_id=cal, all_day=all_day,
            )
        console.print(Panel(
            f"[bold green]✓ Event created![/]\n"
            f"Title:   [bold]{ev['summary']}[/]\n"
            f"Start:   [cyan]{ev['start']}[/]\n"
            f"End:     [cyan]{ev['end']}[/]\n"
            f"Link:    {ev['html_link']}\n"
            f"ID:      [dim]{ev['id']}[/]",
            border_style="green", expand=False,
        ))
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@calendar.command("update")
@click.argument("event_id")
@click.option("--title",       default=None, help="New event title.")
@click.option("--start",       default=None, help="New start datetime (ISO 8601).")
@click.option("--end",         default=None, help="New end datetime (ISO 8601).")
@click.option("--description", default=None, help="New description.")
@click.option("--location",    default=None, help="New location.")
@click.option("--cal",         default="primary")
def calendar_update(
    event_id: str,
    title: str | None,
    start: str | None,
    end: str | None,
    description: str | None,
    location: str | None,
    cal: str,
) -> None:
    """Edit fields on an existing calendar event."""
    updates: dict = {k: v for k, v in {
        "summary": title, "start": start, "end": end,
        "description": description, "location": location,
    }.items() if v is not None}
    if not updates:
        console.print("[yellow]Nothing to update — provide at least one option (--title, --start, …).[/]")
        return
    try:
        from jrvs.google.calendar_client import CalendarClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task(f"Updating event {event_id[:12]}…", total=None)
            ev = CalendarClient().update_event(event_id, cal, **updates)
        console.print(Panel(
            f"[bold green]✓ Event updated![/]\n"
            f"Title: [bold]{ev['summary']}[/]\n"
            f"Start: [cyan]{ev['start']}[/]\n"
            f"End:   [cyan]{ev['end']}[/]\n"
            f"Link:  {ev['html_link']}",
            border_style="green", expand=False,
        ))
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@calendar.command("delete")
@click.argument("event_id")
@click.option("--cal", default="primary")
@click.confirmation_option(prompt="Are you sure you want to delete this event?")
def calendar_delete(event_id: str, cal: str) -> None:
    """Delete a calendar event by ID."""
    try:
        from jrvs.google.calendar_client import CalendarClient
        CalendarClient().delete_event(event_id, cal)
        console.print(f"[green]✓ Event {event_id} deleted.[/]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@calendar.command("calendars")
def calendar_calendars() -> None:
    """List all Google Calendars on this account."""
    try:
        from jrvs.google.calendar_client import CalendarClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Fetching calendars…", total=None)
            cals = CalendarClient().list_calendars()
        tbl = Table(title="Google Calendars", box=box.ROUNDED, show_lines=True)
        tbl.add_column("Primary", width=7, style="bold yellow")
        tbl.add_column("Name",    max_width=40, style="bold white")
        tbl.add_column("Access",  max_width=14, style="dim")
        tbl.add_column("ID",      max_width=50, style="dim cyan")
        for c in cals:
            tbl.add_row("★" if c["primary"] else "", c["summary"][:40], c["access"], c["id"])
        console.print(tbl)
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _print_doc(doc: dict) -> None:
    console.print()
    console.print(Panel(
        f"[bold]Title:[/] {doc['title']}\n"
        f"[bold]ID:[/]    [cyan]{doc['id']}[/]\n"
        f"[bold]URL:[/]   {doc.get('url', '')}\n\n"
        f"{doc.get('text', '')[:4000] or '[empty document]'}",
        title="[bold green]Google Doc[/]",
        border_style="cyan",
        expand=True,
    ))


def _ai_generate_content(topic: str, extra_instruction: str = "") -> str:
    """Query the vector store for context, then ask the LLM to write content about *topic*."""
    rag_context = ""
    try:
        from jrvs.embeddings.vector_store import VectorStore
        from jrvs.embeddings.encoder import EmbeddingEncoder
        EmbeddingEncoder.get()  # ensure encoder singleton is initialised before VectorStore.search
        vs = VectorStore()
        results = vs.search(topic, top_k=5)
        if results:
            rag_context = "\n\n".join(
                (r.get("text") or r.get("content") or "")[:500]
                for r in results[:5]
            )
    except Exception:
        pass  # RAG unavailable — LLM generates from training knowledge only

    from jrvs.llm.ollama_client import OllamaClient
    llm = OllamaClient()

    system = (
        "You are a professional content writer. "
        "Write clear, well-structured content using markdown-style headings (##). "
        "Be thorough and informative."
    )
    user_msg = f"Write content about: {topic}\n"
    if rag_context:
        user_msg += f"\nRelevant context from knowledge base:\n{rag_context}\n"
    if extra_instruction:
        user_msg += f"\nAdditional instruction: {extra_instruction}\n"
    user_msg += "\nWrite the full content now:"

    return llm.chat(messages=[
        {"role": "system", "content": system},
        {"role": "user",   "content": user_msg},
    ])


def _print_events(events: list, title: str = "Events") -> None:
    if not events:
        console.print("[yellow]No events found.[/]")
        return
    tbl = Table(title=title, box=box.ROUNDED, show_lines=True)
    tbl.add_column("#",       style="dim", width=3)
    tbl.add_column("Title",   max_width=36, style="bold white")
    tbl.add_column("Start",   max_width=22, style="cyan")
    tbl.add_column("End",     max_width=22, style="dim")
    tbl.add_column("Where",   max_width=20, style="dim")
    tbl.add_column("ID",      max_width=26, style="dim cyan")
    for i, ev in enumerate(events, 1):
        tbl.add_row(
            str(i),
            ev["summary"][:36],
            ev["start"][:22],
            ev["end"][:22],
            (ev.get("location") or "")[:20],
            ev["id"][:26],
        )
    console.print(tbl)
