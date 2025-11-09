"""Command handler for CLI interface"""
import shlex
from typing import List, Optional
from .themes import theme

class CommandHandler:
    def __init__(self, cli_instance):
        self.cli = cli_instance

    async def handle_command(self, command_line: str):
        """Parse and handle CLI commands"""
        try:
            args = shlex.split(command_line)
            if not args:
                return

            command = args[0].lower()
            command_args = args[1:] if len(args) > 1 else []

            # Route commands
            if command == "help":
                self.cli.show_help()
                
            elif command == "models":
                await self.cli.list_models()

            elif command == "model":
                if command_args:
                    await self.cli.switch_model(command_args[0])
                else:
                    await self.cli.list_models()

            elif command == "switch":
                if command_args:
                    await self.cli.switch_model(command_args[0])
                else:
                    theme.print_error("Usage: /switch <model_name>")
                    
            elif command == "scrape":
                if command_args:
                    await self.cli.scrape_url(command_args[0])
                else:
                    theme.print_error("Usage: /scrape <url>")
                    
            elif command == "search":
                if command_args:
                    query = " ".join(command_args)
                    await self.cli.search_documents(query)
                else:
                    theme.print_error("Usage: /search <query>")
                    
            elif command == "stats":
                await self.cli.show_stats()
                
            elif command == "history":
                limit = 5
                if command_args and command_args[0].isdigit():
                    limit = int(command_args[0])
                self.cli.show_conversation_history(limit)
                
            elif command == "theme":
                if command_args:
                    self.cli.set_theme(command_args[0])
                else:
                    theme.print_error("Usage: /theme <theme_name>")
                    theme.print_info("Available themes: matrix, cyberpunk, minimal")
                    
            elif command == "clear":
                theme.clear_screen()
                theme.print_banner()
                
            elif command == "calendar":
                await self.cli.show_calendar()

            elif command == "event":
                if len(command_args) >= 2:
                    await self.cli.add_event(command_args)
                else:
                    theme.print_error("Usage: /event <date> <time> <title>")
                    theme.print_info("Example: /event 2025-11-10 14:30 Team meeting")

            elif command == "today":
                await self.cli.show_today_events()

            elif command == "complete":
                if command_args and command_args[0].isdigit():
                    await self.cli.complete_event(int(command_args[0]))
                else:
                    theme.print_error("Usage: /complete <event_id>")

            elif command in ["exit", "quit", "bye"]:
                if theme.confirm("Are you sure you want to exit?"):
                    self.cli.running = False

            else:
                theme.print_error(f"Unknown command: /{command}")
                theme.print_info("Type '/help' for available commands")

        except Exception as e:
            theme.print_error(f"Command error: {e}")