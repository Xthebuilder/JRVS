"""Main CLI interface for Jarvis AI Agent"""
import asyncio
import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional
import signal
import sys

from .themes import theme
from .commands import CommandHandler
from llm.ollama_client import ollama_client
from rag.retriever import rag_retriever
from scraper.web_scraper import web_scraper
from scraper.brave_search import brave_search
from core.database import db
from core.file_handler import file_handler, UPLOADS_DIR
from google_integration.client import google_workspace
from core.calendar import calendar
from mcp_gateway.client import mcp_client
from mcp_gateway.agent import mcp_agent
from config import CONVERSATION_HISTORY_TURNS
from mcp_gateway.coding_agent import jarcore

class JarvisCLI:
    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.running = True
        self.command_handler = CommandHandler(self)
        self.conversation_history = []
        # LLM client can be set to either ollama_client or lmstudio_client
        self.llm_client = ollama_client  # default
        self.llm_provider = "ollama"  # default
        self._system_prompt: str | None = None  # built dynamically after MCP init

    async def initialize(self):
        """Initialize all components"""
        theme.print_status("Initializing Jarvis AI Agent...", "info")

        try:
            # Initialize components
            await db.initialize()
            await calendar.initialize()
            await rag_retriever.initialize()

            # Ensure JRVS workspace folder exists before MCP filesystem server starts
            workspace = Path.home() / "jrvs-workspace"
            workspace.mkdir(exist_ok=True)
            (workspace / "README.txt").write_text(
                "This is your JRVS workspace.\n"
                "JRVS can read and write files here.\n"
                "Drop files here or ask JRVS to create them.\n"
            ) if not (workspace / "README.txt").exists() else None

            # Initialize MCP client
            theme.print_status("Connecting to MCP servers...", "info")
            mcp_success = await mcp_client.initialize()
            if mcp_success:
                servers = await mcp_client.list_servers()
                if servers:
                    theme.print_success(f"Connected to {len(servers)} MCP server(s): {', '.join(servers)}")
                else:
                    theme.print_warning("No MCP servers connected (check mcp_gateway/client_config.json)")

            # Build dynamic system prompt now that we know which tools are connected
            self._system_prompt = await self._build_system_prompt()

            # Propagate the configured LLM client to all dependent subsystems
            mcp_agent.set_llm_client(self.llm_client)
            jarcore.set_llm_client(self.llm_client)

            # Catch-up: embed any conversation turns that were missed by a previous crash
            asyncio.create_task(rag_retriever.embed_pending_conversations())

            # Discover available models using the configured LLM client
            models = await self.llm_client.discover_models()
            if not models:
                provider_name = "LM Studio" if self.llm_provider == "lmstudio" else "Ollama"
                theme.print_error(f"No {provider_name} models found. Please check your LLM provider setup.")
                return False

            provider_name = "LM Studio" if self.llm_provider == "lmstudio" else "Ollama"
            theme.print_success(f"Found {len(models)} {provider_name} models")
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
        
        # Main interaction loop — cleanup is guaranteed via finally
        try:
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
        finally:
            await self.cleanup()

    async def _build_system_prompt(self) -> str:
        """Build a system prompt that includes all connected MCP tools so the LLM
        knows what it can actually do."""
        from config import SYSTEM_PROMPT as BASE_PROMPT

        lines = [BASE_PROMPT]

        # Built-in capabilities always present
        lines.append(
            "\n\nYour capabilities:"
            "\n- Persistent memory: every conversation is stored in FAISS + SQLite and retrieved across sessions."
            "\n- RAG knowledge base: you can search documents and web pages that have been ingested."
            "\n- Web scraping: ingest any URL with /scrape."
            "\n- Brave web search: search the live web with /websearch or naturally in conversation."
            "\n- File uploads: read and ingest files from the uploads/ folder."
            "\n- Calendar: view and add events."
            "\n- Code generation and analysis via JARCORE."
        )

        # Read the actual filesystem allowed dirs straight from config
        fs_dirs: list[str] = []
        try:
            cfg_path = Path(__file__).parent.parent / "mcp_gateway" / "client_config.json"
            cfg = json.loads(cfg_path.read_text())
            fs_args = cfg.get("mcpServers", {}).get("filesystem", {}).get("args", [])
            # args format: ["-y", "@modelcontextprotocol/server-filesystem", dir1, dir2, ...]
            fs_dirs = [a for a in fs_args if a.startswith("/")]
        except Exception:
            pass

        if fs_dirs:
            lines.append(f"\n\nFilesystem access — you can read and write files in these directories: {', '.join(fs_dirs)}")
            lines.append(
                "\n~/jrvs-workspace is your personal workspace folder — use it to store files you create."
                "\nWhen asked 'what files can you see', list these exact directories. Never say you cannot access files."
            )

        # List all connected MCP servers and their tools
        all_tools = await mcp_client.list_all_tools()
        if all_tools:
            lines.append("\n\nConnected MCP tools (use these — never claim you lack tool access):")
            for server, tools in all_tools.items():
                tool_names = ", ".join(t["name"] for t in tools)
                lines.append(f"  • {server}: {tool_names}")
        else:
            lines.append("\n\nNo MCP servers are currently connected.")

        return "".join(lines)

    async def handle_chat_message(self, message: str):
        """Handle regular chat messages with intelligent MCP tool usage"""
        try:
            # Check for natural language calendar requests
            if await self._try_parse_calendar_request(message):
                return

            with theme.show_progress("Analyzing request...") as progress:
                task = progress.add_task("", total=None)

                # MCP tool check
                progress.update(task, description="Checking for tool needs...")
                agent_result = await mcp_agent.process_request(message)

                if agent_result.get("tool_results"):
                    theme.print_status("Tools Used:", "info")
                    for tool_result in agent_result["tool_results"]:
                        status = "+" if tool_result["success"] else "x"
                        theme.console.print(
                            f"  {status} {tool_result['server']}/{tool_result['tool']}"
                        )

                # RAG context — semantic search across all sessions + documents
                progress.update(task, description="Gathering memory & context...")
                context = await rag_retriever.retrieve_context(message, self.session_id)

                # Append MCP tool results into context and optionally persist them
                if agent_result.get("tool_results"):
                    tool_lines = []
                    for tr in agent_result["tool_results"]:
                        if tr["success"] and tr.get("result"):
                            result_text = str(tr["result"])
                            tool_lines.append(
                                f"Tool {tr['server']}/{tr['tool']}:\n{result_text[:3000]}"
                            )
                            # Persist substantial tool results to FAISS
                            if len(result_text) > 100:
                                asyncio.create_task(
                                    rag_retriever.add_document(
                                        content=result_text,
                                        title=f"MCP: {tr['server']}/{tr['tool']}",
                                        url="",
                                        metadata={
                                            "source": "mcp_tool",
                                            "server": tr["server"],
                                            "tool": tr["tool"],
                                            "query": message,
                                        },
                                    )
                                )
                    if tool_lines:
                        context = "Tool results:\n" + "\n\n".join(tool_lines) + "\n\n" + context

                progress.update(task, description="Generating response...")

                # Build recent in-session history to pass to the LLM for continuity
                recent_history = self.conversation_history[-CONVERSATION_HISTORY_TURNS:]

                response = await self.llm_client.generate(
                    prompt=message,
                    context=context,
                    stream=False,
                    conversation_history=recent_history,
                    system_prompt=self._system_prompt,
                )

            if response:
                theme.print_response(response)

                tool_summary = agent_result.get("summary", "No tools used")
                conv_id = await db.add_conversation(
                    session_id=self.session_id,
                    user_message=message,
                    ai_response=response,
                    model_used=self.llm_client.current_model,
                    context_used=f"Tools: {tool_summary}\n{context[:500]}"
                )

                # Embed this turn into FAISS asynchronously — JRVS learns from the conversation
                asyncio.create_task(
                    rag_retriever.embed_conversation(
                        user_message=message,
                        ai_response=response,
                        conversation_id=conv_id,
                        session_id=self.session_id,
                    )
                )

                self.conversation_history.append({
                    'user': message,
                    'assistant': response,
                    'model': self.llm_client.current_model,
                    'tools_used': agent_result.get("summary", "")
                })

            else:
                theme.print_error("Failed to generate response")

        except Exception as e:
            theme.print_error(f"Chat error: {e}")

    async def handle_streaming_response(self, message: str):
        """Handle streaming chat response"""
        try:
            context = await rag_retriever.retrieve_context(message, self.session_id)
            recent_history = self.conversation_history[-CONVERSATION_HISTORY_TURNS:]

            theme.print_status("Assistant:", "info")

            response = await self.llm_client.generate(
                prompt=message,
                context=context,
                stream=True,
                conversation_history=recent_history,
                system_prompt=self._system_prompt,
            )

            if response:
                conv_id = await db.add_conversation(
                    session_id=self.session_id,
                    user_message=message,
                    ai_response=response,
                    model_used=self.llm_client.current_model,
                    context_used=context[:500] + "..." if len(context) > 500 else context
                )
                asyncio.create_task(
                    rag_retriever.embed_conversation(
                        user_message=message,
                        ai_response=response,
                        conversation_id=conv_id,
                        session_id=self.session_id,
                    )
                )
                self.conversation_history.append({
                    'user': message,
                    'assistant': response,
                    'model': self.llm_client.current_model,
                    'tools_used': ''
                })

        except Exception as e:
            theme.print_error(f"Streaming error: {e}")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals — set running=False and let the event loop exit cleanly."""
        if not hasattr(self, '_shutting_down'):
            self._shutting_down = True
            theme.print_warning("\nShutdown signal received...")
            self.running = False
            # Raise KeyboardInterrupt to unblock any blocking prompt read
            raise KeyboardInterrupt

    async def cleanup(self):
        """Clean up resources"""
        theme.print_status("Cleaning up...", "info")

        try:
            # Save MCP agent logs before cleanup
            if mcp_agent.session_log:
                log_file = mcp_agent.save_session_log(self.session_id)
                theme.print_info(f"Session log saved: {log_file}")

            await self.llm_client.cleanup()
            await web_scraper.cleanup()
            await brave_search.cleanup()
            await rag_retriever.cleanup()
            await mcp_client.cleanup()
            await google_workspace.cleanup()

            theme.print_success("Goodbye!")

        except Exception as e:
            theme.print_error(f"Cleanup error: {e}")

    # Utility methods for commands
    async def list_models(self):
        """List available models"""
        models = await self.llm_client.list_models()
        if models:
            theme.print_model_info(models, self.llm_client.current_model)
        else:
            theme.print_error("No models available")

    async def switch_model(self, model_name: str):
        """Switch to a different model"""
        if await self.llm_client.switch_model(model_name):
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

    # ------------------------------------------------------------------
    # Upload commands
    # ------------------------------------------------------------------

    def upload_list(self):
        """List files in the uploads/ directory"""
        files = file_handler.list_files()
        if not files:
            theme.print_warning(f"No files in uploads/ — drop files into: {UPLOADS_DIR}")
            return

        theme.print_status(f"Files in uploads/ ({len(files)} total):", "info")
        for f in files:
            size_kb = f['size'] / 1024
            status = "" if f['supported'] else " [dim](unsupported type)[/dim]"
            theme.console.print(
                f"  • [bold]{f['name']}[/bold]  "
                f"[dim]{size_kb:.1f} KB  {f['extension']}[/dim]{status}"
            )
        theme.print_info(f"Path: {UPLOADS_DIR}")

    def upload_read(self, filename: str):
        """Display contents of a file from uploads/"""
        content = file_handler.read_file(filename)
        if content is None:
            theme.print_error(f"Cannot read '{filename}' — file not found or too large")
            return
        theme.print_status(f"Contents of {filename}:", "info")
        theme.console.print(content)

    async def upload_ingest(self, filename: str):
        """Embed a single upload file into the RAG knowledge base"""
        with theme.show_progress(f"Ingesting {filename}...") as progress:
            progress.add_task("", total=None)
            ok = await file_handler.ingest_file(filename, rag_retriever)
        if ok:
            theme.print_success(f"'{filename}' ingested into knowledge base")
        else:
            theme.print_error(
                f"Failed to ingest '{filename}' — check the file exists in {UPLOADS_DIR} "
                "and is a supported text-based format"
            )

    async def upload_ingest_all(self):
        """Embed all supported files in uploads/ into the RAG knowledge base"""
        files = file_handler.list_files()
        if not files:
            theme.print_warning(f"No files in {UPLOADS_DIR}")
            return

        with theme.show_progress("Ingesting all uploads...") as progress:
            progress.add_task("", total=None)
            results = await file_handler.ingest_all(rag_retriever)

        if results['success']:
            theme.print_success(f"Ingested: {', '.join(results['success'])}")
        if results['failed']:
            theme.print_error(f"Failed: {', '.join(results['failed'])}")
        if results['skipped']:
            theme.print_warning(f"Skipped (unsupported type): {', '.join(results['skipped'])}")
        if not results['success'] and not results['failed']:
            theme.print_warning("No files were ingested")

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
            'current_model': self.llm_client.current_model,
            'llm_provider': self.llm_provider
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

    # ------------------------------------------------------------------
    # JARCORE — coding assistant
    # ------------------------------------------------------------------

    async def jarcore_generate(self, language: str, task: str):
        """Generate code from a natural language description"""
        theme.print_status(f"Generating {language} code...", "info")
        with theme.show_progress("Generating code...") as progress:
            p = progress.add_task("", total=None)
            progress.update(p, description=f"Writing {language} code...")
            result = await jarcore.generate_code(task=task, language=language)

        if 'error' in result and 'code' not in result:
            theme.print_error(f"Code generation failed: {result['error']}")
            if result.get('raw_response'):
                theme.console.print(result['raw_response'])
            return

        if result.get('code'):
            theme.print_status("Generated code:", "info")
            theme.console.print(f"\n```{language}\n{result['code']}\n```\n")
        if result.get('explanation'):
            theme.print_info(f"How it works: {result['explanation']}")
        if result.get('dependencies'):
            theme.print_info(f"Dependencies: {', '.join(result['dependencies'])}")
        if result.get('usage_example'):
            theme.print_info(f"Usage: {result['usage_example']}")

    async def jarcore_analyze(self, filepath: str):
        """Analyze a code file for bugs, security, and style issues"""
        file_result = await jarcore.read_file(filepath)
        if file_result.get('error'):
            theme.print_error(file_result['error'])
            return

        theme.print_status(f"Analyzing {file_result['language']} file ({file_result['lines']} lines)...", "info")
        with theme.show_progress("Analyzing...") as progress:
            p = progress.add_task("", total=None)
            progress.update(p, description="Running code analysis...")
            result = await jarcore.analyze_code(file_result['content'], file_result['language'])

        if 'error' in result and 'issues' not in result:
            theme.print_error(f"Analysis failed: {result['error']}")
            return

        issues = result.get('issues', [])
        if issues:
            theme.print_status(f"Found {len(issues)} issue(s):", "info")
            for issue in issues:
                severity = issue.get('severity', 'unknown').upper()
                theme.console.print(
                    f"  [{severity}] Line {issue.get('line', '?')}: "
                    f"{issue.get('description', '')} — {issue.get('suggestion', '')}"
                )
        else:
            theme.print_success("No issues found.")

        if result.get('suggestions'):
            theme.print_info("Suggestions: " + "; ".join(result['suggestions']))

    async def jarcore_explain(self, filepath: str):
        """Explain what a code file does in plain language"""
        file_result = await jarcore.read_file(filepath)
        if file_result.get('error'):
            theme.print_error(file_result['error'])
            return

        theme.print_status(f"Explaining {file_result['language']} file...", "info")
        with theme.show_progress("Explaining...") as progress:
            p = progress.add_task("", total=None)
            progress.update(p, description="Reading code...")
            result = await jarcore.explain_code(file_result['content'], file_result['language'])

        theme.print_response(result)

    async def jarcore_run(self, filepath: str):
        """Execute a code file and show stdout/stderr"""
        file_result = await jarcore.read_file(filepath)
        if file_result.get('error'):
            theme.print_error(file_result['error'])
            return

        theme.print_status(f"Running {file_result['language']} file...", "info")
        with theme.show_progress("Executing...") as progress:
            p = progress.add_task("", total=None)
            progress.update(p, description="Running code...")
            result = await jarcore.execute_code(
                file_result['content'], file_result['language']
            )

        if result.get('success'):
            theme.print_success(f"Exited 0 in {result.get('duration_seconds', 0):.2f}s")
        else:
            theme.print_error(f"Exit code {result.get('exit_code', '?')}: {result.get('error', '')}")

        if result.get('stdout'):
            theme.print_status("stdout:", "info")
            theme.console.print(result['stdout'])
        if result.get('stderr'):
            theme.print_status("stderr:", "info")
            theme.console.print(result['stderr'])

    async def jarcore_fix(self, filepath: str, error_message: str):
        """Fix a code file based on an error message"""
        file_result = await jarcore.read_file(filepath)
        if file_result.get('error'):
            theme.print_error(file_result['error'])
            return

        theme.print_status("Diagnosing and fixing error...", "info")
        with theme.show_progress("Fixing...") as progress:
            p = progress.add_task("", total=None)
            progress.update(p, description="Analyzing error...")
            result = await jarcore.fix_code_errors(
                file_result['content'], error_message, file_result['language']
            )

        if 'error' in result and 'fixed_code' not in result:
            theme.print_error(f"Fix failed: {result['error']}")
            return

        theme.print_status(f"Issue identified: {result.get('issue_identified', '')}", "info")
        theme.print_info(f"Fix: {result.get('fix_explanation', '')}")
        if result.get('prevention_tip'):
            theme.print_info(f"Prevention: {result['prevention_tip']}")
        if result.get('fixed_code'):
            theme.print_status("Fixed code:", "info")
            theme.console.print(f"\n```{file_result['language']}\n{result['fixed_code']}\n```\n")

    async def websearch(self, query: str):
        """Search the web via Brave API and ingest results into FAISS"""
        if not brave_search.is_configured:
            theme.print_error("Brave API key not set. Run: /brave-key <your_key>")
            return

        remaining = brave_search.requests_remaining
        if remaining == 0:
            theme.print_error(
                f"Brave request budget exhausted ({brave_search.max_requests} max). "
                "Use /brave-status to check or /brave-reset to reset."
            )
            return

        theme.print_status(
            f"Searching Brave for: '{query}' ({remaining} requests remaining)...", "info"
        )

        with theme.show_progress("Searching and ingesting...") as progress:
            task = progress.add_task("", total=None)
            progress.update(task, description="Querying Brave Search API...")
            summary = await brave_search.search_and_ingest(query)

        theme.print_success(
            f"Done — {summary['results_found']} results found, "
            f"{summary['pages_ingested']} pages ingested into knowledge base."
        )
        theme.print_info(
            f"Requests used this session: {summary['requests_used']} / "
            f"{brave_search.max_requests}"
        )

    def set_brave_key(self, key: str):
        """Set the Brave Search API key at runtime"""
        brave_search.set_api_key(key)
        theme.print_success("Brave Search API key updated.")
        theme.print_info("Use /brave-status to confirm settings.")

    def show_brave_status(self):
        """Show Brave Search configuration and usage"""
        status = brave_search.get_status()
        theme.print_status("Brave Search Status:", "info")
        theme.console.print(f"  Configured  : {'Yes' if status['configured'] else 'No (use /brave-key)'}")
        theme.console.print(f"  Max requests: {status['max_requests']} per session")
        theme.console.print(f"  Used        : {status['requests_used']}")
        theme.console.print(f"  Remaining   : {status['requests_remaining']}")
        theme.console.print(f"  Per query   : {status['results_per_query']} results")
        theme.console.print(f"  Auto-scrape : {status['auto_scrape']}")

    # ------------------------------------------------------------------
    # Google Workspace commands
    # ------------------------------------------------------------------

    async def google_auth(self):
        """Interactive OAuth2 flow: print URL, prompt for code, exchange token."""
        if not google_workspace.auth.is_configured():
            theme.print_error(
                "Google credentials not configured. "
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file."
            )
            return
        try:
            url = google_workspace.auth.get_auth_url()
        except Exception as exc:
            theme.print_error(f"Failed to build auth URL: {exc}")
            return

        theme.print_status("Google OAuth2 Authorization", "info")
        theme.console.print("\nVisit this URL in your browser:")
        theme.console.print(f"\n  [bright_cyan]{url}[/]\n")
        theme.console.print("After authorizing, paste the code shown on the page:")
        try:
            code = input("  Authorization code: ").strip()
        except (EOFError, KeyboardInterrupt):
            theme.print_warning("Auth cancelled.")
            return
        if not code:
            theme.print_error("No code entered.")
            return
        try:
            google_workspace.auth.exchange_code(code)
            theme.print_success("Authenticated successfully with Google!")
            theme.print_info("Starting background sync... (use /google-status to check)")
            await google_workspace.start_background_sync()
        except Exception as exc:
            theme.print_error(f"Authentication failed: {exc}")

    def google_status(self):
        """Show Google Workspace connection status and sync statistics."""
        status = google_workspace.get_status()
        theme.print_status("Google Workspace Status:", "info")
        theme.console.print(f"  Configured        : {'Yes' if status['configured'] else 'No (set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET)'}")
        theme.console.print(f"  Authenticated     : {'Yes' if status['authenticated'] else 'No (run /google-auth)'}")
        theme.console.print(f"  Background sync   : {'Running' if status['sync_running'] else 'Paused'}")
        theme.console.print(f"  Sync interval     : {status['sync_interval_minutes']} min")
        theme.console.print(f"  Last Gmail sync   : {status['last_sync_gmail'] or 'Never'}")
        theme.console.print(f"  Last Drive sync   : {status['last_sync_drive'] or 'Never'}")
        theme.console.print(f"  Emails ingested   : {status['total_emails_ingested']}")
        theme.console.print(f"  Docs ingested     : {status['total_docs_ingested']}")

    async def google_sync(self):
        """Manually trigger a Google Workspace sync."""
        if not google_workspace.auth.is_authenticated():
            theme.print_error("Not authenticated. Run /google-auth first.")
            return
        theme.print_status("Syncing Google Workspace...", "info")
        with theme.show_progress("Syncing...") as progress:
            task = progress.add_task("", total=None)
            progress.update(task, description="Fetching emails and docs...")
            summary = await google_workspace.sync_now()
        if "error" in summary:
            theme.print_error(f"Sync failed: {summary['error']}")
        else:
            theme.print_success(
                f"Sync complete — {summary['emails_ingested']} emails, "
                f"{summary['docs_ingested']} docs ingested."
            )

    async def google_pause(self):
        """Stop the background Google sync loop."""
        await google_workspace.stop_background_sync()
        theme.print_success("Google Workspace background sync paused.")

    async def google_resume(self):
        """Restart the background Google sync loop."""
        if not google_workspace.auth.is_authenticated():
            theme.print_error("Not authenticated. Run /google-auth first.")
            return
        await google_workspace.start_background_sync()
        theme.print_success("Google Workspace background sync resumed.")

    async def gmail_search(self, query: str):
        """Search Gmail and ingest matches into FAISS."""
        if not google_workspace.auth.is_authenticated():
            theme.print_error("Not authenticated. Run /google-auth first.")
            return
        import asyncio
        from rag.retriever import rag_retriever
        from core.database import db as _db
        theme.print_status(f"Searching Gmail for: '{query}'...", "info")
        with theme.show_progress("Searching...") as progress:
            task = progress.add_task("", total=None)
            progress.update(task, description="Querying Gmail API...")
            messages = await asyncio.to_thread(
                google_workspace.gmail.list_messages,
                query=query,
                max_results=20,
            )
        if not messages:
            theme.print_warning("No emails found.")
            return
        ingested = 0
        for msg in messages:
            url = f"gmail:{msg['id']}"
            if await _db.check_document_exists(url):
                continue
            content = google_workspace.gmail.format_for_ingestion(msg)
            if content.strip():
                await rag_retriever.add_document(
                    content=content,
                    title=msg["subject"],
                    url=url,
                    metadata={"source": "gmail", "from": msg["from_"], "date": msg["date"]},
                )
                ingested += 1
        theme.print_success(
            f"Found {len(messages)} email(s), ingested {ingested} new into knowledge base."
        )

    async def gmail_send(self, to: str, subject: str, body: str):
        """Send an email via Gmail (write-logged to audit)."""
        if not google_workspace.auth.is_authenticated():
            theme.print_error("Not authenticated. Run /google-auth first.")
            return
        theme.print_status(f"Sending email to {to}...", "info")
        try:
            result = await google_workspace.send_email(to, subject, body)
            theme.print_success(f"Email sent! Message ID: {result.get('id', 'unknown')}")
            theme.print_info("Action logged to data/logs/google_audit.log")
        except Exception as exc:
            theme.print_error(f"Failed to send email: {exc}")

    async def gdocs_read(self, title_or_id: str):
        """Find a Google Doc by title or ID, ingest into FAISS, and show preview."""
        if not google_workspace.auth.is_authenticated():
            theme.print_error("Not authenticated. Run /google-auth first.")
            return
        import asyncio
        from rag.retriever import rag_retriever
        from core.database import db as _db

        theme.print_status(f"Reading Google Doc: {title_or_id}...", "info")
        with theme.show_progress("Fetching doc...") as progress:
            task = progress.add_task("", total=None)
            progress.update(task, description="Fetching from Google Docs...")

            # Try as ID first, then title search
            doc_id = title_or_id
            if not title_or_id.startswith("1") or " " in title_or_id:
                found_id = await asyncio.to_thread(google_workspace.docs.find_by_title, title_or_id)
                if found_id:
                    doc_id = found_id
                else:
                    theme.print_error(f"No Google Doc found with title '{title_or_id}'.")
                    return
            try:
                doc = await asyncio.to_thread(google_workspace.docs.get_document, doc_id)
            except Exception as exc:
                theme.print_error(f"Failed to fetch doc: {exc}")
                return

        url = f"gdrive:{doc_id}"
        exists = await _db.check_document_exists(url)
        if not exists:
            await rag_retriever.add_document(
                content=doc["content"],
                title=doc["title"],
                url=url,
                metadata={"source": "gdocs", "revision": doc["revision_id"]},
            )
            theme.print_success(f"Ingested '{doc['title']}' into knowledge base.")
        else:
            theme.print_info(f"'{doc['title']}' already in knowledge base (skipped re-ingestion).")
        preview = doc["content"][:300].replace("\n", " ")
        theme.console.print(f"\nPreview: {preview}...")

    async def gdocs_create(self, title: str, content: str):
        """Create a Google Doc (write-logged to audit)."""
        if not google_workspace.auth.is_authenticated():
            theme.print_error("Not authenticated. Run /google-auth first.")
            return
        theme.print_status(f"Creating Google Doc: '{title}'...", "info")
        try:
            result = await google_workspace.create_doc(title, content)
            theme.print_success(f"Google Doc created: {result['url']}")
            theme.print_info("Action logged to data/logs/google_audit.log")
        except Exception as exc:
            theme.print_error(f"Failed to create doc: {exc}")

    async def gsheets_read(self, title_or_id: str, range_: str = "A1:Z1000"):
        """Read a Google Sheet range and ingest as structured text into FAISS."""
        if not google_workspace.auth.is_authenticated():
            theme.print_error("Not authenticated. Run /google-auth first.")
            return
        import asyncio
        from rag.retriever import rag_retriever
        from core.database import db as _db

        theme.print_status(f"Reading Google Sheet: {title_or_id} range {range_}...", "info")
        with theme.show_progress("Fetching sheet...") as progress:
            task = progress.add_task("", total=None)
            progress.update(task, description="Querying Sheets API...")

            sheet_id = title_or_id
            if " " in title_or_id:
                found_id = await asyncio.to_thread(google_workspace.sheets.find_by_title, title_or_id)
                if found_id:
                    sheet_id = found_id
                else:
                    theme.print_error(f"No Google Sheet found with title '{title_or_id}'.")
                    return
            try:
                data = await asyncio.to_thread(google_workspace.sheets.get_values, sheet_id, range_)
            except Exception as exc:
                theme.print_error(f"Failed to read sheet: {exc}")
                return

        content = google_workspace.sheets.format_for_ingestion(data)
        url = f"gsheets:{sheet_id}:{range_}"
        exists = await _db.check_document_exists(url)
        if not exists:
            await rag_retriever.add_document(
                content=content,
                title=f"Sheet {sheet_id} ({range_})",
                url=url,
                metadata={"source": "gsheets", "range": range_},
            )
            theme.print_success("Sheet data ingested into knowledge base.")
        else:
            theme.print_info("Sheet range already ingested (skipped re-ingestion).")
        rows = len(data["values"])
        theme.console.print(f"Rows read: {rows}  Range: {data['range']}")
        if data["values"]:
            theme.console.print(f"First row: {data['values'][0]}")

    async def gsheets_update(self, title_or_id: str, range_: str, value: str):
        """Update a Google Sheet range (write-logged to audit)."""
        if not google_workspace.auth.is_authenticated():
            theme.print_error("Not authenticated. Run /google-auth first.")
            return
        import asyncio

        sheet_id = title_or_id
        if " " in title_or_id:
            found_id = await asyncio.to_thread(google_workspace.sheets.find_by_title, title_or_id)
            if found_id:
                sheet_id = found_id
            else:
                theme.print_error(f"No Google Sheet found with title '{title_or_id}'.")
                return

        # Parse value: support comma-separated for a single row
        row_values = [v.strip() for v in value.split(",")]
        values = [row_values]

        theme.print_status(f"Updating {sheet_id} range {range_}...", "info")
        try:
            result = await google_workspace.update_sheet(sheet_id, range_, values)
            updated = result.get("updatedCells", 0)
            theme.print_success(f"Updated {updated} cell(s). Action logged to google_audit.log")
        except Exception as exc:
            theme.print_error(f"Failed to update sheet: {exc}")

    async def _try_parse_calendar_request(self, message: str) -> bool:
        """Try to parse natural language calendar requests using the shared parser."""
        from core.calendar_parser import parse_calendar_request

        parsed = parse_calendar_request(message)
        if parsed is None:
            return False

        event_id = await calendar.add_event(parsed["title"], parsed["event_date"])
        theme.print_success(f"Event #{event_id} added: {parsed['title']}")
        theme.print_info(f"  {parsed['event_date'].strftime('%A, %B %d, %Y at %I:%M %p')}")
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
            "/code generate <lang> <task>": "Generate code from description",
            "/code analyze <file>": "Analyze code file for issues",
            "/code explain <file>": "Explain what a code file does",
            "/code run <file>": "Execute a code file",
            "/code fix <file> <error>": "Fix code based on error message",
            "/upload list": "List files in the uploads/ folder",
            "/upload read <file>": "Display a file's contents",
            "/upload ingest <file>": "Embed a file from uploads/ into the knowledge base",
            "/upload ingest-all": "Embed every supported file in uploads/",
            "/websearch <query>": "Search web via Brave API and ingest into knowledge base",
            "/brave-key <key>": "Set your Brave Search API key",
            "/brave-status": "Show Brave Search config and request usage",
            "/google-auth": "Authenticate with Google (OAuth2)",
            "/google-status": "Show Google Workspace status and sync stats",
            "/google-sync": "Manually sync Gmail + Drive into knowledge base",
            "/google-pause": "Pause background Google sync",
            "/google-resume": "Resume background Google sync",
            "/gmail search <query>": "Search Gmail and ingest results",
            "/gmail send <to> <subj> <body>": "Send email (audit-logged)",
            "/gdocs read <title|id>": "Ingest a Google Doc into knowledge base",
            "/gdocs create <title> <content>": "Create a Google Doc (audit-logged)",
            "/gsheets read <title|id> [range]": "Read and ingest a Google Sheet",
            "/gsheets update <id> <range> <val>": "Update Sheet cell(s) (audit-logged)",
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