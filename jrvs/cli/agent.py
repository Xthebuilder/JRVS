"""
JRVS CLI — autonomous agent commands.

  jrvs agent run [--schedule <s>] [--goal <id>] [--dry-run]
  jrvs agent status [--limit N]
  jrvs agent pending
  jrvs agent approve <action-id>
  jrvs agent deny    <action-id>
  jrvs agent pause / resume
  jrvs agent logs [--run-id <id>] [--limit N]
  jrvs agent goals
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table   import Table
from rich         import box

console = Console()


@click.group("agent")
def agent() -> None:
    """Autonomous agent — schedule, run and manage AI-driven goals."""


# ─────────────────────────────────────────────────────────────────────────────
# run
# ─────────────────────────────────────────────────────────────────────────────

@agent.command("run")
@click.option("--schedule", "-s", default="manual",
              help="Schedule label to run (morning/hourly/daily/weekly/manual).")
@click.option("--goal", "-g", "goal_id", default=None,
              help="Run a single goal ID instead of all goals for the schedule.")
@click.option("--dry-run", "dry_run", is_flag=True,
              help="Show plan without making any API calls.")
def run_cmd(schedule: str, goal_id: str | None, dry_run: bool) -> None:
    """Run all goals for a schedule (or a single goal)."""
    from jrvs.agent.runner import AgentRunner

    if dry_run:
        console.print("[yellow]Dry-run mode[/yellow] — no API calls will be made.\n")

    runner = AgentRunner(dry_run=dry_run)
    results = runner.run(schedule=schedule, goal_id=goal_id)

    if not results:
        console.print("[dim]No goals were run.[/dim]")
        return

    for r in results:
        _print_run_result(r)


def _print_run_result(r) -> None:
    colour = {"success": "green", "partial": "yellow",
              "error": "red", "dry_run": "cyan", "skipped": "dim"}.get(r.status, "white")
    console.print(f"\n[bold {colour}]{r.goal_id}[/bold {colour}] "
                  f"[dim]({r.run_id[:8]})[/dim] — [{colour}]{r.status}[/{colour}]")
    if r.summary:
        console.print(f"  {r.summary}")
    if r.error:
        console.print(f"  [red]{r.error}[/red]")

    pending = [x for x in r.results if x.get("status") == "awaiting_approval"]
    if pending:
        console.print(f"  [yellow]{len(pending)} action(s) awaiting approval[/yellow]")
        for x in pending:
            console.print(f"    jrvs agent approve {x['action_id']}")

    if r.plan and r.status == "dry_run":
        tbl = Table(box=box.SIMPLE, show_header=True)
        tbl.add_column("#",      style="dim",    width=3)
        tbl.add_column("Tool",   style="bold",   width=24)
        tbl.add_column("Tier",                   width=8)
        tbl.add_column("Reason",                 overflow="fold")
        for step in r.plan:
            tier    = step.get("tier", "")
            colour2 = {"auto": "green", "notify": "blue",
                       "confirm": "yellow", "blocked": "red"}.get(tier, "white")
            tbl.add_row(
                str(step.get("step", "")),
                step.get("tool", ""),
                f"[{colour2}]{tier}[/{colour2}]",
                step.get("reason", ""),
            )
        console.print(tbl)


# ─────────────────────────────────────────────────────────────────────────────
# status
# ─────────────────────────────────────────────────────────────────────────────

@agent.command("status")
@click.option("--limit", "-n", default=10, show_default=True,
              help="Number of recent runs to show.")
def status_cmd(limit: int) -> None:
    """Show recent agent runs."""
    from jrvs.storage.database import Database
    db = Database()
    rows = db.get_recent_runs(limit=limit)

    if not rows:
        console.print("[dim]No runs found.[/dim]")
        return

    tbl = Table(title="Recent Agent Runs", box=box.SIMPLE_HEAD)
    tbl.add_column("Run ID",  style="dim",  width=10)
    tbl.add_column("Goal",    style="bold", width=22)
    tbl.add_column("Status",               width=10)
    tbl.add_column("Created",              width=20)
    tbl.add_column("Summary",              overflow="fold")

    for row in rows:
        status = row.get("status", "")
        colour = {"success": "green", "partial": "yellow",
                  "error": "red", "dry_run": "cyan"}.get(status, "white")
        tbl.add_row(
            (row.get("run_id") or "")[:8],
            row.get("goal_id", ""),
            f"[{colour}]{status}[/{colour}]",
            (row.get("created_at") or "")[:16],
            (row.get("summary") or "")[:80],
        )
    console.print(tbl)


# ─────────────────────────────────────────────────────────────────────────────
# pending
# ─────────────────────────────────────────────────────────────────────────────

@agent.command("pending")
def pending_cmd() -> None:
    """List actions awaiting approval."""
    from jrvs.storage.database import Database
    db   = Database()
    rows = db.get_pending_actions()

    if not rows:
        console.print("[green]No actions awaiting approval.[/green]")
        return

    tbl = Table(title="Pending Actions", box=box.SIMPLE_HEAD)
    tbl.add_column("Action ID",  style="dim",  width=38)
    tbl.add_column("Run ID",     style="dim",  width=10)
    tbl.add_column("Tool",       style="bold", width=20)
    tbl.add_column("Args",                     overflow="fold")
    tbl.add_column("Reason",                   overflow="fold")

    for row in rows:
        tbl.add_row(
            row.get("action_id", ""),
            (row.get("run_id") or "")[:8],
            row.get("tool", ""),
            (row.get("args_json") or "")[:60],
            (row.get("reason") or "")[:60],
        )
    console.print(tbl)
    console.print("\n  [dim]jrvs agent approve <action-id>[/dim]")
    console.print("  [dim]jrvs agent deny    <action-id>[/dim]")


# ─────────────────────────────────────────────────────────────────────────────
# approve / deny
# ─────────────────────────────────────────────────────────────────────────────

@agent.command("approve")
@click.argument("action_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def approve_cmd(action_id: str, yes: bool) -> None:
    """Approve and execute a queued CONFIRM-tier action."""
    from jrvs.storage.database import Database
    from jrvs.agent.executor   import Executor

    db  = Database()
    row = db.get_action(action_id)
    if not row:
        console.print(f"[red]Action '{action_id}' not found.[/red]")
        return

    console.print(f"\nTool  : [bold]{row.get('tool')}[/bold]")
    console.print(f"Args  : {row.get('args_json', '')[:120]}")
    console.print(f"Reason: {row.get('reason', '')}\n")

    if not yes and not click.confirm("Execute this action?"):
        console.print("[dim]Aborted.[/dim]")
        return

    ex  = Executor(db=db)
    res = ex.execute_approved(action_id)

    if res.get("status") == "success":
        console.print(f"[green]Executed successfully.[/green]")
        result = res.get("result")
        if result:
            console.print(str(result)[:300])
    else:
        console.print(f"[red]Error: {res.get('error')}[/red]")


@agent.command("deny")
@click.argument("action_id")
def deny_cmd(action_id: str) -> None:
    """Deny a queued CONFIRM-tier action."""
    from jrvs.storage.database import Database
    db = Database()
    db.deny_action(action_id)
    console.print(f"[yellow]Action {action_id[:8]}… denied.[/yellow]")


# ─────────────────────────────────────────────────────────────────────────────
# pause / resume
# ─────────────────────────────────────────────────────────────────────────────

@agent.command("pause")
def pause_cmd() -> None:
    """Pause the agent (blocks all cron runs until resumed)."""
    from jrvs.agent.runner import pause_agent
    pause_agent()
    console.print("[yellow]Agent paused.[/yellow] Remove ~/JRVS/agent.pause or run "
                  "[bold]jrvs agent resume[/bold] to re-enable.")


@agent.command("resume")
def resume_cmd() -> None:
    """Resume the agent after a pause."""
    from jrvs.agent.runner import resume_agent
    resume_agent()
    console.print("[green]Agent resumed.[/green]")


# ─────────────────────────────────────────────────────────────────────────────
# logs
# ─────────────────────────────────────────────────────────────────────────────

@agent.command("logs")
@click.option("--run-id",  default=None, help="Filter by run ID prefix.")
@click.option("--limit",   "-n", default=20, show_default=True)
def logs_cmd(run_id: str | None, limit: int) -> None:
    """Show detailed action logs (optionally filtered by run ID)."""
    from jrvs.storage.database import Database
    db = Database()

    if run_id:
        rows = db.get_actions_for_run(run_id)
    else:
        rows = db.get_pending_actions(limit=limit) or []
        # fall back to fetching all recent
        if not rows:
            recent_runs = db.get_recent_runs(limit=3)
            rows = []
            for r in recent_runs:
                rows += db.get_actions_for_run(r["run_id"])

    if not rows:
        console.print("[dim]No action logs found.[/dim]")
        return

    tbl = Table(title="Action Log", box=box.SIMPLE_HEAD)
    tbl.add_column("Step",  style="dim", width=4)
    tbl.add_column("Tool",  style="bold", width=22)
    tbl.add_column("Tier",               width=8)
    tbl.add_column("Status",             width=12)
    tbl.add_column("Result / Error",     overflow="fold")

    for row in rows[:limit]:
        status = row.get("status", "")
        s_col  = {"success": "green", "error": "red",
                  "awaiting_approval": "yellow", "dry_run": "cyan",
                  "blocked": "dim"}.get(status, "white")
        result = (row.get("result_json") or "")[:80]
        tbl.add_row(
            str(row.get("step", "")),
            row.get("tool", ""),
            row.get("tier", ""),
            f"[{s_col}]{status}[/{s_col}]",
            result,
        )
    console.print(tbl)


# ─────────────────────────────────────────────────────────────────────────────
# goals
# ─────────────────────────────────────────────────────────────────────────────

@agent.command("goals")
def goals_cmd() -> None:
    """List all configured goals."""
    from jrvs.agent.goals import GoalLoader
    loader = GoalLoader()
    goals  = loader.all()

    if not goals:
        console.print("[dim]No goals found.[/dim]")
        return

    tbl = Table(title="Configured Goals", box=box.SIMPLE_HEAD)
    tbl.add_column("ID",       style="bold",  width=26)
    tbl.add_column("Tier",                    width=9)
    tbl.add_column("Schedules",               width=16)
    tbl.add_column("Enabled",                 width=7)
    tbl.add_column("Goal",                    overflow="fold")

    for g in goals:
        enabled  = g.get("enabled", True)
        e_colour = "green" if enabled else "dim"
        schedules = ", ".join(g.get("schedules", []))
        tier      = g.get("tier", "notify")
        t_colour  = {"auto": "green", "notify": "blue",
                     "confirm": "yellow", "blocked": "red"}.get(tier, "white")
        tbl.add_row(
            g.get("id", ""),
            f"[{t_colour}]{tier}[/{t_colour}]",
            schedules,
            f"[{e_colour}]{'yes' if enabled else 'no'}[/{e_colour}]",
            (g.get("goal") or "")[:80],
        )
    console.print(tbl)
