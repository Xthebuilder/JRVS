"""Ollama client with model switching and robust error handling"""
import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Optional, AsyncGenerator, Tuple
from contextlib import asynccontextmanager

from config import OLLAMA_BASE_URL, DEFAULT_MODEL, TIMEOUTS
from core.database import db

class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip('/')
        self.current_model = DEFAULT_MODEL
        self.session = None
        self._available_models = []
        self._model_info = {}
        self._last_model_check = 0
        self._check_interval = 60  # Check for new models every minute

    @asynccontextmanager
    async def _get_session(self):
        """Get or create HTTP session with timeout"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=TIMEOUTS["ollama_response"])
            self.session = aiohttp.ClientSession(timeout=timeout)
        
        try:
            yield self.session
        except Exception as e:
            if self.session and not self.session.closed:
                await self.session.close()
            self.session = None
            raise e

    async def _check_ollama_connection(self) -> bool:
        """Check if Ollama is running and accessible"""
        try:
            async with self._get_session() as session:
                async with session.get(f"{self.base_url}/api/tags") as response:
                    return response.status == 200
        except Exception:
            return False

    async def discover_models(self) -> List[str]:
        """Discover available Ollama models"""
        current_time = time.time()
        
        # Only check periodically to avoid overwhelming Ollama
        if current_time - self._last_model_check < self._check_interval:
            return self._available_models
        
        try:
            async with self._get_session() as session:
                async with session.get(f"{self.base_url}/api/tags") as response:
                    if response.status == 200:
                        data = await response.json()
                        models = [model['name'] for model in data.get('models', [])]

                        # Update model info
                        for model_data in data.get('models', []):
                            model_name = model_data['name']
                            self._model_info[model_name] = {
                                'size': model_data.get('size', 0),
                                'modified_at': model_data.get('modified_at', ''),
                                'details': model_data.get('details', {})
                            }
                        
                        self._available_models = models
                        self._last_model_check = current_time
                        
                        # Update database with available models
                        for model in models:
                            # This would need to be implemented properly in database.py
                            # For now, we'll skip database updates during model discovery
                            pass
                        
                        return models
                    else:
                        print(f"Failed to get models: HTTP {response.status}")
                        return self._available_models
        
        except Exception as e:
            print(f"Error discovering models: {e}")
            return self._available_models

    async def switch_model(self, model_name: str) -> bool:
        """Switch to a different model"""
        # Discover models if not done recently
        available_models = await self.discover_models()

        # Check exact match first
        if model_name in available_models:
            target_model = model_name
        else:
            # Look for partial matches (e.g., "deepseek-r1" matches "deepseek-r1:latest")
            matches = [model for model in available_models if model.startswith(model_name)]
            if len(matches) == 1:
                target_model = matches[0]
            elif len(matches) > 1:
                print(f"Multiple models match '{model_name}': {matches}")
                return False
            else:
                print(f"Model '{model_name}' not available. Available models: {available_models}")
                return False
        
        # Test model by sending a simple prompt
        test_response = await self.generate(
            prompt="Hello",
            model=target_model,
            stream=False
        )

        if test_response:
            old_model = self.current_model
            self.current_model = target_model
            print(f"Switched from '{old_model}' to '{target_model}'")
            return True
        else:
            print(f"Failed to switch to model '{target_model}' - model not responding")
            return False

    async def generate(self, prompt: str, model: Optional[str] = None, 
                      stream: bool = True, system_prompt: Optional[str] = None,
                      context: Optional[str] = None) -> Optional[str]:
        """Generate response from Ollama"""
        model = model or self.current_model
        start_time = time.time()
        
        # Check connection first
        if not await self._check_ollama_connection():
            print("Ollama is not running or not accessible")
            return None
        
        # Build the full prompt with context injection
        full_prompt = self._build_prompt(prompt, context, system_prompt)
        
        try:
            if stream:
                response = await self._generate_streaming(full_prompt, model)
            else:
                response = await self._generate_non_streaming(full_prompt, model)
            
            # Record model usage statistics
            response_time = time.time() - start_time
            await db.update_model_stats(model, response_time)
            
            return response
            
        except asyncio.TimeoutError:
            print(f"Timeout after {TIMEOUTS['ollama_response']}s")
            return None
        except Exception as e:
            print(f"Error generating response: {e}")
            return None

    def _build_prompt(self, user_prompt: str, context: Optional[str] = None, 
                     system_prompt: Optional[str] = None) -> str:
        """Build enhanced prompt with context injection"""
        parts = []
        
        # Add system prompt if provided
        if system_prompt:
            parts.append(f"System: {system_prompt}")
        
        # Add context if available (this is the RAG magic!)
        if context and context.strip():
            parts.append("Context Information:")
            parts.append(context)
            parts.append("\nBased on the above context and your knowledge, please answer the following question:")
        
        # Add user prompt
        parts.append(f"Question: {user_prompt}")
        
        return "\n\n".join(parts)

    async def _generate_streaming(self, prompt: str, model: str) -> Optional[str]:
        """Generate streaming response"""
        request_data = {
            "model": model,
            "prompt": prompt,
            "stream": True
        }
        
        full_response = ""
        
        try:
            async with self._get_session() as session:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=request_data
                ) as response:
                    
                    if response.status != 200:
                        print(f"HTTP error: {response.status}")
                        return None
                    
                    async for line in response.content:
                        line = line.decode('utf-8').strip()
                        if line:
                            try:
                                data = json.loads(line)
                                if 'response' in data:
                                    chunk = data['response']
                                    full_response += chunk
                                    print(chunk, end='', flush=True)
                                
                                if data.get('done', False):
                                    print()  # New line after response
                                    break
                                    
                            except json.JSONDecodeError:
                                continue
            
            return full_response if full_response.strip() else None
            
        except Exception as e:
            print(f"Streaming error: {e}")
            return None

    async def _generate_non_streaming(self, prompt: str, model: str) -> Optional[str]:
        """Generate non-streaming response"""
        request_data = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }
        
        try:
            async with self._get_session() as session:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=request_data
                ) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        return data.get('response', '').strip()
                    else:
                        print(f"HTTP error: {response.status}")
                        return None
                        
        except Exception as e:
            print(f"Generation error: {e}")
            return None

    async def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None,
                  stream: bool = True) -> Optional[str]:
        """Chat interface for conversation-style interactions"""
        model = model or self.current_model
        
        request_data = {
            "model": model,
            "messages": messages,
            "stream": stream
        }
        
        try:
            if stream:
                return await self._chat_streaming(request_data)
            else:
                return await self._chat_non_streaming(request_data)
                
        except Exception as e:
            print(f"Chat error: {e}")
            return None

    async def _chat_streaming(self, request_data: Dict) -> Optional[str]:
        """Streaming chat response"""
        full_response = ""
        
        try:
            async with self._get_session() as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=request_data
                ) as response:
                    
                    if response.status != 200:
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
            print(f"Chat streaming error: {e}")
            return None

    async def _chat_non_streaming(self, request_data: Dict) -> Optional[str]:
        """Non-streaming chat response"""
        try:
            async with self._get_session() as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=request_data
                ) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        return data.get('message', {}).get('content', '').strip()
                    else:
                        return None
                        
        except Exception as e:
            print(f"Chat non-streaming error: {e}")
            return None

    async def get_model_info(self, model_name: Optional[str] = None) -> Dict:
        """Get information about a model"""
        model_name = model_name or self.current_model
        
        if model_name in self._model_info:
            return self._model_info[model_name]
        
        # Try to get fresh info
        await self.discover_models()
        return self._model_info.get(model_name, {})

    async def list_models(self) -> List[Dict[str, any]]:
        """List all available models with info"""
        models = await self.discover_models()
        
        model_list = []
        for model in models:
            info = self._model_info.get(model, {})
            model_list.append({
                'name': model,
                'current': model == self.current_model,
                'size': info.get('size', 0),
                'modified_at': info.get('modified_at', ''),
                'details': info.get('details', {})
            })
        
        return model_list

    async def set_base_url(self, base_url: str):
        """Update the base URL and reset session"""
        self.base_url = base_url.rstrip('/')
        # Close existing session if it exists
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None

    async def cleanup(self):
        """Clean up resources"""
        if self.session and not self.session.closed:
            await self.session.close()

# Global Ollama client instance
ollama_client = OllamaClient()