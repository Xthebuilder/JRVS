"""Ollama client — uses /api/chat for proper message history and system prompt"""
import asyncio
import aiohttp
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, TypedDict


class ConversationTurn(TypedDict):
    user: str
    assistant: str
from contextlib import asynccontextmanager

from config import (
    OLLAMA_BASE_URL, DEFAULT_MODEL, TIMEOUTS, OLLAMA_KEEP_ALIVE, OLLAMA_NUM_CTX,
    IDENTITY_BASE, _platform_safe_strftime,
)
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
        if test_response is not None:
            self.current_model = target_model
            return True
        return False

    # ------------------------------------------------------------------
    # Core generation — now uses /api/chat with proper message structure
    # ------------------------------------------------------------------

    async def generate(self, prompt: str, model: Optional[str] = None,
                       stream: bool = True, system_prompt: Optional[str] = None,
                       context: Optional[str] = None,
                       conversation_history: Optional[List[ConversationTurn]] = None) -> Optional[str]:
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

        messages, num_keep = self._build_messages(prompt, context, system_prompt, conversation_history)
        options = {"num_keep": num_keep, "num_ctx": OLLAMA_NUM_CTX}

        try:
            if stream:
                response = await self._chat_streaming({
                    "model": model, "messages": messages,
                    "stream": True, "keep_alive": OLLAMA_KEEP_ALIVE,
                    "options": options,
                })
            else:
                response = await self._chat_non_streaming({
                    "model": model, "messages": messages,
                    "stream": False, "keep_alive": OLLAMA_KEEP_ALIVE,
                    "options": options,
                })

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
                        conversation_history: Optional[List[ConversationTurn]] = None
                        ) -> tuple[List[Dict], int]:
        """
        Build the messages array for /api/chat and return (messages, num_keep).

        KV-cache prefilling strategy
        ----------------------------
        Ollama reuses the KV cache for any prefix that is token-for-token identical
        to the previous request.  To maximise cache hits we keep the system message
        STATIC across turns:

          system  = IDENTITY_BASE + optional capabilities block
                    ← never changes between turns → fully cached

        Dynamic content that changes every turn (timestamp, RAG context) is
        injected as a structured prefix inside the *user* message instead, so
        only the genuinely new tokens are ever re-processed:

          user    = [Context: <date>, <time>]
                    --- Memory & Knowledge ---
                    <rag context>

                    <actual user prompt>

        num_keep is set to the estimated token count of the static system message
        so Ollama preserves those tokens when truncating the context window.
        """
        messages = []

        # ── Static system message (KV-cached) ────────────────────────────────
        static_sys = IDENTITY_BASE
        if system_prompt:
            static_sys += "\n\n" + system_prompt
        messages.append({"role": "system", "content": static_sys})

        # Estimate token count for num_keep (4 chars ≈ 1 token + 32 template overhead)
        num_keep = len(static_sys) // 4 + 32

        # ── Conversation history ─────────────────────────────────────────────
        if conversation_history:
            for turn in conversation_history:
                messages.append({"role": "user",      "content": turn.get("user", "")})
                messages.append({"role": "assistant", "content": turn.get("assistant", "")})

        # ── Current user message — dynamic prefix + prompt ───────────────────
        now = datetime.now()
        date_str = _platform_safe_strftime("%A, %B %-d, %Y", now)
        time_str = _platform_safe_strftime("%-I:%M %p", now)
        dynamic_parts = [f"[Context: {date_str}, {time_str}]"]
        if context and context.strip():
            dynamic_parts.append(f"--- Memory & Knowledge ---\n{context}")

        full_user_msg = "\n\n".join(dynamic_parts) + "\n\n" + user_prompt
        messages.append({"role": "user", "content": full_user_msg})

        return messages, num_keep

    # ------------------------------------------------------------------
    # /api/chat transport (streaming and non-streaming)
    # ------------------------------------------------------------------

    async def _chat_streaming(self, request_data: Dict) -> Optional[str]:
        full_response = ""
        ttft_logged = False
        request_start = time.time()
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
                                    if chunk and not ttft_logged:
                                        ttft_ms = (time.time() - request_start) * 1000
                                        log.debug("TTFT: %.0f ms (num_keep=%s, num_ctx=%s)",
                                                  ttft_ms,
                                                  request_data.get("options", {}).get("num_keep", "?"),
                                                  request_data.get("options", {}).get("num_ctx", "?"))
                                        ttft_logged = True
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

    async def generate_tokens(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        context: Optional[str] = None,
        conversation_history: Optional[List[ConversationTurn]] = None,
    ):
        """
        Async generator that yields tokens one-by-one as Ollama streams them.
        Use for low-latency voice streaming — caller can detect sentence boundaries
        and speak each sentence before the full response is ready.
        """
        model = model or self.current_model
        messages, num_keep = self._build_messages(prompt, context, system_prompt, conversation_history)
        request_data = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"num_keep": num_keep, "num_ctx": OLLAMA_NUM_CTX},
        }
        try:
            async with self._get_session() as session:
                async with session.post(
                    f"{self.base_url}/api/chat", json=request_data
                ) as response:
                    if response.status != 200:
                        log.error("generate_tokens HTTP error: %s", response.status)
                        return
                    async for line in response.content:
                        line = line.decode("utf-8").strip()
                        if line:
                            try:
                                data = json.loads(line)
                                if "message" in data and "content" in data["message"]:
                                    yield data["message"]["content"]
                                if data.get("done", False):
                                    break
                            except json.JSONDecodeError:
                                continue
        except Exception as exc:
            log.error("generate_tokens error: %s", exc)

    async def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None,
                   stream: bool = True, keep_alive: Optional[str] = None) -> Optional[str]:
        """Direct chat interface — pass your own messages array.

        keep_alive controls how long ollama holds the model in VRAM after the
        call. This path used to omit it entirely, so a one-off planning call on
        a big model squatted on the GPU for ollama's default window and starved
        the small model that serves chat and tool execution. Callers that borrow
        a heavy model for a single call should pass "0" to hand the VRAM back
        immediately.
        """
        model = model or self.current_model
        request_data = {
            "model": model, "messages": messages, "stream": stream,
            "keep_alive": keep_alive if keep_alive is not None else OLLAMA_KEEP_ALIVE,
        }
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
