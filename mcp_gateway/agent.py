"""
Intelligent MCP Agent for JRVS

Analyzes user requests, decides which MCP tools to use, executes them,
and logs all actions with timestamps and reasoning.
"""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

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
    "edit", "list", "ls",
    # search / memory / notes
    "search", "find", "look up", "lookup", "remember", "memory", "store",
    "note", "recall", "remind", "forget",
    # code / execution
    "execute", "run", "code", "script", "program", "shell", "terminal",
    "bash", "python",
    # web / external services
    "github", "repo", "repository", "commit", "pull request", "issue",
    "browse", "website", "url", "http", "https", "download", "fetch",
    # generic action verbs on external data
    "check", "analyze", "scan", "monitor", "upload", "show me",
})


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
        self.session_log: List[ActionLog] = []
        self._llm_client = None   # set by CLI after startup

    # ------------------------------------------------------------------
    # LLM client management — avoids hardcoding Ollama
    # ------------------------------------------------------------------

    def set_llm_client(self, client) -> None:
        """Wire the CLI's configured LLM client (Ollama or LM Studio)."""
        self._llm_client = client

    @property
    def _client(self):
        """Return the configured LLM client, falling back to Ollama."""
        if self._llm_client is not None:
            return self._llm_client
        from llm.ollama_client import ollama_client
        return ollama_client

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

        tool_catalog = []
        for server, tools in all_tools.items():
            for tool in tools:
                tool_catalog.append({
                    "server": server,
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "params": tool.get("input_schema", {})
                })

        if not tool_catalog:
            return {"needs_tools": False, "reasoning": "No MCP tools available"}

        analysis_prompt = f"""User Request: "{user_message}"

Available Tools:
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

Consider:
- File operations → filesystem tools
- Remembering info → memory tools
- Just conversation → no tools needed

Respond ONLY with valid JSON."""

        try:
            response = await self._client.generate(
                prompt=analysis_prompt,
                context="",
                stream=False,
                system_prompt=_AGENT_SYSTEM_PROMPT,   # overrides JRVS persona
            )

            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(response[json_start:json_end])

            return {"needs_tools": False, "reasoning": "Could not parse AI response"}

        except Exception as e:
            return {"needs_tools": False, "reasoning": f"Analysis error: {e}"}

    async def execute_tool_plan(self, plan: Dict[str, Any]) -> List[ActionLog]:
        """Execute a plan of tool calls."""
        logs = []

        if not plan.get("needs_tools", False):
            return logs

        for tool_plan in plan.get("recommended_tools", []):
            start_time = datetime.now()
            try:
                server = tool_plan["server"]
                tool   = tool_plan["tool"]
                params = tool_plan.get("parameters", {})
                purpose = tool_plan.get("purpose", "")

                result = await mcp_client.call_tool(server, tool, params)
                duration = (datetime.now() - start_time).total_seconds() * 1000

                log_entry = ActionLog(
                    timestamp=datetime.now().isoformat(),
                    action_type="tool_call",
                    tool_server=server,
                    tool_name=tool,
                    parameters=params,
                    reasoning=purpose,
                    result=str(result)[:4000],   # was 500 — increased to 4000
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

        # ── Fast path: skip analysis for conversational messages ──────────
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
