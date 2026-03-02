#!/usr/bin/env python3
"""
JARCORE CLI - Command-line interface for JARVIS Autonomous Reasoning & Coding Engine

Usage:
    jarcore generate "create a fibonacci function" --language python
    jarcore analyze myfile.py --type security
    jarcore fix myfile.py "NameError: name 'x' is not defined"
    jarcore explain myfile.py --detail medium
    jarcore test mycode.py
    jarcore run mycode.py
"""

import sys
import asyncio
import argparse
from pathlib import Path
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from mcp_gateway.coding_agent import jarcore
from rich.console import Console
from rich.syntax import Syntax
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


async def cmd_generate(args):
    """Generate code from description"""
    console.print(f"\n[bold cyan]JARCORE:[/bold cyan] Generating {args.language} code...")

    result = await jarcore.generate_code(
        task=args.task,
        language=args.language,
        context=args.context,
        include_tests=args.tests
    )

    if "error" in result:
        console.print(f"[bold red]Error:[/bold red] {result['error']}")
        return

    # Display code
    syntax = Syntax(result.get("code", ""), args.language, theme="monokai", line_numbers=True)
    console.print(Panel(syntax, title=f"[bold green]Generated Code[/bold green]"))

    # Display explanation
    if result.get("explanation"):
        console.print(f"\n[bold yellow]Explanation:[/bold yellow]")
        console.print(result["explanation"])

    # Display dependencies
    if result.get("dependencies"):
        console.print(f"\n[bold magenta]Dependencies:[/bold magenta] {', '.join(result['dependencies'])}")

    # Display tests
    if args.tests and result.get("tests"):
        test_syntax = Syntax(result["tests"], args.language, theme="monokai")
        console.print(Panel(test_syntax, title="[bold green]Tests[/bold green]"))

    # Save to file if requested
    if args.output:
        write_result = await jarcore.write_file(args.output, result["code"])
        if write_result.get("success"):
            console.print(f"\n[bold green]✓[/bold green] Saved to {args.output}")


async def cmd_analyze(args):
    """Analyze code file"""
    console.print(f"\n[bold cyan]JARCORE:[/bold cyan] Analyzing {args.file}...")

    # Read file
    file_result = await jarcore.read_file(args.file)
    if file_result.get("error"):
        console.print(f"[bold red]Error:[/bold red] {file_result['error']}")
        return

    # Analyze
    analysis = await jarcore.analyze_code(
        code=file_result["content"],
        language=file_result.get("language", args.language),
        analysis_type=args.type
    )

    if "error" in analysis:
        console.print(f"[bold red]Error:[/bold red] {analysis['error']}")
        return

    # Display issues
    issues = analysis.get("issues", [])
    if issues:
        console.print(f"\n[bold red]Found {len(issues)} issue(s):[/bold red]\n")
        for i, issue in enumerate(issues, 1):
            severity_color = {
                "critical": "red",
                "high": "orange1",
                "medium": "yellow",
                "low": "blue"
            }.get(issue.get("severity", "low"), "white")

            console.print(f"[bold {severity_color}]{i}. [{issue.get('severity', 'unknown').upper()}] Line {issue.get('line', '?')}[/bold {severity_color}]")
            console.print(f"   Type: {issue.get('type', 'unknown')}")
            console.print(f"   Issue: {issue.get('description', 'No description')}")
            console.print(f"   Fix: {issue.get('suggestion', 'No suggestion')}\n")
    else:
        console.print("[bold green]✓ No issues found![/bold green]")

    # Display metrics
    metrics = analysis.get("metrics", {})
    if metrics:
        console.print(f"\n[bold cyan]Metrics:[/bold cyan]")
        console.print(f"  Complexity: {metrics.get('complexity', 'N/A')}")
        console.print(f"  Maintainability: {metrics.get('maintainability', 'N/A')}/10")

    # Display suggestions
    suggestions = analysis.get("suggestions", [])
    if suggestions:
        console.print(f"\n[bold yellow]Suggestions:[/bold yellow]")
        for suggestion in suggestions:
            console.print(f"  • {suggestion}")


async def cmd_fix(args):
    """Fix code errors"""
    console.print(f"\n[bold cyan]JARCORE:[/bold cyan] Fixing {args.file}...")

    # Read file
    file_result = await jarcore.read_file(args.file)
    if file_result.get("error"):
        console.print(f"[bold red]Error:[/bold red] {file_result['error']}")
        return

    # Fix errors
    fixed = await jarcore.fix_code_errors(
        code=file_result["content"],
        error_message=args.error,
        language=file_result.get("language", args.language)
    )

    if "error" in fixed:
        console.print(f"[bold red]Error:[/bold red] {fixed['error']}")
        return

    # Display fixed code
    syntax = Syntax(fixed.get("fixed_code", ""), file_result.get("language", "python"), theme="monokai", line_numbers=True)
    console.print(Panel(syntax, title="[bold green]Fixed Code[/bold green]"))

    console.print(f"\n[bold yellow]Issue:[/bold yellow] {fixed.get('issue_identified', 'Unknown')}")
    console.print(f"[bold green]Fix:[/bold green] {fixed.get('fix_explanation', 'N/A')}")
    console.print(f"[bold cyan]Prevention:[/bold cyan] {fixed.get('prevention_tip', 'N/A')}")

    # Write back if confirmed
    if args.write:
        write_result = await jarcore.write_file(args.file, fixed["fixed_code"])
        if write_result.get("success"):
            console.print(f"\n[bold green]✓[/bold green] Updated {args.file}")


async def cmd_explain(args):
    """Explain code"""
    console.print(f"\n[bold cyan]JARCORE:[/bold cyan] Explaining {args.file}...")

    # Read file
    file_result = await jarcore.read_file(args.file)
    if file_result.get("error"):
        console.print(f"[bold red]Error:[/bold red] {file_result['error']}")
        return

    # Explain
    explanation = await jarcore.explain_code(
        code=file_result["content"],
        language=file_result.get("language", args.language),
        detail_level=args.detail
    )

    console.print(f"\n[bold green]Explanation:[/bold green]\n")
    console.print(Markdown(explanation))


async def cmd_test(args):
    """Generate tests for code"""
    console.print(f"\n[bold cyan]JARCORE:[/bold cyan] Generating tests for {args.file}...")

    # Read file
    file_result = await jarcore.read_file(args.file)
    if file_result.get("error"):
        console.print(f"[bold red]Error:[/bold red] {file_result['error']}")
        return

    # Generate tests
    tests = await jarcore.generate_tests(
        code=file_result["content"],
        language=file_result.get("language", args.language),
        test_framework=args.framework
    )

    if "error" in tests:
        console.print(f"[bold red]Error:[/bold red] {tests['error']}")
        return

    # Display test code
    syntax = Syntax(tests.get("test_code", ""), file_result.get("language", "python"), theme="monokai", line_numbers=True)
    console.print(Panel(syntax, title="[bold green]Test Code[/bold green]"))

    # Display test cases
    test_cases = tests.get("test_cases", [])
    if test_cases:
        console.print(f"\n[bold cyan]Test Cases ({len(test_cases)}):[/bold cyan]")
        for tc in test_cases:
            console.print(f"  • {tc.get('name', 'Unknown')} ({tc.get('type', 'unknown')})")
            console.print(f"    {tc.get('description', '')}")

    # Save if requested
    if args.output:
        write_result = await jarcore.write_file(args.output, tests["test_code"])
        if write_result.get("success"):
            console.print(f"\n[bold green]✓[/bold green] Saved tests to {args.output}")


async def cmd_run(args):
    """Execute code"""
    console.print(f"\n[bold cyan]JARCORE:[/bold cyan] Executing {args.file}...")

    # Read file
    file_result = await jarcore.read_file(args.file)
    if file_result.get("error"):
        console.print(f"[bold red]Error:[/bold red] {file_result['error']}")
        return

    # Execute
    result = await jarcore.execute_code(
        code=file_result["content"],
        language=file_result.get("language", args.language),
        timeout=args.timeout
    )

    if result.get("success"):
        console.print(f"[bold green]✓ Execution successful[/bold green] (exit code: {result.get('exit_code', 0)})")
        console.print(f"Duration: {result.get('duration_seconds', 0):.2f}s")
    else:
        console.print(f"[bold red]✗ Execution failed[/bold red]")
        if result.get("error"):
            console.print(f"Error: {result['error']}")

    # Display output
    if result.get("stdout"):
        console.print(f"\n[bold cyan]stdout:[/bold cyan]")
        console.print(result["stdout"])

    if result.get("stderr"):
        console.print(f"\n[bold red]stderr:[/bold red]")
        console.print(result["stderr"])


async def cmd_refactor(args):
    """Refactor code"""
    console.print(f"\n[bold cyan]JARCORE:[/bold cyan] Refactoring {args.file}...")

    # Read file
    file_result = await jarcore.read_file(args.file)
    if file_result.get("error"):
        console.print(f"[bold red]Error:[/bold red] {file_result['error']}")
        return

    # Refactor
    refactored = await jarcore.refactor_code(
        code=file_result["content"],
        language=file_result.get("language", args.language),
        refactor_goal=args.goal
    )

    if "error" in refactored:
        console.print(f"[bold red]Error:[/bold red] {refactored['error']}")
        return

    # Display refactored code
    syntax = Syntax(refactored.get("refactored_code", ""), file_result.get("language", "python"), theme="monokai", line_numbers=True)
    console.print(Panel(syntax, title="[bold green]Refactored Code[/bold green]"))

    # Display changes
    changes = refactored.get("changes", [])
    if changes:
        console.print(f"\n[bold cyan]Changes Made:[/bold cyan]")
        for change in changes:
            console.print(f"  • {change.get('description', 'Unknown change')}")
            console.print(f"    Reason: {change.get('reason', 'N/A')}")
            console.print(f"    Impact: {change.get('impact', 'N/A')}\n")

    # Write if confirmed
    if args.write:
        write_result = await jarcore.write_file(args.file, refactored["refactored_code"])
        if write_result.get("success"):
            console.print(f"[bold green]✓[/bold green] Updated {args.file}")


def main():
    parser = argparse.ArgumentParser(
        description="JARCORE - JARVIS Autonomous Reasoning & Coding Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  jarcore generate "create a REST API" --language python --output api.py
  jarcore analyze myfile.py --type security
  jarcore fix broken.py "NameError: undefined variable"
  jarcore test mycode.py --output test_mycode.py
  jarcore run script.py
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Generate
    gen_parser = subparsers.add_parser("generate", help="Generate code from description")
    gen_parser.add_argument("task", help="What the code should do")
    gen_parser.add_argument("--language", "-l", default="python", help="Programming language")
    gen_parser.add_argument("--context", "-c", help="Additional context")
    gen_parser.add_argument("--tests", "-t", action="store_true", help="Include tests")
    gen_parser.add_argument("--output", "-o", help="Output file")

    # Analyze
    analyze_parser = subparsers.add_parser("analyze", help="Analyze code")
    analyze_parser.add_argument("file", help="Code file to analyze")
    analyze_parser.add_argument("--type", default="comprehensive", choices=["comprehensive", "security", "performance", "style"])
    analyze_parser.add_argument("--language", "-l", default="python")

    # Fix
    fix_parser = subparsers.add_parser("fix", help="Fix code errors")
    fix_parser.add_argument("file", help="Code file with errors")
    fix_parser.add_argument("error", help="Error message")
    fix_parser.add_argument("--language", "-l", default="python")
    fix_parser.add_argument("--write", "-w", action="store_true", help="Write fixed code back to file")

    # Explain
    explain_parser = subparsers.add_parser("explain", help="Explain code")
    explain_parser.add_argument("file", help="Code file to explain")
    explain_parser.add_argument("--detail", "-d", default="medium", choices=["brief", "medium", "detailed"])
    explain_parser.add_argument("--language", "-l", default="python")

    # Test
    test_parser = subparsers.add_parser("test", help="Generate tests")
    test_parser.add_argument("file", help="Code file to test")
    test_parser.add_argument("--framework", "-f", help="Test framework")
    test_parser.add_argument("--language", "-l", default="python")
    test_parser.add_argument("--output", "-o", help="Output test file")

    # Run
    run_parser = subparsers.add_parser("run", help="Execute code")
    run_parser.add_argument("file", help="Code file to run")
    run_parser.add_argument("--language", "-l", default="python")
    run_parser.add_argument("--timeout", "-t", type=int, default=30, help="Timeout in seconds")

    # Refactor
    refactor_parser = subparsers.add_parser("refactor", help="Refactor code")
    refactor_parser.add_argument("file", help="Code file to refactor")
    refactor_parser.add_argument("--goal", "-g", default="improve readability and maintainability")
    refactor_parser.add_argument("--language", "-l", default="python")
    refactor_parser.add_argument("--write", "-w", action="store_true", help="Write refactored code back")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Route to command
    commands = {
        "generate": cmd_generate,
        "analyze": cmd_analyze,
        "fix": cmd_fix,
        "explain": cmd_explain,
        "test": cmd_test,
        "run": cmd_run,
        "refactor": cmd_refactor
    }

    if args.command in commands:
        asyncio.run(commands[args.command](args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
