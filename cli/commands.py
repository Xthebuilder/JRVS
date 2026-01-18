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

            elif command == "month":
                # /month or /month 11 2025
                month = None
                year = None
                if len(command_args) >= 1:
                    month = int(command_args[0])
                if len(command_args) >= 2:
                    year = int(command_args[1])
                await self.cli.show_month_calendar(month, year)

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

            elif command == "mcp-servers":
                await self.cli.list_mcp_servers()

            elif command == "mcp-tools":
                server = command_args[0] if command_args else None
                await self.cli.list_mcp_tools(server)

            elif command == "mcp-call":
                if len(command_args) >= 3:
                    server = command_args[0]
                    tool = command_args[1]
                    args_json = " ".join(command_args[2:])
                    await self.cli.call_mcp_tool(server, tool, args_json)
                else:
                    theme.print_error("Usage: /mcp-call <server> <tool> <json_args>")
                    theme.print_info("Example: /mcp-call filesystem read_file '{\"path\": \"/tmp/test.txt\"}'")

            elif command == "report":
                self.cli.show_agent_report()

            elif command == "save-report":
                self.cli.save_agent_report()

            elif command == "mindmap":
                await self.handle_mindmap_command(command_args)

            elif command in ["exit", "quit", "bye"]:
                if theme.confirm("Are you sure you want to exit?"):
                    self.cli.running = False

            else:
                theme.print_error(f"Unknown command: /{command}")
                theme.print_info("Type '/help' for available commands")

        except Exception as e:
            theme.print_error(f"Command error: {e}")

    async def handle_mindmap_command(self, args: List[str]):
        """
        Mind map memory visualization commands
        
        Usage:
            /mindmap view          - Open web visualization
            /mindmap build         - Rebuild topic graph from history
            /mindmap topics        - List all topics
            /mindmap search <term> - Search topics
            /mindmap snapshot <name> - Save current state
            /mindmap insights      - Show AI insights
            /mindmap stats         - Show mind map statistics
        """
        import webbrowser
        import json
        from rich.table import Table
        from rich.console import Console
        
        console = Console()
        
        if not args:
            args = ['view']
        
        action = args[0].lower()
        
        try:
            # Import mind map modules
            from memory_map.database import mindmap_db
            from memory_map.topic_extractor import topic_extractor
            from memory_map.graph_builder import graph_builder
            from memory_map.analyzer import mindmap_analyzer
            
            if action == 'view':
                # Open web browser to visualization
                # Try to get Tailscale IP, fall back to localhost
                import subprocess
                try:
                    result = subprocess.run(['tailscale', 'ip', '-4'], capture_output=True, text=True, check=True)
                    host = result.stdout.strip()
                except:
                    host = 'localhost'
                url = f'http://{host}:8080/mindmap'
                webbrowser.open(url)
                theme.print_success(f"✓ Opening mind map at {url}...")
            
            elif action == 'build':
                theme.print_info("🔄 Building topic graph from conversation history...")
                
                # Initialize and extract topics
                result = await topic_extractor.batch_extract_from_history(limit=100)
                
                # Build graph relationships
                await graph_builder.initialize()
                topics = await mindmap_db.get_all_topics()
                if topics:
                    await graph_builder._calculate_topic_relationships(topics)
                
                theme.print_success(
                    f"✓ {result['message']}"
                )
            
            elif action == 'topics':
                await mindmap_db.initialize()
                topics = await mindmap_db.get_all_topics(limit=20)
                
                if not topics:
                    theme.print_warning("No topics found. Run '/mindmap build' first.")
                    return
                
                table = Table(title="Topics in Memory")
                table.add_column("ID", style="cyan", width=6)
                table.add_column("Topic", style="magenta", width=30)
                table.add_column("Category", style="yellow", width=15)
                table.add_column("Mentions", style="green", width=10)
                
                for topic in topics:
                    table.add_row(
                        str(topic['id']),
                        topic['topic_name'][:28] + '...' if len(topic['topic_name']) > 28 else topic['topic_name'],
                        topic['category'] or 'other',
                        str(topic['mention_count'])
                    )
                
                console.print(table)
            
            elif action == 'search' and len(args) > 1:
                search_term = ' '.join(args[1:])
                await mindmap_db.initialize()
                results = await mindmap_db.search_topics(search_term)
                
                console.print(f"\n🔍 Found {len(results)} topics matching '{search_term}':\n", style="bold")
                
                if results:
                    for topic in results:
                        console.print(
                            f"  • {topic['topic_name']} ({topic['category']}) - {topic['mention_count']} mentions"
                        )
                else:
                    theme.print_warning("No matching topics found.")
            
            elif action == 'snapshot' and len(args) > 1:
                snapshot_name = ' '.join(args[1:])
                
                await graph_builder.initialize()
                graph = await graph_builder.build_topic_graph()
                snapshot_id = await mindmap_db.save_mindmap_snapshot(
                    snapshot_name, 
                    json.dumps(graph)
                )
                
                theme.print_success(f"✓ Snapshot '{snapshot_name}' saved (ID: {snapshot_id})")
            
            elif action == 'insights':
                theme.print_info("🧠 Generating insights...")
                
                insights = await mindmap_analyzer.generate_insights()
                
                console.print("\n📊 Mind Map Insights:\n", style="bold cyan")
                
                for insight in insights:
                    icon = insight.get('icon', '📌')
                    desc = insight.get('description', '')
                    console.print(f"  {icon} {desc}")
                
                console.print()
            
            elif action == 'stats':
                await mindmap_db.initialize()
                stats = await mindmap_db.get_graph_statistics()
                
                console.print("\n📈 Mind Map Statistics:\n", style="bold cyan")
                console.print(f"  • Total Topics: {stats['total_topics']}")
                console.print(f"  • Total Connections: {stats['total_connections']}")
                console.print(f"  • Top Category: {stats['top_category']}")
                console.print(f"  • Avg Mentions/Topic: {stats['avg_mentions']}")
                console.print(f"  • Conversations Processed: {stats['conversations_processed']}")
                console.print()
            
            elif action == 'help':
                console.print("\n🧠 Mind Map Commands:\n", style="bold cyan")
                console.print("  /mindmap view           - Open web visualization")
                console.print("  /mindmap build          - Rebuild topic graph from history")
                console.print("  /mindmap topics         - List all extracted topics")
                console.print("  /mindmap search <term>  - Search for topics")
                console.print("  /mindmap snapshot <name> - Save current state")
                console.print("  /mindmap insights       - Show AI-generated insights")
                console.print("  /mindmap stats          - Show mind map statistics")
                console.print("  /mindmap help           - Show this help message")
                console.print()
            
            else:
                theme.print_error(f"Unknown mindmap action: {action}")
                theme.print_info("Use '/mindmap help' for available commands")
                
        except ImportError as e:
            theme.print_error(f"Mind map module not available: {e}")
            theme.print_info("Make sure the memory_map module is properly installed.")
        except Exception as e:
            theme.print_error(f"Mind map error: {e}")
