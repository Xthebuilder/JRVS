"""Main CLI interface for Jarvis AI Agent"""
import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional
import signal
import sys

logger = logging.getLogger(__name__)

from .themes import theme
from .commands import CommandHandler
from llm.ollama_client import ollama_client
from rag.retriever import rag_retriever
from scraper.web_scraper import web_scraper
from scraper.brave_search import brave_search
from core.database import db
from core.file_handler import file_handler, UPLOADS_DIR
from core.session_store import session_store
from google_integration.client import google_workspace
from core.calendar import calendar
from mcp_gateway.client import mcp_client
from mcp_gateway.agent import mcp_agent
from mcp_gateway.coding_agent import jarcore
from core.goal_scheduler import goal_scheduler
from core.cron_scheduler import cron_scheduler
from extensions.vision.vision_module import VisionModule
from extensions.audio.ambient_listener import AmbientListener
from core.security import vibe_checker, SecurityException

class JarvisCLI:
    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.running = True
        self.command_handler = CommandHandler(self)
        # LLM client can be set to either ollama_client or lmstudio_client
        self.llm_client = ollama_client  # default
        self.llm_provider = "ollama"  # default
        self._system_prompt: str | None = None  # built dynamically after MCP init
        self._last_sources: list = []  # sources from most recent /websearch
        # Sensory background modules
        self._vision: Optional[VisionModule] = None
        self._ambient_audio: Optional[AmbientListener] = None
        # Unified agent loop and event triggers (set during initialize())
        self._agent_loop = None
        self._llm_router = None
        self._trigger_hub = None

    async def initialize(self):
        """Initialize all components"""
        theme.print_status("Initializing Jarvis AI Agent...", "info")

        try:
            # Initialize components
            await db.initialize()
            await session_store.initialize()
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
            goal_scheduler.set_llm_client(self.llm_client)
            cron_scheduler.set_llm_client(self.llm_client)
            cron_scheduler.set_notify(lambda msg: theme.print_info(msg))
            await cron_scheduler.start()

            # ── Unified agent loop ──────────────────────────────────────────
            # Register all built-in tools (runs @jarvis_tool decorators)
            import agent.tools  # noqa: F401

            from agent.loop import init_agent_loop
            from core.slack_notifier import send_approval_request_async
            from llm.router import LLMRouter

            _router = LLMRouter(local=self.llm_client)

            async def _slack_approval(action_id, tool, args, reason, goal_id):
                return await send_approval_request_async(
                    action_id=action_id, tool=tool, args=args,
                    reason=reason, goal_id=goal_id,
                )

            self._agent_loop = init_agent_loop(db=db, slack_send_approval=_slack_approval)
            self._llm_router = _router
            theme.print_success("Unified agent loop initialised")

            # ── Slack two-way listener ──────────────────────────────────────
            from core.slack_listener import slack_listener
            if slack_listener.is_configured():
                slack_listener.set_handler(self.handle_chat_message_for_slack)
                asyncio.create_task(slack_listener.start())
                theme.print_success("Slack two-way messaging active (Socket Mode)")
            else:
                theme.print_info("Slack listener inactive — add SLACK_APP_TOKEN to .env to enable")

            # ── Event trigger hub ───────────────────────────────────────────
            from agent.triggers import TriggerHub
            self._trigger_hub = TriggerHub(
                db=db,
                agent_loop=self._agent_loop,
                llm_backend=_router,
            )
            if slack_listener.is_configured():
                self._trigger_hub.register_slack_goal_trigger(slack_listener)
            await self._trigger_hub.start()
            theme.print_success("Event trigger hub started (Gmail, Calendar, File, Slack)")

            # Catch-up: embed any conversation turns that were missed by a previous crash
            asyncio.create_task(rag_retriever.embed_pending_conversations())

            # ── Sensory background modules ──────────────────────────────────
            # Vision: DroidCam → LLaVA descriptions → FAISS
            try:
                self._vision = VisionModule()
                if await self._vision.initialize():
                    await self._vision.start()
                    theme.print_success("Vision sense active (DroidCam → memory)")
                else:
                    logger.debug("Vision unavailable; running in text mode.")
                    self._vision = None
            except Exception as _ve:
                logger.debug("Vision sense skipped: %s", _ve)
                self._vision = None

            # Audio: Blue Yeti ambient listener → Whisper transcripts → FAISS
            try:
                from extensions.audio.config import audio_config as _acfg
                if _acfg.ambient_enabled:
                    self._ambient_audio = AmbientListener()
                    if await self._ambient_audio.initialize():
                        await self._ambient_audio.start()
                        theme.print_success("Audio sense active (Blue Yeti → memory)")
                    else:
                        logger.debug("Audio unavailable; running in text mode.")
                        self._ambient_audio = None
            except Exception as _ae:
                logger.debug("Audio sense skipped: %s", _ae)
                self._ambient_audio = None

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

        # Surface any confirm-tier goals that need manual approval
        try:
            from core.goal_scheduler import get_pending_confirm_goals
            pending = get_pending_confirm_goals()
            if pending:
                theme.print_info(f"⚡ {len(pending)} goal(s) need your approval:")
                for g in pending:
                    theme.console.print(f"  • [{g['id']}] {g['goal'][:80]}")
                theme.console.print("  Run: /agent run <id>  to execute each one.")
                theme.print_separator()
        except Exception:
            pass

        # Surface any pending scheduled actions waiting for approve/deny
        try:
            pending_jobs = await cron_scheduler.get_pending()
            if pending_jobs:
                theme.print_info(f"⏰ {len(pending_jobs)} scheduled action(s) awaiting approval:")
                for j in pending_jobs:
                    theme.console.print(f"  • [{j['id']}] {j['description']}")
                theme.console.print("  Run: /approve <id>  or  /deny <id>")
                theme.print_separator()
        except Exception:
            pass
        
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
        """Build the static capabilities/tools section appended to the per-call identity.
        Date/time identity is injected fresh each call by ollama_client._build_messages()."""
        lines = []

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

        # Sensory context — describe active senses so the LLM knows to use them
        sense_lines = []
        if self._vision:
            sense_lines.append(
                "\n- Vision (DroidCam): you continuously observe the environment via a DroidCam "
                "camera feed. Descriptions of what the camera sees are embedded in your memory "
                "as 'vision_observation' documents. When asked about the environment, people "
                "present, or recent visual events, search your memory for these observations."
            )
        if self._ambient_audio:
            sense_lines.append(
                "\n- Hearing (Blue Yeti): you continuously transcribe ambient speech picked up "
                "by a Blue Yeti microphone. These transcripts are embedded in your memory as "
                "'audio_observation' documents tagged with a timestamp. When asked what was "
                "said, or about recent spoken context, search your memory for these observations."
            )
        if sense_lines:
            lines.append("\n\nActive senses (use RAG memory to recall what was seen or heard):")
            lines.extend(sense_lines)

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
            # ── Semantic guardrail: block prompt-injection before touching the LLM ──
            try:
                await vibe_checker.vibe_check(message)
            except SecurityException as sec_exc:
                theme.print_error(
                    f"[SECURITY] Input blocked — prompt injection detected "
                    f"(similarity={sec_exc.similarity:.3f})."
                )
                return

            # Check for natural language calendar requests
            if await self._try_parse_calendar_request(message):
                return

            # Check for natural language web search requests
            if await self._try_parse_web_search(message):
                return

            # General intent router — map natural language to /commands
            from cli.intent_router import detect_command_intent
            intent_cmd = detect_command_intent(message)
            if intent_cmd:
                theme.print_info(f"Command detected: {intent_cmd}")
                await self.command_handler.handle_command(intent_cmd.lstrip("/"))
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

                # Process MCP tool results — persist to FAISS, then append to user message
                tool_suffix = ""
                if agent_result.get("tool_results"):
                    tool_lines = []
                    for tr in agent_result["tool_results"]:
                        if tr["success"] and tr.get("result"):
                            result_text = str(tr["result"])
                            tool_lines.append(
                                f"{tr['server']}/{tr['tool']}:\n{result_text[:3000]}"
                            )
                            # Skip embedding if content looks like binary/base64 —
                            # embedding models return None for such content which
                            # causes PointStruct validation errors in Mem0/Qdrant.
                            _b64_chars = frozenset(
                                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
                            )
                            _looks_binary = (
                                len(result_text) > 500
                                and sum(c in _b64_chars for c in result_text[:500]) / 500 > 0.92
                            )
                            # Persist substantial, non-binary tool results to memory
                            if len(result_text) > 100 and not _looks_binary:
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
                        # Inject as part of the user turn, not the system prompt
                        tool_suffix = "\n\n[Tool results]\n" + "\n\n".join(tool_lines)

                progress.update(task, description="Generating response...")

                # Build recent in-session history from the unified session store
                recent_history = await session_store.get_recent_as_pairs(self.session_id)

                response = await self.llm_client.generate(
                    prompt=message + tool_suffix,
                    context=context,
                    stream=False,
                    conversation_history=recent_history,
                    system_prompt=self._system_prompt,
                )

            if response:
                # ── Response guardrail: same clause-level check on the output ──
                try:
                    await vibe_checker.vibe_check(response)
                except SecurityException as sec_exc:
                    theme.print_error(
                        f"[SECURITY] Response blocked — model output contained "
                        f"injected content (similarity={sec_exc.similarity:.3f}, "
                        f"clause: {sec_exc.matched_phrase!r}). Request denied."
                    )
                    return
                # ─────────────────────────────────────────────────────────────

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

                # Persist turn to the unified session store
                await session_store.add_turn(
                    self.session_id, message, response,
                    metadata={
                        "model": self.llm_client.current_model,
                        "tools_used": agent_result.get("summary", ""),
                    },
                )

                # Proactive goal proposal — scan the user's message for implied tasks.
                # Runs as a fire-and-forget background task so it never blocks the user.
                asyncio.create_task(
                    goal_scheduler.propose_goal(
                        message,
                        source="conversation",
                        notify_callback=lambda msg: theme.print_info(f"⚡ {msg}"),
                    )
                )

            else:
                theme.print_error("Failed to generate response")

        except Exception as e:
            theme.print_error(f"Chat error: {e}")

    async def _execute_google_command_for_slack(self, command: str, session_id: str) -> str:
        """Execute a Google/Gmail command detected by the intent router and return a string."""
        import shlex, asyncio
        parts = shlex.split(command.lstrip("/"))
        if not parts:
            return "Unknown command."
        cmd, args = parts[0].lower(), parts[1:]

        if cmd == "gmail":
            if not args:
                return "Usage: list my emails  |  search my emails for <query>"
            sub = args[0].lower()
            if sub == "search":
                query = " ".join(args[1:]) if len(args) > 1 else ""
                if not query:
                    return "What should I search for?"
                if not google_workspace.auth.is_authenticated():
                    return "Google isn't connected yet. Run /google-auth first."
                messages = await asyncio.to_thread(
                    google_workspace.gmail.list_messages, query=query, max_results=10
                )
                if not messages:
                    return f"No emails found for: {query}"
                lines = [f"Found {len(messages)} email(s) matching *{query}*:"]
                for m in messages[:10]:
                    lines.append(f"• *{m.get('subject', '(no subject)')}* — from {m.get('from_', '?')} on {m.get('date', '?')}")
                return "\n".join(lines)

            if sub == "list":
                if not google_workspace.auth.is_authenticated():
                    return "Google isn't connected yet. Run /google-auth first."
                messages = await asyncio.to_thread(
                    google_workspace.gmail.list_messages, max_results=10
                )
                if not messages:
                    return "No emails found in your inbox."
                lines = [f"Here are your {len(messages)} most recent email(s):"]
                for m in messages:
                    lines.append(f"• *{m.get('subject', '(no subject)')}* — from {m.get('from_', '?')} on {m.get('date', '?')}")
                return "\n".join(lines)

        # Unhandled command — fall back to LLM
        return None

    async def handle_chat_message_for_slack(self, message: str, session_id: str) -> str:
        """
        Full JARVIS chat pipeline for Slack messages.
        Same as handle_chat_message() but:
          - accepts a per-user session_id (each Slack user has their own memory)
          - returns the response string instead of printing it
          - no terminal UI (no progress bars, no theme output)
        """
        try:
            from core.security import vibe_checker, SecurityException
            try:
                await vibe_checker.vibe_check(message)
            except SecurityException as sec_exc:
                return f"Message blocked — potential injection detected (similarity={sec_exc.similarity:.3f})."

            # ── Goal intent detection ─────────────────────────────────────
            # Check if this message is asking to run a goal before falling
            # through to the normal LLM chat path.
            goal_id = _detect_goal_intent(message)
            if goal_id:
                return await self._run_goal_for_slack(goal_id, message)

            # ── Ad-hoc task routing ───────────────────────────────────────
            # If the message looks like a multi-step action request, send it
            # directly to AgentLoop rather than the chat path.
            if _is_adhoc_task(message):
                import uuid
                adhoc_id = f"adhoc_{uuid.uuid4().hex[:8]}"
                return await self._run_goal_for_slack(adhoc_id, message)

            # Intent router — same routing as normal chat
            from cli.intent_router import detect_command_intent
            intent_cmd = detect_command_intent(message)
            if intent_cmd:
                result = await self._execute_google_command_for_slack(intent_cmd, session_id)
                if result is not None:
                    return result
                # Unknown command type — fall through to LLM with intent as context

            # MCP tools
            agent_result = await mcp_agent.process_request(message)

            # Skip RAG for short conversational messages to avoid injecting irrelevant context
            is_conversational = len(message.split()) <= 6 and not agent_result.get("tool_results")
            context = "" if is_conversational else await rag_retriever.retrieve_context(message, session_id)

            # Build tool suffix
            tool_suffix = ""
            if agent_result.get("tool_results"):
                tool_lines = []
                for tr in agent_result["tool_results"]:
                    if tr["success"] and tr.get("result"):
                        result_text = str(tr["result"])
                        tool_lines.append(f"{tr['server']}/{tr['tool']}:\n{result_text[:3000]}")
                        _b64_chars = frozenset(
                            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
                        )
                        _looks_binary = (
                            len(result_text) > 500
                            and sum(c in _b64_chars for c in result_text[:500]) / 500 > 0.92
                        )
                        if len(result_text) > 100 and not _looks_binary:
                            asyncio.create_task(
                                rag_retriever.add_document(
                                    content=result_text,
                                    title=f"MCP: {tr['server']}/{tr['tool']}",
                                    url="",
                                    metadata={"source": "mcp_tool", "server": tr["server"],
                                              "tool": tr["tool"], "query": message},
                                )
                            )
                if tool_lines:
                    tool_suffix = "\n\n[Tool results]\n" + "\n\n".join(tool_lines)

            recent_history = await session_store.get_recent_as_pairs(session_id)

            # For pure conversation use the base identity only — the full capabilities
            # system prompt causes the LLM to volunteer what it can't do even on greetings
            from config import _build_system_prompt as _base_prompt
            sys_prompt = _base_prompt() if is_conversational else self._system_prompt

            # Always tell JARVIS to label his source in Slack so the user knows
            # whether the answer comes from memory, live tools, or training data
            sys_prompt = (sys_prompt or "") + (
                "\n\nIMPORTANT — you are responding in Slack. Always prefix your answer with "
                "one of these source labels so the user knows where the information came from:\n"
                "- If you used tool results: start with 'From what I can see right now through [tool name], ...'\n"
                "- If the answer comes from RAG/memory context provided above: start with 'From what I know from memory, ...'\n"
                "- If answering from training data only (no context or tools): start with 'From my general knowledge, ...'\n"
                "Keep the label natural — weave it into the first sentence, don't just paste it robotically."
            )

            response = await self.llm_client.generate(
                prompt=message + tool_suffix,
                context=context,
                stream=False,
                conversation_history=recent_history,
                system_prompt=sys_prompt,
            )

            if not response:
                return "I wasn't able to generate a response. Try again."

            # Guardrail on output
            try:
                await vibe_checker.vibe_check(response)
            except SecurityException as sec_exc:
                return "Response blocked — output contained injected content."

            # Persist to memory
            conv_id = await db.add_conversation(
                session_id=session_id,
                user_message=message,
                ai_response=response,
                model_used=self.llm_client.current_model,
                context_used=f"Tools: {agent_result.get('summary', '')}\n{context[:500]}",
            )
            asyncio.create_task(
                rag_retriever.embed_conversation(
                    user_message=message,
                    ai_response=response,
                    conversation_id=conv_id,
                    session_id=session_id,
                )
            )
            await session_store.add_turn(
                session_id, message, response,
                metadata={"model": self.llm_client.current_model,
                          "tools_used": agent_result.get("summary", ""),
                          "source": "slack"},
            )

            return response

        except Exception as exc:
            logger.error("Slack chat handler error: %s", exc)
            return f"Something went wrong: {exc}"

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

            # Stop sensory modules first
            if self._vision:
                await self._vision.stop()
            if self._ambient_audio:
                await self._ambient_audio.stop()

            await self.llm_client.cleanup()
            await web_scraper.cleanup()
            await brave_search.cleanup()
            await rag_retriever.cleanup()
            await mcp_client.cleanup()
            await google_workspace.cleanup()
            await goal_scheduler.stop()
            await cron_scheduler.stop()
            await session_store.close()

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

    async def open_screenshot(self, name: Optional[str] = None):
        """Open a puppeteer screenshot saved in /tmp."""
        import glob
        import subprocess
        from pathlib import Path

        if name:
            candidates = [f"/tmp/jrvs_{name}.png"]
        else:
            candidates = sorted(glob.glob("/tmp/jrvs_*.png"), key=lambda f: Path(f).stat().st_mtime, reverse=True)

        if not candidates or not Path(candidates[0]).exists():
            theme.print_error("No screenshots found. Ask JARVIS to take one first.")
            theme.print_info("Example: take a screenshot of https://example.com")
            return

        path = candidates[0]
        theme.print_success(f"Opening: {path}")
        try:
            subprocess.Popen(["xdg-open", path])
        except Exception as e:
            theme.print_error(f"Could not open image: {e}")
            theme.print_info(f"File is at: {path}")

        if not name and len(candidates) > 1:
            theme.print_info("Other screenshots:")
            for f in candidates[1:6]:
                theme.console.print(f"  {f}")

    async def scrape_url(self, url: str):
        """Scrape a URL and add to knowledge base"""
        with theme.show_progress(f"Scraping {url}...") as progress:
            progress.add_task("", total=None)

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
        msg_count = await session_store.count(self.session_id)
        stats['session'] = {
            'session_id': self.session_id[:8] + "...",
            'conversations': msg_count // 2,
            'current_model': self.llm_client.current_model,
            'llm_provider': self.llm_provider
        }

        theme.print_stats(stats)

    async def show_conversation_history(self, limit: int = 5):
        """Show recent conversation history"""
        history = await session_store.get_recent_as_pairs(self.session_id, limit=limit)
        if not history:
            theme.print_warning("No conversation history")
            return

        theme.print_status("Recent Conversations:", "info")

        for i, conv in enumerate(history, 1):
            theme.console.print(f"\n[{theme.get_color('accent')}]#{i}[/]")
            theme.console.print(f"[{theme.get_color('primary')}]User:[/] {conv['user'][:100]}{'...' if len(conv['user']) > 100 else ''}")
            theme.console.print(f"[{theme.get_color('secondary')}]Assistant:[/] {conv['assistant'][:200]}{'...' if len(conv['assistant']) > 200 else ''}")

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

        sources = summary.get("sources", [])
        if sources:
            theme.print_status("Sources:", "info")
            for i, s in enumerate(sources, 1):
                title = s.get("title") or s.get("url", "")
                url = s.get("url", "")
                theme.console.print(f"  [bold]{i}.[/bold] {title}")
                if url:
                    theme.console.print(f"     [dim]{url}[/dim]")

        # Store for /sources command
        self._last_sources = sources

    def set_brave_key(self, key: str):
        """Set the Brave Search API key at runtime and persist it to .env"""
        brave_search.set_api_key(key)
        # Persist to .env so it loads automatically next time
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            text = env_path.read_text()
            if "BRAVE_API_KEY=" in text:
                lines = text.splitlines(keepends=True)
                new_lines = []
                for line in lines:
                    if line.startswith("BRAVE_API_KEY="):
                        new_lines.append(f"BRAVE_API_KEY={key}\n")
                    else:
                        new_lines.append(line)
                env_path.write_text("".join(new_lines))
            else:
                with env_path.open("a") as f:
                    f.write(f"\nBRAVE_API_KEY={key}\n")
        theme.print_success("Brave Search API key updated and saved.")
        theme.print_info("Use /brave-status to confirm settings.")

    def show_sources(self):
        """Show URLs from the most recent web search"""
        if not self._last_sources:
            theme.print_info("No web search has been run yet this session. Use /websearch <query>.")
            return
        theme.print_status("Sources from last web search:", "info")
        for i, s in enumerate(self._last_sources, 1):
            title = s.get("title") or s.get("url", "")
            url = s.get("url", "")
            theme.console.print(f"  [bold]{i}.[/bold] {title}")
            if url:
                theme.console.print(f"     [dim]{url}[/dim]")

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

    async def websearch_and_answer(self, query: str):
        """Search Brave, inject results as context, and answer in one shot."""
        if not brave_search.is_configured:
            theme.print_error("Brave API key not set. Run: /brave-key <your_key>")
            return

        if brave_search.requests_remaining == 0:
            theme.print_error(
                f"Brave request budget exhausted ({brave_search.max_requests} max). "
                "Use /brave-status to check."
            )
            return

        with theme.show_progress("Searching web...") as progress:
            task = progress.add_task("", total=None)
            progress.update(task, description="Querying Brave Search API...")
            results = await brave_search.search(query)

        if not results:
            theme.print_error("No results returned from Brave.")
            return

        self._last_sources = [{"title": r["title"], "url": r["url"]} for r in results]

        snippets = "\n\n".join(
            f"[{i+1}] {r['title']}\n{r['url']}\n{r['description']}"
            for i, r in enumerate(results)
        )
        web_suffix = f"\n\n[Web search results for: {query}]\n{snippets}"

        with theme.show_progress("Generating answer...") as progress:
            task = progress.add_task("", total=None)
            progress.update(task, description="Generating response...")
            recent_history = await session_store.get_recent_as_pairs(self.session_id)
            context = await rag_retriever.retrieve_context(query, self.session_id)
            response = await self.llm_client.generate(
                prompt=query + web_suffix,
                context=context,
                stream=False,
                conversation_history=recent_history,
                system_prompt=self._system_prompt,
            )

        if response:
            theme.print_response(response)
            theme.print_info(f"Sources: {len(results)} web results — use /sources to view")

            conv_id = await db.add_conversation(
                session_id=self.session_id,
                user_message=query,
                ai_response=response,
                model_used=self.llm_client.current_model,
                context_used=f"brave_search:{query}",
            )
            asyncio.create_task(
                rag_retriever.embed_conversation(
                    user_message=query,
                    ai_response=response,
                    conversation_id=conv_id,
                    session_id=self.session_id,
                )
            )
            await session_store.add_turn(
                self.session_id, query, response,
                metadata={"model": self.llm_client.current_model, "tools_used": "brave_search"},
            )

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

    async def _try_parse_web_search(self, message: str) -> bool:
        """Detect natural language web search intent and run /websearch automatically."""
        import re

        if not brave_search.is_configured or brave_search.requests_remaining == 0:
            return False

        lower = message.lower().strip()

        # Patterns that strongly signal a live web search is needed
        _SEARCH_TRIGGERS = re.compile(
            r"\b("
            r"search (the web|online|internet|for)|"
            r"look(ing)? (it )?up( online)?|"
            r"find out|"
            r"google|"
            r"what('s| is) (the )?(latest|current|today'?s?|recent|live)|"
            r"how many .{0,40} (today|now|currently|in 20\d\d)|"
            r"(latest|current|recent|live|real.?time) .{0,40}(news|data|stats?|numbers?|rate|price|score)|"
            r"(who won|who is winning|what happened)|"
            r"news (about|on)|"
            r"as of (today|now|march|january|february|april|may|june|july|august|september|october|november|december)"
            r")\b",
            re.IGNORECASE,
        )

        if not _SEARCH_TRIGGERS.search(lower):
            return False

        # Strip filler to extract a clean search query
        query = re.sub(
            r"^(hey jarvis[,.]?\s*|jarvis[,.]?\s*|can you\s*|could you\s*|please\s*)+",
            "", message, flags=re.IGNORECASE,
        ).strip()
        query = re.sub(
            r"^(search (the web |online |internet )?for|look up|find out|google)\s*",
            "", query, flags=re.IGNORECASE,
        ).strip()

        theme.print_info(f"Web search detected — running: /websearch {query}")
        await self.websearch(query)
        return True

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

    # ------------------------------------------------------------------
    # Autonomous agent / goal scheduler commands
    # ------------------------------------------------------------------

    async def agent_list_goals(self):
        """List all goals defined in goals.yaml."""
        goals = goal_scheduler.list_goals()
        if not goals:
            theme.print_warning("No goals found. Add goals to goals.yaml.")
            return
        theme.print_status(f"Goals ({len(goals)} defined):", "info")
        for g in goals:
            enabled = "ON " if g.get("enabled", True) else "OFF"
            schedules = ", ".join(g.get("schedules", ["manual"]))
            tier = g.get("tier", "auto")
            last = g.get("last_run")
            last_str = last.strftime("%Y-%m-%d %H:%M") if last else "never"
            theme.console.print(
                f"  [{enabled}] {g['id']:<30}  sched={schedules:<20}  tier={tier:<8}  last={last_str}"
            )
        theme.print_info("Run a goal with: /agent run <id>")

    async def _run_goal_for_slack(self, goal_id: str, original_message: str) -> str:
        """Run a goal via AgentLoop and return a Slack-friendly result string."""
        from agent.loop import get_agent_loop
        from llm.router import LLMRouter

        agent_loop = get_agent_loop()
        if agent_loop is None:
            return "AgentLoop not ready — try again in a moment."

        # Load goal text from goals.yaml
        import yaml
        from pathlib import Path
        goals_file = Path(__file__).parent.parent / "goals.yaml"
        goal_text = original_message  # fallback: use the raw message as the goal
        if goals_file.exists():
            try:
                data = yaml.safe_load(goals_file.read_text()) or {}
                for g in data.get("goals", []):
                    if g.get("id") == goal_id:
                        goal_text = g.get("goal", original_message)
                        goal_text = goal_text.replace(
                            "{date}", __import__("datetime").datetime.now().strftime("%Y-%m-%d")
                        )
                        break
            except Exception:
                pass

        backend = self._llm_router or LLMRouter(local=self.llm_client)

        try:
            result = await agent_loop.run_goal(
                goal_id=goal_id,
                goal_text=goal_text,
                backend=backend,
            )
            if result.status == "completed":
                return (
                    f":white_check_mark: Goal `{goal_id}` completed "
                    f"({result.steps_ok} steps). Check Slack for details."
                )
            elif result.status == "awaiting_approval":
                return (
                    f":bell: Goal `{goal_id}` is waiting for your approval — "
                    f"check for the Approve/Deny message above."
                )
            else:
                return f":x: Goal `{goal_id}` failed: {result.error[:200]}"
        except Exception as exc:
            logger.error("_run_goal_for_slack: %s", exc)
            return f":x: Error running goal `{goal_id}`: {exc}"

    async def agent_run_goal(self, goal_id: str):
        """Run a specific goal immediately."""
        theme.print_status(f"Running goal '{goal_id}'...", "info")
        with theme.show_progress("Executing goal...") as progress:
            task = progress.add_task("", total=None)
            progress.update(task, description=f"Executing '{goal_id}'...")
            result = await goal_scheduler.run_goal(goal_id)
        theme.print_response(result)

    async def agent_run_schedule(self, schedule_name: str):
        """Run all goals that match a given schedule name."""
        valid = ("morning", "hourly", "daily", "weekly")
        if schedule_name not in valid:
            theme.print_error(f"Unknown schedule '{schedule_name}'. Valid: {', '.join(valid)}")
            return
        theme.print_status(f"Running all '{schedule_name}' goals...", "info")
        results = await goal_scheduler.run_schedule(schedule_name)
        for r in results:
            theme.console.print(r)

    def agent_scheduler_status(self):
        """Show goal scheduler state."""
        status = goal_scheduler.get_status()
        theme.print_status("Goal Scheduler Status:", "info")
        theme.console.print(f"  Running       : {status['scheduler_running']}")
        theme.console.print(f"  Goals total   : {status['goals_total']}")
        theme.console.print(f"  Goals enabled : {status['goals_enabled']}")
        if status["last_runs"]:
            theme.console.print("  Last runs:")
            for gid, ts in status["last_runs"].items():
                theme.console.print(f"    {gid}: {ts or 'never'}")

    async def agent_start_scheduler(self):
        """Start the background goal scheduler."""
        await goal_scheduler.start()
        theme.print_success("Goal scheduler started (checks every 60 s).")

    async def agent_stop_scheduler(self):
        """Stop the background goal scheduler."""
        await goal_scheduler.stop()
        theme.print_success("Goal scheduler stopped.")

    # ------------------------------------------------------------------
    # Cron scheduler commands
    # ------------------------------------------------------------------

    async def create_schedule(self, text: str):
        """Parse natural language and create a pending scheduled action."""
        theme.print_status("Parsing schedule...", "info")
        job = await cron_scheduler.create_pending(text)
        if not job:
            theme.print_error("Could not parse that as a schedule. Try something like:")
            theme.print_info('  /schedule every weekday at 9am check my emails')
            theme.print_info('  /schedule every Friday at 5pm summarise my week')
            return

        theme.print_success("Scheduled action created — waiting for your approval:")
        theme.console.print(f"  ID          : [bold]{job['id']}[/bold]")
        theme.console.print(f"  Description : {job['description']}")
        theme.console.print(f"  Action      : {job['action']}")
        theme.console.print(f"  Schedule    : {job.get('human_schedule', job['cron'])}")
        theme.console.print(f"  Cron        : {job['cron']}")
        theme.console.print()
        theme.console.print(f"  [bold]/approve {job['id']}[/bold]  to activate")
        theme.console.print(f"  [bold]/deny {job['id']}[/bold]     to discard")

    async def approve_schedule(self, job_id: str):
        """Approve and activate a pending scheduled action."""
        ok = await cron_scheduler.approve(job_id)
        if ok:
            job = await cron_scheduler.list_jobs()
            j = next((j for j in job if j["id"] == job_id), None)
            theme.print_success(f"Schedule '{job_id}' approved and active.")
            if j:
                from datetime import datetime
                nxt = datetime.fromtimestamp(j["next_run"]).strftime("%A %b %d at %I:%M %p") if j.get("next_run") else "unknown"
                theme.print_info(f"Next run: {nxt}")
        else:
            theme.print_error(f"No schedule found with ID '{job_id}'.")
            theme.print_info("Use /schedule to see all scheduled actions.")

    async def deny_schedule(self, job_id: str):
        """Deny and archive a pending scheduled action."""
        ok = await cron_scheduler.deny(job_id)
        if ok:
            theme.print_success(f"Schedule '{job_id}' denied and archived.")
        else:
            theme.print_error(f"No schedule found with ID '{job_id}'.")

    async def delete_schedule(self, job_id: str):
        """Delete a scheduled action permanently."""
        ok = await cron_scheduler.delete(job_id)
        if ok:
            theme.print_success(f"Schedule '{job_id}' deleted.")
        else:
            theme.print_error(f"No schedule found with ID '{job_id}'.")

    async def list_schedules(self):
        """List all scheduled actions."""
        jobs = await cron_scheduler.list_jobs()
        if not jobs:
            theme.print_info("No scheduled actions yet.")
            theme.print_info("Create one with: /schedule every morning check my emails")
            return

        status_colors = {
            "pending":  "yellow",
            "active":   "green",
            "denied":   "red",
            "paused":   "cyan",
        }
        theme.print_status("Scheduled Actions:", "info")
        for j in jobs:
            color = status_colors.get(j["status"], "white")
            from datetime import datetime
            nxt = ""
            if j.get("next_run") and j["status"] == "active":
                nxt = "  next: " + datetime.fromtimestamp(j["next_run"]).strftime("%a %b %d %I:%M %p")
            runs = f"  ran {j['run_count']}x" if j["run_count"] else ""
            theme.console.print(
                f"  [{color}][{j['id']}][/{color}] [{j['status'].upper()}] "
                f"{j['description'][:60]}{nxt}{runs}"
            )
        theme.console.print()
        theme.console.print("  /approve <id>         activate a pending schedule")
        theme.console.print("  /deny <id>            discard a pending schedule")
        theme.console.print("  /schedule log         show execution history")
        theme.console.print("  /schedule delete <id> permanently remove a schedule")

    async def show_schedule_log(self, job_id: Optional[str] = None):
        """Show schedule execution log."""
        from datetime import datetime
        entries = await cron_scheduler.get_log(job_id, limit=20)
        if not entries:
            msg = f"No log entries for '{job_id}'." if job_id else "No scheduled actions have run yet."
            theme.print_info(msg)
            return

        title = f"Schedule Log — {job_id}" if job_id else "Schedule Log (last 20 runs)"
        theme.print_status(title, "info")
        for e in entries:
            ts = datetime.fromtimestamp(e["ran_at"]).strftime("%Y-%m-%d %H:%M:%S")
            status = "[green]+[/green]" if e["success"] else "[red]x[/red]"
            ms = f"  ({e['duration_ms']}ms)" if e.get("duration_ms") else ""
            theme.console.print(f"  {status} [{e['job_id']}] {ts}{ms}")
            if e.get("result"):
                theme.console.print(f"    {e['result'][:120]}")

    def show_help(self):
        """Show help information"""
        commands = {
            "/help": "Show this help message",
            "/models": "List available Ollama models",
            "/switch <model>": "Switch to a different model",
            "/scrape <url>": "Scrape a website and add to knowledge base",
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
            "/search <query>": "Search web via Brave, inject results, and answer in one shot",
            "/websearch <query>": "Search web via Brave API and ingest into knowledge base (no answer)",
            "/rag <query>": "Search local knowledge base only",
            "/sources": "Show URLs from the most recent web search",
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
            "/agent goals": "List all autonomous goals from goals.yaml",
            "/agent run <id>": "Run a specific goal immediately",
            "/agent run --schedule <s>": "Run all goals for a schedule (morning|hourly|daily|weekly)",
            "/agent status": "Show goal scheduler state and last-run times",
            "/agent start": "Start the background goal scheduler",
            "/agent stop": "Stop the background goal scheduler",
            "/schedule <description>": "Create a scheduled action from natural language",
            "/schedule": "List all scheduled actions",
            "/schedule log": "Show schedule execution history",
            "/schedule delete <id>": "Delete a scheduled action",
            "/approve <id>": "Approve and activate a pending schedule",
            "/deny <id>": "Deny and discard a pending schedule",
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


# ── Ad-hoc task detection ─────────────────────────────────────────────────────

# Phrases that suggest the user wants JARVIS to *do* something, not just answer
_ADHOC_ACTION_VERBS = [
    "research", "find", "search for", "look up", "fetch",
    "create", "write", "save", "summarise", "summarize",
    "analyse", "analyze", "compile", "generate", "list",
]
_ADHOC_TOOL_HINTS = [
    "and save", "to a file", "to file", "save to", "write to",
    "and write", "and create", "and send", "then save",
    "in a file", "save it", "store it",
]

def _is_adhoc_task(message: str) -> bool:
    """
    Return True if the message looks like a multi-step action request
    that should go to AgentLoop rather than the plain chat path.
    Must have both an action verb near the start AND a tool hint anywhere.
    """
    text = message.lower().strip()
    # Must start with (or begin with "please/can you/go") an action verb
    has_verb = any(
        text.startswith(v) or text.startswith(f"please {v}")
        or text.startswith(f"can you {v}") or text.startswith(f"go {v}")
        for v in _ADHOC_ACTION_VERBS
    )
    has_hint = any(hint in text for hint in _ADHOC_TOOL_HINTS)
    return has_verb and has_hint


# ── Goal intent detection ─────────────────────────────────────────────────────

def _detect_goal_intent(message: str) -> Optional[str]:
    """
    Detect if a Slack message is asking to run a specific goal.
    Returns a goal_id string if matched, None otherwise.

    Handles:
      - Explicit: "run morning_digest", "/agent run morning_digest"
      - Natural:  "morning digest", "give me my morning digest",
                  "run the weekly report", "do the daily brief"
    """
    import re
    import yaml
    from pathlib import Path

    text = message.strip().lower()

    # Load goal IDs and their keywords from goals.yaml
    goals_file = Path(__file__).parent.parent / "goals.yaml"
    goals = []
    if goals_file.exists():
        try:
            data = yaml.safe_load(goals_file.read_text()) or {}
            goals = [g for g in data.get("goals", []) if g.get("enabled", True)]
        except Exception:
            pass

    # 1. Explicit: "run <goal_id>" or "/agent run <goal_id>"
    m = re.search(r"(?:^|\s)(?:/agent\s+run|run)\s+([a-z0-9_]+)", text)
    if m:
        candidate = m.group(1)
        for g in goals:
            if g.get("id") == candidate:
                return candidate

    # 2. Natural language match — check if the message contains enough words
    #    from the goal's ID or its name keywords
    _GOAL_ALIASES: dict[str, list[str]] = {
        "morning_digest":       ["morning digest", "morning brief", "morning summary", "overnight emails"],
        "daily_calendar_brief": ["calendar brief", "today's schedule", "what's on today", "daily brief", "calendar today"],
        "end_of_day_summary":   ["end of day", "eod summary", "daily summary", "day summary"],
        "urgent_email_watch":   ["urgent emails", "urgent email", "check urgent", "flagged emails"],
        "inbox_zero_check":     ["inbox", "unread emails", "inbox check", "check inbox"],
        "draft_reply_urgent":   ["draft reply", "draft response", "draft an email"],
        "weekly_youtube_report":["youtube report", "youtube analytics", "channel report", "weekly youtube"],
        "weekly_trend_research":["trend research", "trending topics", "research trends", "weekly trends"],
        "research_brief":       ["research brief", "ai tools brief", "research update"],
    }

    # Add any goal IDs not in the hardcoded map (using ID words as keywords)
    goal_ids_in_yaml = {g["id"] for g in goals}
    for g in goals:
        gid = g["id"]
        if gid not in _GOAL_ALIASES:
            # Convert snake_case to space-separated words as a fallback alias
            _GOAL_ALIASES[gid] = [gid.replace("_", " ")]

    for goal_id, aliases in _GOAL_ALIASES.items():
        # Only match goals that exist and are enabled in goals.yaml
        if goal_ids_in_yaml and goal_id not in goal_ids_in_yaml:
            continue
        for alias in aliases:
            if alias in text:
                return goal_id

    return None