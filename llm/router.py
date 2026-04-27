"""
LLM Router — routes goals to Ollama (local) or Claude (cloud).

Usage:
    router = LLMRouter(local=ollama_client)
    goal_text, backend = router.route(raw_goal_text)
    response = await backend.generate(prompt=goal_text, ...)

If goal_text starts with '!strong ', the prefix is stripped and the
request is sent to Claude instead of Ollama.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from llm.protocol import LLMBackend

log = logging.getLogger(__name__)

_STRONG_PREFIX = "!strong "


class LLMRouter:
    """Wraps a local LLMBackend and optionally a cloud backend."""

    def __init__(self, local: LLMBackend) -> None:
        self._local = local
        self._cloud: Optional[LLMBackend] = None

    def route(self, goal_text: str) -> Tuple[str, LLMBackend]:
        """
        Return (stripped_goal_text, backend_to_use).

        If goal_text starts with '!strong ', strip the prefix and use the
        cloud backend. Otherwise use the local backend.
        """
        if goal_text.startswith(_STRONG_PREFIX):
            stripped = goal_text[len(_STRONG_PREFIX):].lstrip()
            log.info("LLMRouter: routing to cloud backend (Claude)")
            return stripped, self._get_cloud()
        return goal_text, self._local

    def _get_cloud(self) -> LLMBackend:
        if self._cloud is None:
            from llm.claude_client import ClaudeClient
            self._cloud = ClaudeClient()
            log.info("LLMRouter: initialised ClaudeClient")
        return self._cloud

    # Delegate LLMBackend protocol to local backend so the router can be
    # used as a drop-in wherever an LLMBackend is expected.

    @property
    def current_model(self) -> str:
        return self._local.current_model

    @property
    def base_url(self) -> str:
        return self._local.base_url

    async def generate(self, prompt: str, **kwargs):
        text, backend = self.route(prompt)
        return await backend.generate(text, **kwargs)

    async def chat(self, messages, **kwargs):
        return await self._local.chat(messages, **kwargs)

    async def discover_models(self):
        return await self._local.discover_models()

    async def switch_model(self, model_name: str) -> bool:
        return await self._local.switch_model(model_name)

    async def list_models(self):
        return await self._local.list_models()

    async def get_model_info(self, model_name=None):
        return await self._local.get_model_info(model_name)

    async def set_base_url(self, base_url: str) -> None:
        await self._local.set_base_url(base_url)

    async def cleanup(self) -> None:
        await self._local.cleanup()

    def _build_messages(self, user_prompt, context=None, system_prompt=None, conversation_history=None):
        return self._local._build_messages(user_prompt, context, system_prompt, conversation_history)
