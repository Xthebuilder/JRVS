"""Ollama client — uses /api/chat for proper message history and system prompt"""
import asyncio
import aiohttp
import json
import logging
import time
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

from config import OLLAMA_BASE_URL, DEFAULT_MODEL, TIMEOUTS, SYSTEM_PROMPT
from core.database import db
from core.lazy_loader import retry_on_failure

log = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip('/')
        self.current_model = DEFAULT_MODEL
        self.session = None
        self._available_models = []
        self._model_info = {}
        self._last_model_check = 0
        self._check_interval = 60

    @asynccontextmanager
    async def _get_session(self):
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=TIMEOUTS["ollama_response"])
            self.session = aiohttp.ClientSession(timeout=timeout)

        try:
            yield self.session
        except aiohttp.ClientConnectorError:
            if self.session and not self.session.closed:
                await self.session.close()
            self.session = None
            raise
        except Exception:
            raise

    async def _check_ollama_connection(self) -> bool:
        try:
            async with self._get_session() as session:
                async with session.get(f"{self.base_url}/api/tags") as response:
                    return response.status == 200
        except Exception:
            return False

    async def discover_models(self) -> List[str]:
        current_time = time.time()
        if current_time - self._last_model_check < self._check_interval:
            return self._available_models

        try:
            async with self._get_session() as session:
                async with session.get(f"{self.base_url}/api/tags") as response:
                    if response.status == 200:
                        data = await response.json()
                        models = [model['name'] for model in data.get('models', [])]
                        for model_data in data.get('models', []):
                            model_name = model_data['name']
                            self._model_info[model_name] = {
                                'size': model_data.get('size', 0),
                                'modified_at': model_data.get('modified_at', ''),
                                'details': model_data.get('details', {})
                            }
                        self._available_models = models
                        self._last_model_check = current_time
                        return models
                    return self._available_models
        except Exception as e:
            log.warning("Error discovering models: %s", e)
            return self._available_models

    async def switch_model(self, model_name: str) -> bool:
        available_models = await self.discover_models()

        if model_name in available_models:
            target_model = model_name
        else:
            matches = [m for m in available_models if m.startswith(model_name)]
            if len(matches) == 1:
                target_model = matches[0]
            elif len(matches) > 1:
                log.warning("Multiple models match '%s': %s", model_name, matches)
                return False
            else:
                log.warning("Model '%s' not available. Available: %s", model_name, available_models)
                return False

        test_response = await self.generate(prompt="Hello", model=target_model, stream=False)
        if test_response:
            self.current_model = target_model
            return True
        return False

    # ------------------------------------------------------------------
    # Core generation — now uses /api/chat with proper message structure
    # ------------------------------------------------------------------

    async def generate(self, prompt: str, model: Optional[str] = None,
                       stream: bool = True, system_prompt: Optional[str] = None,
                       context: Optional[str] = None,
                       conversation_history: Optional[List[Dict]] = None) -> Optional[str]:
        """
        Generate a response using /api/chat.

        conversation_history — list of dicts with keys 'user' and 'assistant',
        representing the in-session turns that precede this message.
        context — RAG-retrieved text injected into the system message.
        """
        model = model or self.current_model
        start_time = time.time()

        if not await self._check_ollama_connection():
            log.error("Ollama is not running or not accessible at %s", self.base_url)
            return None

        messages = self._build_messages(prompt, context, system_prompt, conversation_history)

        try:
            if stream:
                response = await self._chat_streaming({"model": model, "messages": messages, "stream": True})
            else:
                response = await self._chat_non_streaming({"model": model, "messages": messages, "stream": False})

            response_time = time.time() - start_time
            await db.update_model_stats(model, response_time)
            return response

        except asyncio.TimeoutError:
            log.error("Ollama generate timed out after %ss", TIMEOUTS['ollama_response'])
            return None
        except Exception as e:
            log.error("Error generating response: %s", e)
            return None

    def _build_messages(self, user_prompt: str, context: Optional[str] = None,
                        system_prompt: Optional[str] = None,
                        conversation_history: Optional[List[Dict]] = None) -> List[Dict]:
        """
        Build the messages array for /api/chat:
          1. System message — JRVS identity + RAG context
          2. Alternating user/assistant turns from conversation_history
          3. Current user message
        """
        messages = []

        # --- System message ---
        sys_content = system_prompt or SYSTEM_PROMPT
        if context and context.strip():
            sys_content += f"\n\n--- Memory & Knowledge ---\n{context}"
        messages.append({"role": "system", "content": sys_content})

        # --- Conversation history (in-session turns for continuity) ---
        if conversation_history:
            for turn in conversation_history:
                messages.append({"role": "user",      "content": turn.get('user', '')})
                messages.append({"role": "assistant",  "content": turn.get('assistant', '')})

        # --- Current user message ---
        messages.append({"role": "user", "content": user_prompt})

        return messages

    # ------------------------------------------------------------------
    # /api/chat transport (streaming and non-streaming)
    # ------------------------------------------------------------------

    async def _chat_streaming(self, request_data: Dict) -> Optional[str]:
        full_response = ""
        try:
            async with self._get_session() as session:
                async with session.post(
                    f"{self.base_url}/api/chat", json=request_data
                ) as response:
                    if response.status != 200:
                        log.error("Ollama streaming HTTP error: %s", response.status)
                        return None
                    async for line in response.content:
                        line = line.decode('utf-8').strip()
                        if line:
                            try:
                                data = json.loads(line)
                                if 'message' in data and 'content' in data['message']:
                                    chunk = data['message']['content']
                                    full_response += chunk
                                    print(chunk, end='', flush=True)
                                if data.get('done', False):
                                    print()
                                    break
                            except json.JSONDecodeError:
                                continue
            return full_response if full_response.strip() else None
        except Exception as e:
            log.error("Ollama streaming error: %s", e)
            return None

    @retry_on_failure(max_retries=2, delay=1.0, backoff=2.0)
    async def _chat_non_streaming(self, request_data: Dict) -> Optional[str]:
        try:
            async with self._get_session() as session:
                async with session.post(
                    f"{self.base_url}/api/chat", json=request_data
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('message', {}).get('content', '').strip()
                    log.error("Ollama non-streaming HTTP error: %s", response.status)
                    return None
        except Exception as e:
            log.error("Ollama generation error: %s", e)
            return None

    async def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None,
                   stream: bool = True) -> Optional[str]:
        """Direct chat interface — pass your own messages array"""
        model = model or self.current_model
        request_data = {"model": model, "messages": messages, "stream": stream}
        if stream:
            return await self._chat_streaming(request_data)
        return await self._chat_non_streaming(request_data)

    # ------------------------------------------------------------------
    # Model info helpers
    # ------------------------------------------------------------------

    async def get_model_info(self, model_name: Optional[str] = None) -> Dict:
        model_name = model_name or self.current_model
        if model_name in self._model_info:
            return self._model_info[model_name]
        await self.discover_models()
        return self._model_info.get(model_name, {})

    async def list_models(self) -> List[Dict]:
        models = await self.discover_models()
        return [
            {
                'name': m,
                'current': m == self.current_model,
                'size': self._model_info.get(m, {}).get('size', 0),
                'modified_at': self._model_info.get(m, {}).get('modified_at', ''),
                'details': self._model_info.get(m, {}).get('details', {}),
            }
            for m in models
        ]

    async def set_base_url(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None

    async def cleanup(self):
        if self.session and not self.session.closed:
            await self.session.close()


# Global Ollama client instance
ollama_client = OllamaClient()
