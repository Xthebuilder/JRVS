"""
JRVS LLM Backend Protocol — formal interface for all LLM clients.

Both OllamaClient and LMStudioClient conform to this protocol.
Adding a new backend (llama.cpp, vLLM, etc.) requires implementing
this same interface.

Usage:
    from llm.protocol import LLMBackend

    def my_function(llm: LLMBackend):
        response = await llm.generate("Hello")
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMBackend(Protocol):
    """Protocol that all LLM backend clients must implement."""

    current_model: str
    base_url: str

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        stream: bool = True,
        system_prompt: Optional[str] = None,
        context: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
    ) -> Optional[str]:
        """Generate a response from the LLM."""
        ...

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = True,
    ) -> Optional[str]:
        """Direct chat interface — pass your own messages array."""
        ...

    async def discover_models(self) -> List[str]:
        """Discover available models from the backend."""
        ...

    async def switch_model(self, model_name: str) -> bool:
        """Switch to a different model. Returns True on success."""
        ...

    async def list_models(self) -> List[Dict]:
        """List all available models with metadata."""
        ...

    async def get_model_info(self, model_name: Optional[str] = None) -> Dict:
        """Get information about a specific or current model."""
        ...

    async def set_base_url(self, base_url: str) -> None:
        """Update the backend URL and reset connection."""
        ...

    async def cleanup(self) -> None:
        """Clean up resources (close sessions, etc.)."""
        ...

    def _build_messages(
        self,
        user_prompt: str,
        context: Optional[str] = None,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
    ) -> List[Dict[str, str]]:
        """Build the messages array for the chat API."""
        ...
