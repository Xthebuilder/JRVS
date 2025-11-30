"""Main CLI interface for Jarvis AI Agent"""
import asyncio
import uuid
from typing import Dict, List, Optional
import signal
import sys

from .themes import theme
from .commands import CommandHandler
from llm.ollama_client import ollama_client
from rag.retriever import rag_retriever
from scraper.web_scraper import web_scraper
from core.database import db
from core.calendar import calendar
from mcp_gateway.client import mcp_client
from mcp_gateway.agent import mcp_agent

class JarvisCLI:
    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.running = True
        self.command_handler = CommandHandler(self)
        self.conversation_history = []

    async def initialize(self):
        """Initialize all components"""
        theme.print_status("Initializing Jarvis AI Agent...", "info")

        try:
            # Initialize components
            await db.initialize()
            await calendar.initialize()
            await rag_retriever.initialize()

            # Initialize MCP client
            theme.print_status("Connecting to MCP servers...", "info")
            mcp_success = await mcp_client.initialize()
            if mcp_success:
                servers = await mcp_client.list_servers()
                if servers:
                    theme.print_success(f"Connected to {len(servers)} MCP server(s): {', '.join(servers)}")
                else:
                    theme.print_warning("No MCP servers connected (check mcp_gateway/client_config.json)")

            # Discover available models
            models = await ollama_client.discover_models()
            if not models:
                theme.print_error("No Ollama models found. Please install Ollama and pull some models.")
                return False

            theme.print_success(f"Found {len(models)} Ollama models")
            theme.print_success("Jarvis AI Agent initialized successfully!")

            return True

        except Exception as e:
            theme.print_error(f"Initialization failed: {e}")
            return False

    async def start(self):
        """Start the CLI interface"""
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Clear screen and show banner
        theme.clear_screen()
        theme.print_banner()
        
        # Initialize components
        if not await self.initialize():
            return
        
        theme.print_separator()
        theme.print_info("Type '/help' for available commands or start chatting!")
        theme.print_separator()
        
        # Main interaction loop
        while self.running:
            try:
                user_input = theme.print_prompt("jarvis")
                
                if not user_input.strip():
                    continue
                
                # Handle commands or chat
                if user_input.startswith('/'):
                    await self.command_handler.handle_command(user_input[1:])
                else:
                    await self.handle_chat_message(user_input)
                    
            except KeyboardInterrupt:
                if theme.confirm("Are you sure you want to exit?"):
                    break
            except Exception as e:
                theme.print_error(f"Unexpected error: {e}")
        
        await self.cleanup()

    async def handle_chat_message(self, message: str):
        """Handle regular chat messages with intelligent MCP tool usage"""
        try:
            # Check for natural language calendar requests
            if await self._try_parse_calendar_request(message):
                return

            # Show thinking indicator
            with theme.show_progress("Analyzing request...") as progress:
                task = progress.add_task("", total=None)

                # First, check if MCP tools should be used
                progress.update(task, description="Checking for tool needs...")
                agent_result = await mcp_agent.process_request(message)

                # If tools were used, show results
                if agent_result.get("tool_results"):
                    theme.print_status("🔧 Tools Used:", "info")
                    for tool_result in agent_result["tool_results"]:
                        status = "✓" if tool_result["success"] else "✗"
                        theme.console.print(
                            f"  {status} {tool_result['server']}/{tool_result['tool']}"
                        )

                # Get context from RAG
                progress.update(task, description="Gathering context...")
                context = await rag_retriever.retrieve_context(message, self.session_id)

                # Add tool results to context if available
                if agent_result.get("tool_results"):
                    tool_context = "\n\nTool Results:\n"
                    for tr in agent_result["tool_results"]:
                        if tr["success"] and tr.get("result"):
                            tool_context += f"- {tr['server']}/{tr['tool']}: {tr['result'][:200]}\n"
                    context = tool_context + "\n" + context

                progress.update(task, description="Generating response...")

                # Generate response with context injection
                response = await ollama_client.generate(
                    prompt=message,
                    context=context,
                    stream=False
                )

            if response:
                # Display response
                theme.print_response(response)

                # Store conversation with tool info
                tool_summary = agent_result.get("summary", "No tools used")
                await db.add_conversation(
                    session_id=self.session_id,
                    user_message=message,
                    ai_response=response,
                    model_used=ollama_client.current_model,
                    context_used=f"Tools: {tool_summary}\n{context[:500]}"
                )

                # Add to local history
                self.conversation_history.append({
                    'user': message,
                    'assistant': response,
                    'model': ollama_client.current_model,
                    'tools_used': agent_result.get("summary", "")
                })

            else:
                theme.print_error("Failed to generate response")

        except Exception as e:
            theme.print_error(f"Chat error: {e}")

    async def handle_streaming_response(self, message: str):
        """Handle streaming chat response"""
        try:
            # Get context
            context = await rag_retriever.retrieve_context(message, self.session_id)
            
            theme.print_status("Assistant:", "info")
            
            # Start streaming response
            response = ""
            async for chunk in self._generate_streaming(message, context):
                print(chunk, end='', flush=True)
                response += chunk
            
            print()  # New line after response
            
            # Store conversation
            if response:
                await db.add_conversation(
                    session_id=self.session_id,
                    user_message=message,
                    ai_response=response,
                    model_used=ollama_client.current_model,
                    context_used=context[:500] + "..." if len(context) > 500 else context
                )
                
        except Exception as e:
            theme.print_error(f"Streaming error: {e}")

    async def _generate_streaming(self, message: str, context: str):
        """Generate streaming response (placeholder for actual streaming)"""
        # This would integrate with the actual Ollama streaming API
        response = await ollama_client.generate(
            prompt=message,
            context=context,
            stream=False
        )
        
        if response:
            # Simulate streaming by yielding chunks
            for i in range(0, len(response), 10):
                yield response[i:i+10]
                await asyncio.sleep(0.05)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        if not hasattr(self, '_shutting_down'):
            self._shutting_down = True
            theme.print_warning("\nShutdown signal received...")
            self.running = False
            # Force exit if needed
            sys.exit(0)

    async def cleanup(self):
        """Clean up resources"""
        theme.print_status("Cleaning up...", "info")

        try:
            # Save MCP agent logs before cleanup
            if mcp_agent.session_log:
                log_file = mcp_agent.save_session_log(self.session_id)
                theme.print_info(f"Session log saved: {log_file}")

            await ollama_client.cleanup()
            await web_scraper.cleanup()
            await rag_retriever.cleanup()
            await mcp_client.cleanup()

            theme.print_success("Goodbye!")

        except Exception as e:
            theme.print_error(f"Cleanup error: {e}")

    # Utility methods for commands
    async def list_models(self):
        """List available models"""
        models = await ollama_client.list_models()
        if models:
            theme.print_model_info(models, ollama_client.current_model)
        else:
            theme.print_error("No models available")

    async def switch_model(self, model_name: str):
        """Switch to a different model"""
        if await ollama_client.switch_model(model_name):
            theme.print_success(f"Switched to model: {model_name}")
        else:
            theme.print_error(f"Failed to switch to model: {model_name}")

    async def scrape_url(self, url: str):
        """Scrape a URL and add to knowledge base"""
        with theme.show_progress(f"Scraping {url}...") as progress:
            task = progress.add_task("", total=None)
            
            doc_id = await web_scraper.scrape_and_store(url)
            
            if doc_id:
                theme.print_success(f"Successfully scraped and stored: {url}")
            else:
                theme.print_error(f"Failed to scrape: {url}")

    async def search_documents(self, query: str):
        """Search stored documents"""
        results = await rag_retriever.search_documents(query)
        
        if results:
            theme.print_status(f"Found {len(results)} results:", "info")
            
            for result in results:
                theme.print_info(f"• {result['title']} ({result.get('similarity', 0):.2f})")
                theme.console.print(f"  {result['preview']}")
                if result.get('url'):
                    theme.console.print(f"  URL: {result['url']}")
                theme.print_separator(length=30)
        else:
            theme.print_warning("No documents found")

    async def show_stats(self):
        """Show system statistics"""
        stats = await rag_retriever.get_stats()
        
        # Add current session info
        stats['session'] = {
            'session_id': self.session_id[:8] + "...",
            'conversations': len(self.conversation_history),
            'current_model': ollama_client.current_model
        }
        
        theme.print_stats(stats)

    def show_conversation_history(self, limit: int = 5):
        """Show recent conversation history"""
        if not self.conversation_history:
            theme.print_warning("No conversation history")
            return
        
        theme.print_status("Recent Conversations:", "info")
        
        for i, conv in enumerate(self.conversation_history[-limit:], 1):
            theme.console.print(f"\n[{theme.get_color('accent')}]#{i}[/]")
            theme.console.print(f"[{theme.get_color('primary')}]User:[/] {conv['user'][:100]}{'...' if len(conv['user']) > 100 else ''}")
            theme.console.print(f"[{theme.get_color('secondary')}]Assistant:[/] {conv['assistant'][:200]}{'...' if len(conv['assistant']) > 200 else ''}")
            theme.console.print(f"[dim]Model: {conv['model']}[/]")

    def set_theme(self, theme_name: str):
        """Set CLI theme"""
        theme.set_theme(theme_name)

    async def show_calendar(self):
        """Show upcoming events"""
        events = await calendar.get_upcoming_events(days=7)
        if events:
            theme.print_status("Upcoming Events (Next 7 Days):", "info")
            from datetime import datetime
            for event in events:
                event_dt = datetime.fromisoformat(event['event_date'])
                theme.console.print(f"[{theme.get_color('accent')}]#{event['id']}[/] {event['title']}")
                theme.console.print(f"  Date: {event_dt.strftime('%Y-%m-%d %H:%M')}")
                if event['description']:
                    theme.console.print(f"  {event['description']}")
                theme.print_separator(length=30)
        else:
            theme.print_warning("No upcoming events")

    async def show_month_calendar(self, month: int = None, year: int = None):
        """Show interactive ASCII calendar for a month"""
        from datetime import datetime

        # Default to current month
        now = datetime.now()
        if month is None:
            month = now.month
        if year is None:
            year = now.year

        # Get events for the month
        events_by_day = await calendar.get_month_events(year, month)

        # Render calendar
        cal_display = calendar.render_month_calendar(year, month, events_by_day)
        print(cal_display)

        # Show event details if any
        if events_by_day:
            theme.print_separator()
            theme.print_status("Events this month:", "info")
            for day in sorted(events_by_day.keys()):
                for event in events_by_day[day]:
                    event_dt = datetime.fromisoformat(event['event_date'])
                    status = "✓" if event['completed'] else "○"
                    theme.console.print(
                        f"{status} [{theme.get_color('accent')}]#{event['id']}[/] "
                        f"{event['title']} - {event_dt.strftime('%b %d at %I:%M %p')}"
                    )
                    if event['description']:
                        theme.console.print(f"    {event['description']}")
        else:
            theme.print_separator()
            theme.print_info("No events scheduled this month")

    async def show_today_events(self):
        """Show today's events"""
        events = await calendar.get_today_events()
        if events:
            theme.print_status("Today's Events:", "info")
            from datetime import datetime
            for event in events:
                event_dt = datetime.fromisoformat(event['event_date'])
                theme.console.print(f"[{theme.get_color('accent')}]#{event['id']}[/] {event['title']}")
                theme.console.print(f"  Time: {event_dt.strftime('%H:%M')}")
                if event['description']:
                    theme.console.print(f"  {event['description']}")
                theme.print_separator(length=30)
        else:
            theme.print_info("No events today")

    async def add_event(self, args: List[str]):
        """Add a calendar event"""
        try:
            from datetime import datetime
            # Parse: /event 2025-11-10 14:30 Team meeting
            date_str = args[0]
            time_str = args[1]
            title = " ".join(args[2:])

            event_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            event_id = await calendar.add_event(title, event_dt)
            theme.print_success(f"Event #{event_id} added: {title} on {event_dt.strftime('%Y-%m-%d %H:%M')}")
        except Exception as e:
            theme.print_error(f"Failed to add event: {e}")

    async def complete_event(self, event_id: int):
        """Mark event as completed"""
        try:
            await calendar.mark_completed(event_id)
            theme.print_success(f"Event #{event_id} marked as completed")
        except Exception as e:
            theme.print_error(f"Failed to complete event: {e}")

    async def list_mcp_servers(self):
        """List connected MCP servers"""
        servers = await mcp_client.list_servers()
        if servers:
            theme.print_status("Connected MCP Servers:", "info")
            for server in servers:
                tools = await mcp_client.list_server_tools(server)
                theme.console.print(f"  • {server} ({len(tools)} tools)")
        else:
            theme.print_warning("No MCP servers connected")
            theme.print_info("Configure servers in mcp_gateway/client_config.json")

    async def list_mcp_tools(self, server_name: str = None):
        """List MCP tools"""
        if server_name:
            tools = await mcp_client.list_server_tools(server_name)
            if tools:
                theme.print_status(f"Tools from '{server_name}':", "info")
                for tool in tools:
                    theme.console.print(f"  • {tool['name']}")
                    if tool.get('description'):
                        theme.console.print(f"    {tool['description']}")
            else:
                theme.print_error(f"Server '{server_name}' not found")
        else:
            all_tools = await mcp_client.list_all_tools()
            if all_tools:
                theme.print_status("Available MCP Tools:", "info")
                for server, tools in all_tools.items():
                    theme.console.print(f"\n[{theme.get_color('accent')}]{server}[/]:")
                    for tool in tools:
                        theme.console.print(f"  • {tool['name']}")
                        if tool.get('description'):
                            theme.console.print(f"    {tool['description']}")
            else:
                theme.print_warning("No MCP tools available")

    async def call_mcp_tool(self, server: str, tool: str, args_json: str):
        """Call an MCP tool"""
        try:
            import json
            arguments = json.loads(args_json)

            theme.print_status(f"Calling {server}/{tool}...", "info")
            result = await mcp_client.call_tool(server, tool, arguments)

            theme.print_success("Tool executed successfully!")
            theme.console.print(result)

        except Exception as e:
            theme.print_error(f"Failed to call tool: {e}")

    def show_agent_report(self):
        """Show MCP agent activity report"""
        report = mcp_agent.generate_report(self.session_id)
        print(report)

    def save_agent_report(self):
        """Save agent report to file"""
        try:
            log_file = mcp_agent.save_session_log(self.session_id)
            theme.print_success(f"Log saved: {log_file}")

            # Also save human-readable report
            report = mcp_agent.generate_report(self.session_id)
            report_file = log_file.parent / f"report_{log_file.stem}.txt"
            with open(report_file, 'w') as f:
                f.write(report)
            theme.print_success(f"Report saved: {report_file}")

        except Exception as e:
            theme.print_error(f"Failed to save report: {e}")

    async def _try_parse_calendar_request(self, message: str) -> bool:
        """Try to parse natural language calendar requests"""
        import re
        from datetime import datetime, timedelta

        msg_lower = message.lower()

        # Check for calendar-related keywords
        calendar_keywords = ['add', 'create', 'schedule', 'set', 'calendar', 'event', 'meeting', 'reminder', 'appointment']
        has_calendar_intent = any(word in msg_lower for word in calendar_keywords)

        if not has_calendar_intent:
            return False

        # Try to parse time: "at 10 am", "at 14:30", "at 3pm"
        time_match = re.search(r'(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', msg_lower)

        if not time_match:
            return False

        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        meridiem = time_match.group(3)

        # Convert to 24-hour format
        if meridiem == 'pm' and hour != 12:
            hour += 12
        elif meridiem == 'am' and hour == 12:
            hour = 0
        elif not meridiem and hour < 12 and hour >= 1:
            # If no meridiem specified and hour is small, assume AM unless it's clearly PM time
            pass

        # Determine date
        if 'tomorrow' in msg_lower:
            event_date = datetime.now() + timedelta(days=1)
        elif 'today' in msg_lower:
            event_date = datetime.now()
        else:
            # Try to parse specific date: "2025-11-15", "11/15", "nov 15"
            date_match = re.search(r'(\d{4}-\d{1,2}-\d{1,2})', msg_lower)
            if date_match:
                event_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
            else:
                # Default to tomorrow if no date specified
                event_date = datetime.now() + timedelta(days=1)

        # Set time
        event_date = event_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # Extract title - everything except calendar keywords and time/date info
        title = message
        # Remove common prefixes
        for prefix in ['add calendar event', 'add event', 'create event', 'schedule', 'add']:
            if msg_lower.startswith(prefix):
                title = title[len(prefix):].strip()
                break

        # Remove time part
        title = re.sub(r'(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)?', '', title, flags=re.IGNORECASE).strip()
        # Remove date parts
        title = re.sub(r'\b(?:tomorrow|today)\b', '', title, flags=re.IGNORECASE).strip()
        title = re.sub(r'\d{4}-\d{1,2}-\d{1,2}', '', title).strip()
        # Remove trailing words like "to jrvs"
        title = re.sub(r'\bto\s+jrvs\b', '', title, flags=re.IGNORECASE).strip()

        # Clean up title
        title = re.sub(r'\s+', ' ', title).strip(',. ')

        if not title or len(title) < 3:
            title = "Event"

        event_id = await calendar.add_event(title, event_date)
        theme.print_success(f"✓ Event #{event_id} added: {title}")
        theme.print_info(f"  📅 {event_date.strftime('%A, %B %d, %Y at %I:%M %p')}")
        return True

    def show_help(self):
        """Show help information"""
        commands = {
            "/help": "Show this help message",
            "/models": "List available Ollama models",
            "/switch <model>": "Switch to a different model",
            "/scrape <url>": "Scrape a website and add to knowledge base",
            "/search <query>": "Search stored documents",
            "/calendar": "Show upcoming events (7 days)",
            "/month [month] [year]": "Show ASCII calendar for month (default: current)",
            "/today": "Show today's events",
            "/event <date> <time> <title>": "Add calendar event",
            "/complete <id>": "Mark event as completed",
            "/mcp-servers": "List connected MCP servers",
            "/mcp-tools [server]": "List MCP tools (all or from specific server)",
            "/mcp-call <srv> <tool> <json>": "Call an MCP tool",
            "/report": "Show MCP agent activity report",
            "/save-report": "Save activity report to file",
            "/stats": "Show system statistics",
            "/history": "Show conversation history",
            "/theme <name>": "Change CLI theme (matrix, cyberpunk, minimal)",
            "/clear": "Clear the screen",
            "/exit": "Exit Jarvis"
        }

        theme.print_help(commands)
        theme.print_separator()
        theme.print_info("🤖 Intelligent Agent:")
        theme.console.print("  JRVS automatically detects when to use tools!")
        theme.console.print("  Just chat naturally - tools are used when needed")
        theme.console.print("  Example: 'read the file /tmp/test.txt'")
        theme.console.print("  Example: 'remember that I prefer Python 3.11'")
        theme.print_separator()
        theme.print_info("💡 Natural Language Calendar:")
        theme.console.print("  'add event study time tomorrow at 10 am'")
        theme.console.print("  'meeting with team today at 3pm'")
        theme.console.print("  'schedule dentist appointment 2025-11-20 at 2:30 pm'")
        theme.print_separator()
        theme.print_info("📅 Calendar View:")
        theme.console.print("  /month              - Current month calendar")
        theme.console.print("  /month 12           - December this year")
        theme.console.print("  /month 12 2025      - December 2025")
        theme.print_separator()
        theme.print_info("🔌 MCP Tools:")
        theme.console.print("  /mcp-servers        - List connected servers")
        theme.console.print("  /mcp-tools          - List all tools")
        theme.console.print("  /report             - View tool usage report")
        theme.console.print("  Configure: mcp_gateway/client_config.json")

# CLI instance
cli = JarvisCLI()