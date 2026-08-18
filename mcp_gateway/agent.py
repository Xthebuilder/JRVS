"""
Intelligent MCP Agent for JRVS

Analyzes user requests, decides which MCP tools to use, executes them,
and logs all actions with timestamps and reasoning.
"""

import base64
import json
import logging
import asyncio
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

# Cap on in-memory session_log entries. The daemon runs 24/7, so an unbounded
# list would grow forever; a deque drops the oldest entry on overflow.
_SESSION_LOG_MAX = 1000

log = logging.getLogger(__name__)

from .client import mcp_client

# ── System prompt for internal JSON-only analysis calls ──────────────────────
_AGENT_SYSTEM_PROMPT = (
    "You are a JSON-only tool selection agent. "
    "Analyse the user request and available tools, then respond ONLY with valid "
    "JSON. Do not include any prose, markdown, or text outside the JSON object."
)

# ── Keywords that indicate a message might need tool use ─────────────────────
_TOOL_KEYWORDS = frozenset({
    # file / filesystem
    "file", "files", "read", "write", "open", "save", "create", "delete",
    "remove", "move", "copy", "rename", "directory", "folder", "path",
    "edit", "list", "ls", "contents", "config", "log", "logs",
    # search / memory / notes
    "search", "find", "look up", "lookup", "remember", "memory", "store",
    "note", "recall", "remind", "forget", "look at", "show me",
    # code / execution
    "execute", "run", "code", "script", "program", "shell", "terminal",
    "bash", "python", "javascript", "typescript", "function", "import",
    # slack / messaging
    "slack", "channel", "dm", "send",
    # web / external services
    "github", "repo", "repository", "commit", "pull request", "pr", "issue",
    "browse", "website", "url", "http", "https", "download", "fetch",
    # browser automation / puppeteer
    "screenshot", "navigate", "webpage", "visit", "page", "browser",
    "puppeteer", "click", "fill", "form", "render", "scrape",
    # video downloading (mp4-downloader)
    "video", "videos", "youtube", "clip", "clips", "watch", "grab",
    "rip", "playlist", "mp4", "stream", "subtitle", "subtitles",
    # generic action verbs on external data
    "check", "analyze", "analyse", "scan", "monitor", "upload",
    "get", "set", "update", "deploy", "build",
    # live information — facts that go stale, so they always need a lookup.
    # Without these the fast path answers from training data and invents a
    # confident-sounding number. Deliberately concrete nouns: bare time words
    # like "today" or "now" would fire on small talk and cost a round-trip.
    "weather", "forecast", "temperature", "humidity", "rain", "snow",
    "news", "headline", "headlines", "price", "prices", "stock", "stocks",
    "score", "scores", "who won", "latest", "current", "currently",
    "right now", "happening", "open now", "exchange rate",
    # workspace / documents
    "workspace", "project", "document", "spreadsheet", "sheet",
})

# ── Per-server keywords, used to pre-filter the catalogue ────────────────────
# Sending every tool's full JSON schema to the model costs ~16k tokens, which
# blows OLLAMA_NUM_CTX (4096) and makes Ollama reject the request outright with
# HTTP 400 — analysis then returns None and *every* tool silently goes unused.
# Only servers whose keywords appear in the message get sent.
_SERVER_KEYWORDS: Dict[str, frozenset] = {
    "filesystem": frozenset({
        "file", "files", "read", "write", "open", "save", "create", "delete",
        "remove", "move", "copy", "rename", "directory", "folder", "path",
        "edit", "list", "ls", "contents", "config", "workspace", "document",
    }),
    "sqlite": frozenset({
        "database", "db", "sqlite", "sql", "query", "table", "tables", "row",
        "rows", "select", "insert", "schema", "records",
    }),
    "github": frozenset({
        "github", "repo", "repository", "commit", "commits", "pull request",
        "pr", "issue", "issues", "branch", "merge", "fork", "clone",
    }),
    "sequential-thinking": frozenset({
        "think", "reason", "plan", "step by step", "break down", "brainstorm",
        "figure out", "work through",
    }),
    "brave-search": frozenset({
        "search", "google", "look up", "lookup", "find", "news", "headline",
        "headlines", "web", "online", "internet", "latest", "current",
        "today", "recent", "who is", "what is", "weather", "price",
    }),
    "puppeteer": frozenset({
        "screenshot", "navigate", "webpage", "visit", "page", "browser",
        "puppeteer", "click", "fill", "form", "render", "scrape", "url",
        "website", "http", "https", "browse",
    }),
    "slack": frozenset({
        "slack", "channel", "channels", "dm", "message", "post", "send",
        "thread", "reply",
    }),
    "mp4-downloader": frozenset({
        "video", "videos", "youtube", "clip", "clips", "watch", "download",
        "grab", "rip", "playlist", "mp4", "stream", "subtitle", "subtitles",
    }),
}

# Description text is truncated to this many chars per tool in the catalogue.
_MAX_TOOL_DESC_CHARS = 100

# Scaffolding (rules block, system prompt, user message) plus room for the
# JSON reply, in tokens. The catalogue gets whatever is left of num_ctx.
_ANALYSIS_OVERHEAD_TOKENS = 1800
_MIN_CATALOG_TOKENS = 800


def _rank_servers(message: str, servers: List[str]) -> List[str]:
    """Rank servers by how many of their keywords appear in the message.

    Servers with no keyword hit are dropped. If nothing matches, every server
    is returned unranked — the budget cap in _build_tool_catalog is then the
    only thing keeping the prompt inside the context window.
    """
    msg_lower = message.lower()
    scored = []
    for server in servers:
        keywords = _SERVER_KEYWORDS.get(server)
        if keywords is None:
            # Unknown server (config changed without updating the map) — keep it,
            # ranked last, so a new server is never silently unreachable.
            scored.append((0.5, server))
            continue
        hits = sum(1 for kw in keywords if kw in msg_lower)
        if hits:
            scored.append((hits, server))

    if not scored:
        return list(servers)

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [server for _, server in scored]


def _build_tool_catalog(all_tools: Dict[str, List[Dict]], servers: List[str]) -> List[Dict]:
    """Build a slimmed tool catalogue for the ranked servers, within budget.

    Parameter *names* replace full JSON schemas and descriptions are truncated;
    together that cuts the catalogue by roughly 70%. Servers are added in rank
    order and the loop stops once the budget is spent, so the request can never
    exceed the context window no matter how many MCP servers are connected.
    """
    from config import OLLAMA_NUM_CTX

    budget_tokens = max(OLLAMA_NUM_CTX - _ANALYSIS_OVERHEAD_TOKENS, _MIN_CATALOG_TOKENS)
    budget_chars = budget_tokens * 4

    catalog: List[Dict] = []
    used_chars = 0

    for server in servers:
        entries = []
        for tool in all_tools.get(server, []):
            schema = tool.get("input_schema") or {}
            entries.append({
                "server": server,
                "name": tool["name"],
                "desc": (tool.get("description") or "")[:_MAX_TOOL_DESC_CHARS],
                "params": list(schema.get("properties", {}).keys()),
                "required": schema.get("required", []),
            })

        server_chars = len(json.dumps(entries))
        if catalog and used_chars + server_chars > budget_chars:
            log.debug(
                "Tool catalogue budget reached — dropping %s and lower-ranked servers",
                server,
            )
            break

        catalog.extend(entries)
        used_chars += server_chars

    return catalog


@dataclass
class ActionLog:
    """Log entry for MCP tool usage"""
    timestamp: str
    action_type: str          # "tool_call", "analysis", "error"
    tool_server: Optional[str]
    tool_name: Optional[str]
    parameters: Optional[Dict]
    reasoning: str
    result: Optional[str]
    success: bool
    duration_ms: float


class MCPAgent:
    """Intelligent agent that automatically uses MCP tools"""

    def __init__(self, log_dir: str = "data/mcp_logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # Bounded deque — oldest entries drop automatically when full.
        # Prevents unbounded memory growth on a long-running daemon.
        self.session_log: deque = deque(maxlen=_SESSION_LOG_MAX)
        self._llm_client = None   # set by CLI after startup

    # ------------------------------------------------------------------
    # LLM client management — avoids hardcoding Ollama
    # ------------------------------------------------------------------

    def set_llm_client(self, client) -> None:
        """Wire the CLI's configured LLM client (Ollama or LM Studio)."""
        self._llm_client = client
        log.info("MCPAgent: LLM client injected (%s)", type(client).__name__)

    @property
    def _client(self):
        """Return the injected LLM client."""
        if self._llm_client is None:
            raise RuntimeError(
                "LLM client not injected — call set_llm_client() before using MCPAgent."
            )
        return self._llm_client

    # ------------------------------------------------------------------
    # Pre-filter: avoid LLM call for obviously conversational messages
    # ------------------------------------------------------------------

    def _needs_tool_analysis(self, message: str) -> bool:
        """
        Quick keyword scan.  Returns False for short conversational messages
        that obviously don't need tools, saving a full LLM round-trip.
        """
        msg_lower = message.lower()
        return any(kw in msg_lower for kw in _TOOL_KEYWORDS)

    # ------------------------------------------------------------------
    # Core analysis
    # ------------------------------------------------------------------

    async def analyze_request(self, user_message: str) -> Dict[str, Any]:
        """Use AI to analyse what tools are needed for a request."""

        all_tools = await mcp_client.list_all_tools()

        # Only send servers the message plausibly needs, slimmed and capped to
        # fit num_ctx. The full catalogue is ~16k tokens and gets rejected.
        ranked = _rank_servers(user_message, list(all_tools.keys()))
        tool_catalog = _build_tool_catalog(all_tools, ranked)

        if not tool_catalog:
            return {"needs_tools": False, "reasoning": "No MCP tools available"}

        log.debug(
            "Tool analysis: %d tool(s) from %s",
            len(tool_catalog),
            ", ".join(dict.fromkeys(t["server"] for t in tool_catalog)),
        )

        analysis_prompt = f"""User Request: "{user_message}"

Available Tools (with exact parameter schemas):
{json.dumps(tool_catalog, indent=2)}

Analyse the request and respond with JSON:
{{
  "needs_tools": true/false,
  "reasoning": "why tools are/aren't needed",
  "recommended_tools": [
    {{
      "server": "server_name",
      "tool": "tool_name",
      "parameters": {{"key": "value"}},
      "purpose": "what this tool will accomplish"
    }}
  ]
}}

CRITICAL RULES:
1. Each tool lists its accepted parameter names in "params" and its mandatory ones in "required".
   Use ONLY names from "params", and always supply every name in "required". Never invent parameters.
2. For puppeteer (browser/screenshot/webpage tasks), you MUST call tools in this exact order:
   a. First: puppeteer/puppeteer_navigate with {{"url": "https://..."}}
   b. For screenshots: puppeteer/puppeteer_screenshot with {{"name": "descriptive_name"}}
   c. To read page text/content: puppeteer/puppeteer_evaluate with {{"script": "document.body.innerText"}}
   d. To get page titles/links: puppeteer/puppeteer_evaluate with {{"script": "Array.from(document.querySelectorAll('a')).map(a=>a.innerText).join('\\n')"}}
   NOTE: there is NO puppeteer_get_content tool — use puppeteer_evaluate with JavaScript instead.
3. File operations → filesystem tools. IMPORTANT: to list files in a directory use `list_directory` (NOT `list_files` — that tool does not exist).
4. Database queries → sqlite tools
5. GitHub tasks → github tools
6. Thinking through complex problems → sequential-thinking tools
7. Downloading/saving a video from a link → mp4-downloader/download_video with {{"urls": "https://..."}}.
   Finding videos the user cannot link to → mp4-downloader/search_videos with {{"query": "..."}} — it returns
   candidates only, so present them and let the user choose before downloading. Do NOT use puppeteer or
   scraping tools to download videos; mp4-downloader handles the extraction itself.
8. Just conversation → no tools needed

Respond ONLY with valid JSON."""

        try:
            response = await self._client.generate(
                prompt=analysis_prompt,
                context="",
                stream=False,
                system_prompt=_AGENT_SYSTEM_PROMPT,   # overrides JRVS persona
            )

            if response is None:
                log.error("LLM returned None during tool analysis — skipping tools")
                return {"needs_tools": False, "reasoning": "LLM unavailable"}

            json_start = response.find('{')
            json_end   = response.rfind('}')          # -1 if absent
            if json_start >= 0 and json_end >= json_start:
                try:
                    return json.loads(response[json_start:json_end + 1])
                except json.JSONDecodeError:
                    log.warning("Could not parse tool-analysis JSON: %.120s", response)
                    return {"needs_tools": False, "reasoning": "Could not parse AI response"}

            log.debug("No JSON block in tool-analysis response: %.120s", response)
            return {"needs_tools": False, "reasoning": "No JSON in AI response"}

        except Exception as e:
            log.error("Tool analysis failed unexpectedly: %s", e, exc_info=True)
            return {"needs_tools": False, "reasoning": f"Analysis error: {e}"}

    async def execute_tool_plan(self, plan: Dict[str, Any]) -> List[ActionLog]:
        """Execute a plan of tool calls."""
        logs = []

        if not plan.get("needs_tools", False):
            return logs

        all_tools = await mcp_client.list_all_tools()

        for tool_plan in plan.get("recommended_tools", []):
            start_time = datetime.now()
            try:
                server = tool_plan["server"]
                tool   = tool_plan["tool"]
                params = tool_plan.get("parameters", {})
                purpose = tool_plan.get("purpose", "")

                # Validate tool exists — if not, find closest match in same server
                valid_tools = [t["name"] for t in all_tools.get(server, [])]
                if valid_tools and tool not in valid_tools:
                    import difflib
                    matches = difflib.get_close_matches(tool, valid_tools, n=1, cutoff=0.4)
                    if matches:
                        log.warning("Tool '%s/%s' not found — using closest match '%s'", server, tool, matches[0])
                        tool = matches[0]
                    else:
                        log.warning("Tool '%s/%s' not found and no close match in %s — skipping", server, tool, valid_tools)
                        continue

                result = await mcp_client.call_tool(server, tool, params)
                duration = (datetime.now() - start_time).total_seconds() * 1000

                # Treat MCP-level errors as failures
                if getattr(result, "isError", False):
                    raise RuntimeError(str(result)[:200])

                # Auto-save puppeteer screenshots to /tmp so JARVIS can open them
                saved_path: Optional[str] = None
                if server == "puppeteer" and tool == "puppeteer_screenshot":
                    shot_name = params.get("name", "screenshot")
                    try:
                        resource = await mcp_client.read_resource("puppeteer", f"screenshot://{shot_name}")
                        for content in getattr(resource, "contents", []):
                            raw = getattr(content, "blob", None) or getattr(content, "data", None)
                            if raw:
                                img_bytes = base64.b64decode(raw) if isinstance(raw, str) else raw
                                saved_path = f"/tmp/jrvs_{shot_name}.png"
                                Path(saved_path).write_bytes(img_bytes)
                                log.info("Screenshot saved: %s", saved_path)
                                break
                    except Exception as exc:
                        log.warning("Could not save screenshot resource: %s", exc)

                if saved_path:
                    # Use only the clean path — don't include raw base64 PNG bytes
                    result_str = f"Screenshot saved to {saved_path}"
                else:
                    result_str = str(result)[:4000]

                log_entry = ActionLog(
                    timestamp=datetime.now().isoformat(),
                    action_type="tool_call",
                    tool_server=server,
                    tool_name=tool,
                    parameters=params,
                    reasoning=purpose,
                    result=result_str,
                    success=True,
                    duration_ms=duration,
                )

            except Exception as e:
                duration = (datetime.now() - start_time).total_seconds() * 1000
                log_entry = ActionLog(
                    timestamp=datetime.now().isoformat(),
                    action_type="tool_call",
                    tool_server=tool_plan.get("server"),
                    tool_name=tool_plan.get("tool"),
                    parameters=tool_plan.get("parameters"),
                    reasoning=tool_plan.get("purpose", ""),
                    result=None,
                    success=False,
                    duration_ms=duration,
                )

            logs.append(log_entry)
            self.session_log.append(log_entry)

        return logs

    async def process_request(self, user_message: str) -> Dict[str, Any]:
        """
        Main entry point — analyse request, execute tools, return results.

        Skips LLM analysis entirely for messages that contain no tool-related
        keywords, eliminating the double-LLM latency for normal conversation.
        """

        # ── Fast path: skip analysis if no LLM client or no keywords ────────
        if self._llm_client is None:
            return {
                "analysis": {"needs_tools": False, "reasoning": "LLM client not yet available"},
                "actions": [],
                "summary": "No tools needed",
                "tool_results": [],
            }
        if not self._needs_tool_analysis(user_message):
            return {
                "analysis": {"needs_tools": False, "reasoning": "No tool keywords detected"},
                "actions": [],
                "summary": "No tools needed - handling as conversation",
                "tool_results": [],
            }

        # ── Full LLM analysis path ─────────────────────────────────────────
        analysis = await self.analyze_request(user_message)

        analysis_log = ActionLog(
            timestamp=datetime.now().isoformat(),
            action_type="analysis",
            tool_server=None,
            tool_name=None,
            parameters=None,
            reasoning=analysis.get("reasoning", ""),
            result=json.dumps(analysis),
            success=True,
            duration_ms=0,
        )
        self.session_log.append(analysis_log)

        actions = []
        tool_results = []

        if analysis.get("needs_tools", False):
            actions = await self.execute_tool_plan(analysis)
            tool_results = [
                {
                    "server": log.tool_server,
                    "tool":   log.tool_name,
                    "success": log.success,
                    "result":  log.result,
                }
                for log in actions
            ]

        if actions:
            successful = sum(1 for a in actions if a.success)
            summary = f"Executed {len(actions)} tool(s), {successful} successful"
        else:
            summary = "No tools needed - handling as conversation"

        return {
            "analysis": analysis,
            "actions":  actions,
            "summary":  summary,
            "tool_results": tool_results,
        }

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def save_session_log(self, session_id: str):
        log_file = self.log_dir / f"session_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        log_data = {
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "total_actions": len(self.session_log),
            "actions": [asdict(log) for log in self.session_log],
        }
        with open(log_file, 'w') as f:
            json.dump(log_data, f, indent=2)
        return log_file

    def generate_report(self, session_id: str) -> str:
        if not self.session_log:
            return "No actions logged in this session."

        report_lines = [
            "=" * 70,
            "JRVS MCP AGENT ACTIVITY REPORT",
            f"Session: {session_id}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 70, "",
        ]

        tool_calls = [l for l in self.session_log if l.action_type == "tool_call"]
        successful = sum(1 for l in tool_calls if l.success)
        failed     = len(tool_calls) - successful

        report_lines += [
            "SUMMARY", "-" * 70,
            f"Total Actions: {len(self.session_log)}",
            f"Tool Calls: {len(tool_calls)}",
            f"Successful: {successful}",
            f"Failed: {failed}",
            f"Average Duration: {sum(l.duration_ms for l in tool_calls) / len(tool_calls) if tool_calls else 0:.2f}ms",
            "",
        ]

        report_lines += ["DETAILED ACTIONS", "-" * 70, ""]

        for i, log in enumerate(self.session_log, 1):
            ts = datetime.fromisoformat(log.timestamp).strftime('%H:%M:%S')
            if log.action_type == "analysis":
                report_lines += [f"{i}. [{ts}] ANALYSIS", f"   Reasoning: {log.reasoning}", ""]
            elif log.action_type == "tool_call":
                status = "+ SUCCESS" if log.success else "x FAILED"
                report_lines += [
                    f"{i}. [{ts}] TOOL CALL - {status}",
                    f"   Server: {log.tool_server}",
                    f"   Tool: {log.tool_name}",
                    f"   Purpose: {log.reasoning}",
                    f"   Parameters: {json.dumps(log.parameters, indent=6)}",
                    f"   Duration: {log.duration_ms:.2f}ms",
                ]
                if log.result:
                    preview = log.result[:300] + "..." if len(log.result) > 300 else log.result
                    report_lines.append(f"   Result: {preview}")
                report_lines.append("")

        report_lines += ["=" * 70, "END OF REPORT", "=" * 70]
        return "\n".join(report_lines)


# Global agent instance
mcp_agent = MCPAgent()
