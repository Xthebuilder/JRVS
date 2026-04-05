"""
Ollama REST API client for JRVS.

Provides a thin wrapper around Ollama's local HTTP API for:
- chat completions (streaming and non-streaming)
- model availability checks
- embedding generation via Ollama (fallback when sentence-transformers unavailable)
"""

from __future__ import annotations

import json
import time
from typing import Any, Generator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from jrvs.config import Config
from jrvs.utils.logger import setup_logger, log_api_call, log_model_interaction, log_error

# Initialize logger
logger = setup_logger('jrvs.ollama')


class OllamaClient:
    """Communicate with a local Ollama instance."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = (base_url or Config.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or Config.OLLAMA_MODEL
        self._last_failure_time = 0
        self._failure_count = 0
        self._session = self._create_session()
        logger.info("Ollama client initialized", extra={
            'base_url': self.base_url,
            'default_model': self.model
        })
        
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry strategy."""
        session = requests.Session()
        retry_strategy = Retry(
            total=Config.OLLAMA_RETRY_COUNT,
            backoff_factor=Config.OLLAMA_RETRY_DELAY,
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
        
    def _is_circuit_open(self) -> bool:
        """Simple circuit breaker to avoid hammering failed service."""
        if self._failure_count < 3:
            return False
        time_since_failure = time.time() - self._last_failure_time
        return time_since_failure < (Config.OLLAMA_RETRY_DELAY * 2**self._failure_count)
        
    def _record_success(self):
        """Reset failure tracking on successful request."""
        self._failure_count = 0
        
    def _record_failure(self):
        """Track failures for circuit breaker."""
        self._failure_count += 1
        self._last_failure_time = time.time()

    # ── health ──────────────────────────────────────────────────────────
    def is_available(self) -> bool:
        """Return True if the Ollama server is reachable."""
        if self._is_circuit_open():
            logger.info("Circuit breaker open, skipping health check", extra={
                'failure_count': self._failure_count
            })
            return False
            
        start_time = time.time()
        try:
            r = self._session.get(f"{self.base_url}/api/tags", timeout=Config.OLLAMA_HEALTH_TIMEOUT)
            duration = time.time() - start_time
            available = r.status_code == 200
            log_api_call('ollama', 'GET', f"{self.base_url}/api/tags", 
                        response_status=r.status_code, duration=duration)
            
            if available:
                self._record_success()
                logger.info(f"Ollama availability check: {available}", extra={
                    'available': available, 'duration': duration
                })
            else:
                self._record_failure()
                logger.warning(f"Ollama returned status {r.status_code}", extra={
                    'status_code': r.status_code, 'duration': duration
                })
            return available
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            duration = time.time() - start_time
            self._record_failure() 
            log_api_call('ollama', 'GET', f"{self.base_url}/api/tags", 
                        duration=duration, error=str(e))
            logger.warning(f"Ollama not available: {e}", extra={
                'duration': duration, 'failure_count': self._failure_count
            })
            return False
        except Exception as e:
            duration = time.time() - start_time
            self._record_failure()
            log_error(e, {'operation': 'health_check', 'duration': duration})
            return False

    def list_models(self) -> list[str]:
        """Return model names available in the local Ollama instance."""
        if self._is_circuit_open():
            logger.info("Circuit breaker open, returning cached empty models list")
            return []
            
        start_time = time.time()
        try:
            r = self._session.get(f"{self.base_url}/api/tags", timeout=Config.OLLAMA_HEALTH_TIMEOUT)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            duration = time.time() - start_time
            
            self._record_success()
            log_api_call('ollama', 'GET', f"{self.base_url}/api/tags", 
                        response_status=r.status_code, duration=duration)
            logger.info(f"Listed {len(models)} models", extra={
                'model_count': len(models), 'models': models, 'duration': duration
            })
            return models
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            duration = time.time() - start_time
            self._record_failure()
            logger.warning(f"Failed to list models: {e}", extra={
                'duration': duration, 'failure_count': self._failure_count
            })
            return []
        except Exception as e:
            duration = time.time() - start_time
            self._record_failure()
            log_error(e, {'operation': 'list_models', 'duration': duration})
            return []

    def has_model(self, name: str | None = None) -> bool:
        """Check whether a specific model is pulled locally."""
        name = name or self.model
        models = self.list_models()
        return any(name in m for m in models)

    # ── chat (non-streaming) ────────────────────────────────────────────
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        num_ctx: int | None = None,
        system: str | None = None,
    ) -> str:
        """Send a chat completion request and return the assistant reply.

        Parameters
        ----------
        messages : list of {"role": ..., "content": ...}
        temperature : override Config default
        num_ctx : context window size
        system : optional system prompt (prepended)
        """
        if self._is_circuit_open():
            raise RuntimeError(f"Ollama service temporarily unavailable (circuit breaker open, {self._failure_count} recent failures)")
            
        start_time = time.time()
        prompt_text = " ".join([msg.get('content', '') for msg in messages])
        
        if system:
            messages = [{"role": "system", "content": system}] + messages

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature or Config.OLLAMA_TEMPERATURE,
                "num_ctx": num_ctx or Config.OLLAMA_NUM_CTX,
            },
        }

        try:
            r = self._session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=Config.OLLAMA_CHAT_TIMEOUT,
            )
            r.raise_for_status()
            response = r.json()["message"]["content"]
            duration = time.time() - start_time
            
            self._record_success()
            
            log_api_call('ollama', 'POST', f"{self.base_url}/api/chat",
                        params={'model': self.model}, 
                        response_status=r.status_code,
                        response_size=len(response),
                        duration=duration)
            
            log_model_interaction(self.model, prompt_text, response, 
                                duration=duration, 
                                temperature=temperature or Config.OLLAMA_TEMPERATURE)
            
            logger.info("Chat completion successful", extra={
                'model': self.model,
                'prompt_length': len(prompt_text),
                'response_length': len(response),
                'duration': duration,
                'message_count': len(messages)
            })
            
            return response
            
        except requests.exceptions.Timeout as e:
            duration = time.time() - start_time
            self._record_failure()
            log_error(e, {
                'operation': 'chat_completion',
                'model': self.model,
                'duration': duration,
                'message_count': len(messages),
                'timeout': Config.OLLAMA_CHAT_TIMEOUT,
                'prompt_length': len(prompt_text)
            })
            raise RuntimeError(f"Ollama request timed out after {Config.OLLAMA_CHAT_TIMEOUT}s. Try a shorter prompt or restart Ollama.") from e
            
        except requests.exceptions.ConnectionError as e:
            duration = time.time() - start_time
            self._record_failure()
            log_error(e, {
                'operation': 'chat_completion',
                'model': self.model,
                'duration': duration,
                'message_count': len(messages)
            })
            raise RuntimeError(f"Cannot connect to Ollama at {self.base_url}. Is it running?") from e
            
        except Exception as e:
            duration = time.time() - start_time
            self._record_failure()
            log_error(e, {
                'operation': 'chat_completion',
                'model': self.model,
                'duration': duration,
                'message_count': len(messages)
            })
            raise

    # ── chat (streaming) ────────────────────────────────────────────────
    def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        num_ctx: int | None = None,
        system: str | None = None,
    ) -> Generator[str, None, None]:
        """Yield tokens as they arrive from Ollama."""
        if system:
            messages = [{"role": "system", "content": system}] + messages

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature or Config.OLLAMA_TEMPERATURE,
                "num_ctx": num_ctx or Config.OLLAMA_NUM_CTX,
            },
        }

        with requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            stream=True,
            timeout=120,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue

    # ── generate (single prompt, non-chat) ──────────────────────────────
    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Simple single-prompt completion."""
        return self.chat(
            [{"role": "user", "content": prompt}],
            **kwargs,
        )

    # ── embeddings via Ollama ───────────────────────────────────────────
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings through Ollama's embedding endpoint.

        Useful as a fallback when sentence-transformers is not installed.
        """
        payload = {
            "model": self.model,
            "input": texts,
        }
        r = requests.post(
            f"{self.base_url}/api/embed",
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json().get("embeddings", [])
