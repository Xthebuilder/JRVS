#!/usr/bin/env python3
"""
CORTANA_JRVS v2.0 - Modular Enterprise AI Assistant
Entry point that imports from cortana/ module

Usage:
    python cortana_jrvs_v2.py
"""

import asyncio
import sys
from pathlib import Path

# Add JRVS to path
jrvs_path = Path(__file__).parent
sys.path.insert(0, str(jrvs_path))

# Validate Python version
if sys.version_info < (3, 8):
    print("Error: Python 3.8+ required")
    sys.exit(1)

try:
    from cortana import CortanaJRVS, validate_config, CONFIG
    from rich.console import Console
   
    console = Console()
    
    async def main():
        """Main entry point"""
        
        # Validate configuration
        valid, errors = validate_config(CONFIG)
        if not valid:
            console.print("[red]Configuration errors:[/]")
            for error in errors:
                console.print(f"  - {error}")
            sys.exit(1)
        
        # Create and run assistant
        assistant = CortanaJRVS()
        await assistant.run()
    
    if __name__ == "__main__":
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user[/]")
            sys.exit(0)
        except Exception as e:
            console.print(f"[red]Fatal error: {e}[/]")
            import traceback
            traceback.print_exc()
            sys.exit(1)

except ImportError as e:
    print(f"Import error: {e}")
    print("\nThe cortana module is not fully implemented yet.")
    print("This is a placeholder entry point for the modular version.")
    sys.exit(1)
