"""
JRVS Nextcloud (CalDAV) CLI sub-commands.

Usage
─────
  jrvs nextcloud calendars                     # List calendars on the account
  jrvs nextcloud list                          # Upcoming events
  jrvs nextcloud find "keyword"                 # Search events
  jrvs nextcloud create --title "..." ...       # Create an event
  jrvs nextcloud update <event-id> ...          # Edit an existing event
  jrvs nextcloud delete <event-id>              # Delete an event
"""

from __future__ import annotations

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()


@click.group(invoke_without_command=True)
@click.pass_context
def nextcloud(ctx) -> None:
    """Nextcloud calendar commands (CalDAV) — list, find, create, update, delete."""
    if ctx.invoked_subcommand is None:
        console.print(Panel(
            "[bold white]Nextcloud Calendar Commands (CalDAV)[/]\n\n"
            "  [bold cyan]jrvs nextcloud calendars[/]           List all calendars\n"
            "  [bold cyan]jrvs nextcloud list[/]                Upcoming events\n"
            "  [bold cyan]jrvs nextcloud find \"keyword\"[/]      Search events\n"
            "  [bold cyan]jrvs nextcloud create[/]              Create an event\n"
            "  [bold cyan]jrvs nextcloud update <id>[/]         Edit an existing event\n"
            "  [bold cyan]jrvs nextcloud delete <id>[/]         Delete an event\n\n"
            "[dim]Requires NEXTCLOUD_URL, NEXTCLOUD_USER and NEXTCLOUD_APP_PASSWORD "
            "in .env (Nextcloud Settings → Security → Devices & sessions → app password).[/dim]",
            title="[bold]jrvs nextcloud[/]",
            border_style="blue",
            box=box.DOUBLE,
            expand=False,
            padding=(1, 3),
        ))


@nextcloud.command("calendars")
def nextcloud_calendars() -> None:
    """List all calendars on this Nextcloud account."""
    try:
        from jrvs.nextcloud.caldav_client import CalDAVClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Fetching calendars…", total=None)
            cals = CalDAVClient().list_calendars()
        tbl = Table(title="Nextcloud Calendars", box=box.ROUNDED, show_lines=True)
        tbl.add_column("Name", max_width=40, style="bold white")
        tbl.add_column("ID",   max_width=40, style="dim cyan")
        tbl.add_column("URL",  max_width=60, style="dim")
        for c in cals:
            tbl.add_row(c["name"], c["id"], c["url"])
        console.print(tbl)
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@nextcloud.command("list")
@click.option("--limit", "-n",   default=None, type=int, help="Max events.")
@click.option("--from",  "from_", default=None,           help="Start datetime (ISO 8601).")
@click.option("--to",    "to_",   default=None,           help="End datetime (ISO 8601).")
@click.option("--cal",            default="",              help="Calendar name (default: NEXTCLOUD_CALENDAR).")
def nextcloud_list(limit: int | None, from_: str | None, to_: str | None, cal: str) -> None:
    """List upcoming calendar events."""
    try:
        from jrvs.nextcloud.caldav_client import CalDAVClient
        kw = {"calendar_name": cal or None}
        if limit:  kw["max_results"] = limit
        if from_:  kw["time_min"] = from_
        if to_:    kw["time_max"] = to_
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task("Fetching calendar events…", total=None)
            events = CalDAVClient().list_events(**kw)
        _print_events(events, f"Calendar: {cal or '(default)'}")
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@nextcloud.command("find")
@click.argument("query")
@click.option("--limit", "-n", default=None, type=int)
@click.option("--cal",         default="")
def nextcloud_find(query: str, limit: int | None, cal: str) -> None:
    """Search events by keyword."""
    try:
        from jrvs.nextcloud.caldav_client import CalDAVClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task(f"Searching for \"{query}\"…", total=None)
            events = CalDAVClient().find_events(query, cal or None, limit)
        _print_events(events, f"Search: {query}")
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@nextcloud.command("create")
@click.option("--title",       required=True,  help="Event title.")
@click.option("--start",       required=True,  help="Start datetime e.g. '2026-03-01T10:00:00'.")
@click.option("--end",         required=True,  help="End datetime.")
@click.option("--description", default="",     help="Event description.")
@click.option("--location",    default="",     help="Event location.")
@click.option("--cal",         default="",     help="Calendar name (default: NEXTCLOUD_CALENDAR).")
@click.option("--all-day",     is_flag=True,   help="All-day event (use YYYY-MM-DD for start/end).")
def nextcloud_create(
    title: str, start: str, end: str, description: str,
    location: str, cal: str, all_day: bool,
) -> None:
    """Create a new calendar event."""
    try:
        from jrvs.nextcloud.caldav_client import CalDAVClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task(f"Creating event '{title}'…", total=None)
            ev = CalDAVClient().create_event(
                summary=title, start=start, end=end,
                description=description, location=location,
                calendar_name=cal or None, all_day=all_day,
            )
        console.print(Panel(
            f"[bold green]✓ Event created![/]\n"
            f"Title:   [bold]{ev['summary']}[/]\n"
            f"Start:   [cyan]{ev['start']}[/]\n"
            f"End:     [cyan]{ev['end']}[/]\n"
            f"ID:      [dim]{ev['id']}[/]",
            border_style="green", expand=False,
        ))
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@nextcloud.command("update")
@click.argument("event_id")
@click.option("--title",       default=None, help="New event title.")
@click.option("--start",       default=None, help="New start datetime (ISO 8601).")
@click.option("--end",         default=None, help="New end datetime (ISO 8601).")
@click.option("--description", default=None, help="New description.")
@click.option("--location",    default=None, help="New location.")
@click.option("--cal",         default="")
def nextcloud_update(
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
        from jrvs.nextcloud.caldav_client import CalDAVClient
        with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console) as p:
            p.add_task(f"Updating event {event_id[:12]}…", total=None)
            ev = CalDAVClient().update_event(event_id, cal or None, **updates)
        console.print(Panel(
            f"[bold green]✓ Event updated![/]\n"
            f"Title: [bold]{ev['summary']}[/]\n"
            f"Start: [cyan]{ev['start']}[/]\n"
            f"End:   [cyan]{ev['end']}[/]",
            border_style="green", expand=False,
        ))
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


@nextcloud.command("delete")
@click.argument("event_id")
@click.option("--cal", default="")
@click.confirmation_option(prompt="Are you sure you want to delete this event?")
def nextcloud_delete(event_id: str, cal: str) -> None:
    """Delete a calendar event by UID."""
    try:
        from jrvs.nextcloud.caldav_client import CalDAVClient
        CalDAVClient().delete_event(event_id, cal or None)
        console.print(f"[green]✓ Event {event_id} deleted.[/]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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
