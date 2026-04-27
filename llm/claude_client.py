"""
Anthropic Claude API client — implements LLMBackend protocol.

Used when a goal is prefixed with '!strong' to route to a more capable
cloud model for complex planning or reasoning tasks.

Requires ANTHROPIC_API_KEY in environment.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp

log = logging.getLogger(__name__)

_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"


class ClaudeClient:
    """Anthropic Claude client conforming to the LLMBackend protocol."""

    current_model: str
    base_url: str = _API_URL

    def __init__(self, model: Optional[str] = None) -> None:
        from config import CLAUDE_MODEL
        self.current_model = model or CLAUDE_MODEL
        self.base_url = _API_URL

    # ── Core API ──────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        stream: bool = False,
        system_prompt: Optional[str] = None,
        context: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
    ) -> Optional[str]:
        messages = self._build_messages(prompt, context, system_prompt, conversation_history)
        return await self._post(messages, model or self.current_model)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
    ) -> Optional[str]:
        return await self._post(messages, model or self.current_model)

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _post(self, messages: List[Dict], model: str) -> Optional[str]:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set — required for !strong goals. "
                "Add it to your .env file."
            )

        # Anthropic API requires system as a top-level field, not a message role
        system: Optional[str] = None
        user_messages = []
        for m in messages:
            if m.get("role") == "system":
                system = m["content"]
            else:
                user_messages.append(m)

        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "messages": user_messages,
        }
        if system:
            payload["system"] = system

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _API_URL,
                    json=payload,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": _ANTHROPIC_VERSION,
                        "content-type": "application/json",
                    },
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"Claude API error {resp.status}: {body[:300]}")
                    data = await resp.json()
            return data["content"][0]["text"]
        except aiohttp.ClientError as exc:
            log.error("ClaudeClient: network error: %s", exc)
            raise

    def _build_messages(
        self,
        user_prompt: str,
        context: Optional[str] = None,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
    ) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if conversation_history:
            messages.extend(conversation_history)
        content = user_prompt
        if context:
            content = f"Context:\n{context}\n\n{user_prompt}"
        messages.append({"role": "user", "content": content})
        return messages

    # ── LLMBackend protocol stubs ─────────────────────────────────────────────

    async def discover_models(self) -> List[str]:
        return [self.current_model]

    async def switch_model(self, model_name: str) -> bool:
        self.current_model = model_name
        return True

    async def list_models(self) -> List[Dict]:
        return [{"name": self.current_model, "provider": "anthropic"}]

    async def get_model_info(self, model_name: Optional[str] = None) -> Dict:
        return {"name": model_name or self.current_model, "provider": "anthropic"}

    async def set_base_url(self, base_url: str) -> None:
        self.base_url = base_url

    async def cleanup(self) -> None:
        pass
