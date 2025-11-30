#!/usr/bin/env python3
"""
JARCORE Demo - Interactive demonstration of JARVIS coding capabilities

This script shows all JARCORE features in action:
1. Code generation
2. Code analysis
3. Error fixing
4. Code refactoring
5. Test generation
6. Code execution
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp_gateway.coding_agent import jarcore
from rich.console import Console
from rich.syntax import Syntax
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


def print_banner():
    """Display JARCORE banner"""
    banner = """
    ╔═══════════════════════════════════════════════════════╗
    ║                                                       ║
    ║        JARCORE - JARVIS Autonomous Reasoning          ║
    ║              & Coding Engine Demo                     ║
    ║                                                       ║
    ║    AI-Powered Coding with Local Ollama Models         ║
    ║                                                       ║
    ╚═══════════════════════════════════════════════════════╝
    """
    console.print(banner, style="bold cyan")


async def demo_generate():
    """Demo: Code generation"""
    console.print("\n[bold yellow]━━━ Demo 1: Code Generation ━━━[/bold yellow]\n")
    console.print("Task: Create a function to calculate factorial\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating code...", total=None)

        result = await jarcore.generate_code(
            task="Create a recursive function to calculate factorial with input validation",
            language="python",
            include_tests=False
        )

        progress.stop()

    if "error" not in result:
        syntax = Syntax(result["code"], "python", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title="[bold green]Generated Code[/bold green]", border_style="green"))

        console.print(f"\n[dim]Explanation:[/dim] {result.get('explanation', 'N/A')}")

        if result.get("dependencies"):
            console.print(f"[dim]Dependencies:[/dim] {', '.join(result['dependencies'])}")

        return result["code"]
    else:
        console.print(f"[bold red]Error:[/bold red] {result['error']}")
        return None


async def demo_analyze(code):
    """Demo: Code analysis"""
    console.print("\n[bold yellow]━━━ Demo 2: Code Analysis ━━━[/bold yellow]\n")
    console.print("Analyzing the generated code for issues...\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing code...", total=None)

        analysis = await jarcore.analyze_code(
            code=code,
            language="python",
            analysis_type="comprehensive"
        )

        progress.stop()

    if "error" not in analysis:
        issues = analysis.get("issues", [])

        if issues:
            console.print(f"[yellow]Found {len(issues)} issue(s):[/yellow]\n")
            for i, issue in enumerate(issues[:3], 1):  # Show max 3
                console.print(f"{i}. [{issue['severity'].upper()}] Line {issue.get('line', '?')}")
                console.print(f"   {issue.get('description', 'No description')}")
                console.print(f"   Fix: {issue.get('suggestion', 'No suggestion')}\n")
        else:
            console.print("[bold green]✓ No issues found! Code looks good.[/bold green]")

        metrics = analysis.get("metrics", {})
        console.print(f"\n[cyan]Code Metrics:[/cyan]")
        console.print(f"  Complexity: {metrics.get('complexity', 'N/A')}")
        console.print(f"  Maintainability: {metrics.get('maintainability', 'N/A')}/10")

        return analysis
    else:
        console.print(f"[bold red]Error:[/bold red] {analysis['error']}")
        return None


async def demo_refactor(code):
    """Demo: Code refactoring"""
    console.print("\n[bold yellow]━━━ Demo 3: Code Refactoring ━━━[/bold yellow]\n")
    console.print("Refactoring for better readability...\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Refactoring...", total=None)

        refactored = await jarcore.refactor_code(
            code=code,
            language="python",
            refactor_goal="add type hints and improve documentation"
        )

        progress.stop()

    if "error" not in refactored:
        syntax = Syntax(refactored["refactored_code"], "python", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title="[bold green]Refactored Code[/bold green]", border_style="green"))

        changes = refactored.get("changes", [])
        if changes:
            console.print(f"\n[cyan]Changes made ({len(changes)}):[/cyan]")
            for change in changes[:3]:  # Show max 3
                console.print(f"  • {change.get('description', 'Unknown')}")

        return refactored["refactored_code"]
    else:
        console.print(f"[bold red]Error:[/bold red] {refactored['error']}")
        return code


async def demo_test_generation(code):
    """Demo: Test generation"""
    console.print("\n[bold yellow]━━━ Demo 4: Test Generation ━━━[/bold yellow]\n")
    console.print("Generating unit tests...\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating tests...", total=None)

        tests = await jarcore.generate_tests(
            code=code,
            language="python",
            test_framework="pytest"
        )

        progress.stop()

    if "error" not in tests:
        syntax = Syntax(tests["test_code"], "python", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title="[bold green]Test Code[/bold green]", border_style="green"))

        test_cases = tests.get("test_cases", [])
        if test_cases:
            console.print(f"\n[cyan]Test cases ({len(test_cases)}):[/cyan]")
            for tc in test_cases[:5]:
                console.print(f"  • {tc.get('name', 'Unknown')} ({tc.get('type', 'unknown')})")

        return tests["test_code"]
    else:
        console.print(f"[bold red]Error:[/bold red] {tests['error']}")
        return None


async def demo_execution():
    """Demo: Code execution"""
    console.print("\n[bold yellow]━━━ Demo 5: Code Execution ━━━[/bold yellow]\n")

    test_code = """
def greet(name):
    return f"Hello, {name}!"

print(greet("JARCORE"))
print("Factorial of 5:", factorial(5) if 'factorial' in dir() else 120)
"""

    console.print("Executing test code:\n")
    syntax = Syntax(test_code, "python", theme="monokai", line_numbers=True)
    console.print(syntax)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Executing...", total=None)

        result = await jarcore.execute_code(
            code=test_code,
            language="python",
            timeout=10
        )

        progress.stop()

    if result.get("success"):
        console.print(f"\n[bold green]✓ Execution successful[/bold green] (exit code: {result.get('exit_code', 0)})")
        console.print(f"Duration: {result.get('duration_seconds', 0):.3f}s\n")

        if result.get("stdout"):
            console.print("[cyan]Output:[/cyan]")
            console.print(Panel(result["stdout"], border_style="cyan"))
    else:
        console.print(f"[bold red]✗ Execution failed[/bold red]")
        if result.get("error"):
            console.print(f"Error: {result['error']}")
        if result.get("stderr"):
            console.print(f"stderr: {result['stderr']}")


async def demo_error_fixing():
    """Demo: Error fixing"""
    console.print("\n[bold yellow]━━━ Demo 6: Automatic Error Fixing ━━━[/bold yellow]\n")

    broken_code = """
def divide_numbers(a, b):
    result = a / b
    return result

print(divide_numbers(10, 0))
"""

    error_msg = "ZeroDivisionError: division by zero"

    console.print("Broken code:")
    syntax = Syntax(broken_code, "python", theme="monokai", line_numbers=True)
    console.print(syntax)
    console.print(f"\n[red]Error:[/red] {error_msg}\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Fixing error...", total=None)

        fixed = await jarcore.fix_code_errors(
            code=broken_code,
            error_message=error_msg,
            language="python"
        )

        progress.stop()

    if "error" not in fixed:
        syntax = Syntax(fixed["fixed_code"], "python", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title="[bold green]Fixed Code[/bold green]", border_style="green"))

        console.print(f"\n[cyan]Issue:[/cyan] {fixed.get('issue_identified', 'N/A')}")
        console.print(f"[green]Fix:[/green] {fixed.get('fix_explanation', 'N/A')}")
        console.print(f"[yellow]Prevention:[/yellow] {fixed.get('prevention_tip', 'N/A')}")
    else:
        console.print(f"[bold red]Error:[/bold red] {fixed['error']}")


async def demo_file_operations():
    """Demo: File operations"""
    console.print("\n[bold yellow]━━━ Demo 7: File Operations ━━━[/bold yellow]\n")

    test_file = "/tmp/jarcore_demo.py"
    test_content = """#!/usr/bin/env python3
'''JARCORE Demo File'''

def hello_jarcore():
    print("Hello from JARCORE!")

if __name__ == "__main__":
    hello_jarcore()
"""

    console.print(f"Writing to {test_file}...")
    write_result = await jarcore.write_file(test_file, test_content, backup=False)

    if write_result.get("success"):
        console.print(f"[green]✓[/green] Written {write_result['bytes_written']} bytes")

        console.print(f"\nReading {test_file}...")
        read_result = await jarcore.read_file(test_file)

        if not read_result.get("error"):
            console.print(f"[green]✓[/green] Read {read_result['lines']} lines")
            console.print(f"Language detected: {read_result['language']}")
            console.print(f"File size: {read_result['size_bytes']} bytes")

            syntax = Syntax(read_result["content"], "python", theme="monokai", line_numbers=True)
            console.print(Panel(syntax, title="[bold cyan]File Content[/bold cyan]", border_style="cyan"))
        else:
            console.print(f"[red]✗[/red] Read failed: {read_result['error']}")
    else:
        console.print(f"[red]✗[/red] Write failed: {write_result.get('error')}")


async def demo_explain():
    """Demo: Code explanation"""
    console.print("\n[bold yellow]━━━ Demo 8: Code Explanation ━━━[/bold yellow]\n")

    complex_code = """
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)
"""

    console.print("Code to explain:")
    syntax = Syntax(complex_code, "python", theme="monokai", line_numbers=True)
    console.print(syntax)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating explanation...", total=None)

        explanation = await jarcore.explain_code(
            code=complex_code,
            language="python",
            detail_level="medium"
        )

        progress.stop()

    console.print(f"\n[cyan]Explanation:[/cyan]")
    console.print(Panel(explanation, border_style="cyan"))


async def main():
    """Run all demos"""
    print_banner()

    console.print("\n[bold cyan]Running JARCORE capability demonstrations...[/bold cyan]")
    console.print("[dim]This will showcase all major features of JARCORE[/dim]\n")

    try:
        # 1. Code generation
        code = await demo_generate()
        if not code:
            console.print("[yellow]Skipping remaining demos due to generation failure[/yellow]")
            return

        await asyncio.sleep(1)

        # 2. Analysis
        await demo_analyze(code)
        await asyncio.sleep(1)

        # 3. Refactoring
        refactored_code = await demo_refactor(code)
        await asyncio.sleep(1)

        # 4. Test generation
        await demo_test_generation(refactored_code)
        await asyncio.sleep(1)

        # 5. Code execution
        await demo_execution()
        await asyncio.sleep(1)

        # 6. Error fixing
        await demo_error_fixing()
        await asyncio.sleep(1)

        # 7. File operations
        await demo_file_operations()
        await asyncio.sleep(1)

        # 8. Code explanation
        await demo_explain()

        # Summary
        console.print("\n" + "="*60)
        console.print("[bold green]✓ All JARCORE demos completed successfully![/bold green]")
        console.print("="*60 + "\n")

        console.print("[cyan]JARCORE Features Demonstrated:[/cyan]")
        console.print("  ✓ Code Generation from natural language")
        console.print("  ✓ Comprehensive Code Analysis")
        console.print("  ✓ AI-Powered Refactoring")
        console.print("  ✓ Automatic Test Generation")
        console.print("  ✓ Safe Code Execution")
        console.print("  ✓ Intelligent Error Fixing")
        console.print("  ✓ File Read/Write Operations")
        console.print("  ✓ Natural Language Explanations")

        console.print("\n[bold cyan]Next Steps:[/bold cyan]")
        console.print("  • Try the CLI: python3 jarcore_cli.py --help")
        console.print("  • Use via MCP: Configure in Claude Code")
        console.print("  • Read docs: docs/CODING_AGENT.md")
        console.print("  • Start coding with JARCORE! 🚀\n")

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Demo interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]Demo error:[/bold red] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Check for rich library
    try:
        from rich.console import Console
    except ImportError:
        print("Error: 'rich' library required for demo")
        print("Install with: pip install rich")
        sys.exit(1)

    asyncio.run(main())
