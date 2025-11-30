"""
Intelligent MCP Agent for JRVS

This agent analyzes user requests and automatically:
1. Determines which MCP tools to use
2. Executes the tools with appropriate parameters
3. Logs all actions with timestamps and reasoning
4. Generates reports of completed tasks
"""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

from .client import mcp_client
from llm.ollama_client import ollama_client


@dataclass
class ActionLog:
    """Log entry for MCP tool usage"""
    timestamp: str
    action_type: str  # "tool_call", "analysis", "error"
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

    async def analyze_request(self, user_message: str) -> Dict[str, Any]:
        """Use AI to analyze what tools are needed for a request"""

        # Get available tools
        all_tools = await mcp_client.list_all_tools()

        # Build tool catalog for AI
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

        # Create analysis prompt
        analysis_prompt = f"""You are an AI agent analyzer. Given a user request and available tools, determine if any tools should be used.

User Request: "{user_message}"

Available Tools:
{json.dumps(tool_catalog, indent=2)}

Analyze the request and respond with JSON:
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
- Does the request require file operations? → Use filesystem tools
- Does it need web search? → Use brave-search tools (if available)
- Should information be remembered? → Use memory tools
- Is it just a conversation? → No tools needed

Respond ONLY with valid JSON, no other text."""

        try:
            # Get AI analysis
            response = await ollama_client.generate(
                prompt=analysis_prompt,
                context="",
                stream=False
            )

            # Parse JSON response
            # Try to extract JSON from response
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                analysis = json.loads(json_str)
                return analysis
            else:
                return {"needs_tools": False, "reasoning": "Could not parse AI response"}

        except Exception as e:
            return {"needs_tools": False, "reasoning": f"Analysis error: {e}"}

    async def execute_tool_plan(self, plan: Dict[str, Any]) -> List[ActionLog]:
        """Execute a plan of tool calls"""
        logs = []

        if not plan.get("needs_tools", False):
            return logs

        recommended_tools = plan.get("recommended_tools", [])

        for tool_plan in recommended_tools:
            start_time = datetime.now()

            try:
                server = tool_plan["server"]
                tool = tool_plan["tool"]
                params = tool_plan.get("parameters", {})
                purpose = tool_plan.get("purpose", "")

                # Execute tool
                result = await mcp_client.call_tool(server, tool, params)

                # Calculate duration
                duration = (datetime.now() - start_time).total_seconds() * 1000

                # Log success
                log_entry = ActionLog(
                    timestamp=datetime.now().isoformat(),
                    action_type="tool_call",
                    tool_server=server,
                    tool_name=tool,
                    parameters=params,
                    reasoning=purpose,
                    result=str(result)[:500],  # Truncate long results
                    success=True,
                    duration_ms=duration
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
                    duration_ms=duration
                )

            logs.append(log_entry)
            self.session_log.append(log_entry)

        return logs

    async def process_request(self, user_message: str) -> Dict[str, Any]:
        """
        Main entry point - analyze request, execute tools, return results

        Returns:
            {
                "analysis": {...},
                "actions": [...],
                "summary": "what was done",
                "tool_results": [...]
            }
        """

        # Analyze request
        analysis = await self.analyze_request(user_message)

        # Log analysis
        analysis_log = ActionLog(
            timestamp=datetime.now().isoformat(),
            action_type="analysis",
            tool_server=None,
            tool_name=None,
            parameters=None,
            reasoning=analysis.get("reasoning", ""),
            result=json.dumps(analysis),
            success=True,
            duration_ms=0
        )
        self.session_log.append(analysis_log)

        # Execute tools if needed
        actions = []
        tool_results = []

        if analysis.get("needs_tools", False):
            actions = await self.execute_tool_plan(analysis)
            tool_results = [
                {
                    "server": log.tool_server,
                    "tool": log.tool_name,
                    "success": log.success,
                    "result": log.result
                }
                for log in actions
            ]

        # Generate summary
        if actions:
            successful = sum(1 for a in actions if a.success)
            summary = f"Executed {len(actions)} tool(s), {successful} successful"
        else:
            summary = "No tools needed - handling as conversation"

        return {
            "analysis": analysis,
            "actions": actions,
            "summary": summary,
            "tool_results": tool_results
        }

    def save_session_log(self, session_id: str):
        """Save session log to file"""
        log_file = self.log_dir / f"session_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        log_data = {
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "total_actions": len(self.session_log),
            "actions": [asdict(log) for log in self.session_log]
        }

        with open(log_file, 'w') as f:
            json.dump(log_data, f, indent=2)

        return log_file

    def generate_report(self, session_id: str) -> str:
        """Generate human-readable report of session activity"""

        if not self.session_log:
            return "No actions logged in this session."

        report_lines = [
            "="*70,
            f"JRVS MCP AGENT ACTIVITY REPORT",
            f"Session: {session_id}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "="*70,
            ""
        ]

        # Summary stats
        tool_calls = [log for log in self.session_log if log.action_type == "tool_call"]
        successful = sum(1 for log in tool_calls if log.success)
        failed = len(tool_calls) - successful

        report_lines.extend([
            "SUMMARY",
            "-"*70,
            f"Total Actions: {len(self.session_log)}",
            f"Tool Calls: {len(tool_calls)}",
            f"Successful: {successful}",
            f"Failed: {failed}",
            f"Average Duration: {sum(log.duration_ms for log in tool_calls) / len(tool_calls) if tool_calls else 0:.2f}ms",
            ""
        ])

        # Detailed actions
        report_lines.extend([
            "DETAILED ACTIONS",
            "-"*70,
            ""
        ])

        for i, log in enumerate(self.session_log, 1):
            timestamp = datetime.fromisoformat(log.timestamp).strftime('%H:%M:%S')

            if log.action_type == "analysis":
                report_lines.extend([
                    f"{i}. [{timestamp}] ANALYSIS",
                    f"   Reasoning: {log.reasoning}",
                    ""
                ])

            elif log.action_type == "tool_call":
                status = "✓ SUCCESS" if log.success else "✗ FAILED"
                report_lines.extend([
                    f"{i}. [{timestamp}] TOOL CALL - {status}",
                    f"   Server: {log.tool_server}",
                    f"   Tool: {log.tool_name}",
                    f"   Purpose: {log.reasoning}",
                    f"   Parameters: {json.dumps(log.parameters, indent=6)}",
                    f"   Duration: {log.duration_ms:.2f}ms",
                ])

                if log.result:
                    result_preview = log.result[:200] + "..." if len(log.result) > 200 else log.result
                    report_lines.append(f"   Result: {result_preview}")

                report_lines.append("")

        report_lines.extend([
            "="*70,
            "END OF REPORT",
            "="*70
        ])

        return "\n".join(report_lines)


# Global agent instance
mcp_agent = MCPAgent()
