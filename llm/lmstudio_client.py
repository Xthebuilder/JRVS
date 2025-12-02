"""LM Studio client with OpenAI-compatible API support"""
import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Optional

from config import LMSTUDIO_BASE_URL, LMSTUDIO_DEFAULT_MODEL, TIMEOUTS


class LMStudioClient:
    """Client for LM Studio's OpenAI-compatible API"""
    
    def __init__(self, base_url: str = LMSTUDIO_BASE_URL):
        self.base_url = base_url.rstrip('/')
        self.current_model = LMSTUDIO_DEFAULT_MODEL
        self.session = None
        self._available_models = []
        self._model_info = {}
        self._last_model_check = 0
        self._check_interval = 60  # Check for new models every minute

    async def _get_session(self):
        """Get or create HTTP session with timeout"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=TIMEOUTS["ollama_response"])
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def _check_connection(self) -> bool:
        """Check if LM Studio is running and accessible"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/models") as response:
                return response.status == 200
        except Exception:
            return False

    async def discover_models(self) -> List[str]:
        """Discover available LM Studio models via OpenAI-compatible API"""
        current_time = time.time()
        
        # Only check periodically to avoid overwhelming LM Studio
        if current_time - self._last_model_check < self._check_interval:
            return self._available_models
        
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/models") as response:
                if response.status == 200:
                    data = await response.json()
                    models = [model['id'] for model in data.get('data', [])]
                    
                    # Update model info
                    for model_data in data.get('data', []):
                        model_id = model_data['id']
                        self._model_info[model_id] = {
                            'id': model_id,
                            'object': model_data.get('object', 'model'),
                            'owned_by': model_data.get('owned_by', 'lmstudio'),
                        }
                    
                    self._available_models = models
                    self._last_model_check = current_time
                    
                    # Set default model if available and none is set
                    if models and not self.current_model:
                        self.current_model = models[0]
                    
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
            # Look for partial matches
            matches = [model for model in available_models if model_name in model]
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
        """Generate response from LM Studio using OpenAI-compatible API"""
        model = model or self.current_model
        
        # Check connection first
        if not await self._check_connection():
            print("LM Studio is not running or not accessible")
            return None
        
        # Build messages for chat completion
        messages = self._build_messages(prompt, context, system_prompt)
        
        try:
            if stream:
                response = await self._generate_streaming(messages, model)
            else:
                response = await self._generate_non_streaming(messages, model)
            
            return response
            
        except asyncio.TimeoutError:
            print(f"Timeout after {TIMEOUTS['ollama_response']}s")
            return None
        except Exception as e:
            print(f"Error generating response: {e}")
            return None

    def _build_messages(self, user_prompt: str, context: Optional[str] = None,
                       system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
        """Build messages array for chat completion"""
        messages = []
        
        # Add system prompt if provided
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        # Build user message with context
        user_content = ""
        
        # Add context if available (this is the RAG magic!)
        if context and context.strip():
            user_content = f"Context Information:\n{context}\n\nBased on the above context and your knowledge, please answer the following question:\n\n"
        
        user_content += f"Question: {user_prompt}"
        messages.append({"role": "user", "content": user_content})
        
        return messages

    async def _generate_streaming(self, messages: List[Dict[str, str]], model: str) -> Optional[str]:
        """Generate streaming response using chat completions endpoint"""
        request_data = {
            "model": model,
            "messages": messages,
            "stream": True
        }
        
        full_response = ""
        
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/chat/completions",
                json=request_data
            ) as response:
                
                if response.status != 200:
                    print(f"HTTP error: {response.status}")
                    return None
                
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    if line.startswith('data: '):
                        line = line[6:]  # Remove 'data: ' prefix
                        if line == '[DONE]':
                            print()  # New line after response
                            break
                        try:
                            data = json.loads(line)
                            if 'choices' in data and len(data['choices']) > 0:
                                delta = data['choices'][0].get('delta', {})
                                if 'content' in delta:
                                    chunk = delta['content']
                                    full_response += chunk
                                    print(chunk, end='', flush=True)
                        except json.JSONDecodeError:
                            continue
            
            return full_response if full_response.strip() else None
            
        except Exception as e:
            print(f"Streaming error: {e}")
            return None

    async def _generate_non_streaming(self, messages: List[Dict[str, str]], model: str) -> Optional[str]:
        """Generate non-streaming response using chat completions endpoint"""
        request_data = {
            "model": model,
            "messages": messages,
            "stream": False
        }
        
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/chat/completions",
                json=request_data
            ) as response:
                
                if response.status == 200:
                    data = await response.json()
                    if 'choices' in data and len(data['choices']) > 0:
                        return data['choices'][0].get('message', {}).get('content', '').strip()
                    return None
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
        
        try:
            if stream:
                return await self._generate_streaming(messages, model)
            else:
                return await self._generate_non_streaming(messages, model)
                
        except Exception as e:
            print(f"Chat error: {e}")
            return None

    async def get_model_info(self, model_name: Optional[str] = None) -> Dict:
        """Get information about a model"""
        model_name = model_name or self.current_model
        
        if model_name in self._model_info:
            return self._model_info[model_name]
        
        # Try to get fresh info
        await self.discover_models()
        return self._model_info.get(model_name, {})

    async def list_models(self) -> List[Dict]:
        """List all available models with info"""
        models = await self.discover_models()
        
        model_list = []
        for model in models:
            info = self._model_info.get(model, {})
            model_list.append({
                'name': model,
                'current': model == self.current_model,
                'size': 0,  # LM Studio API doesn't provide size
                'modified_at': '',
                'details': info
            })
        
        return model_list

    async def set_base_url(self, base_url: str):
        """Update the base URL and reset session"""
        self.base_url = base_url.rstrip('/')
        # Close existing session if it exists
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None
        # Reset model cache
        self._available_models = []
        self._model_info = {}
        self._last_model_check = 0

    async def cleanup(self):
        """Clean up resources"""
        if self.session and not self.session.closed:
            await self.session.close()


# Global LM Studio client instance
lmstudio_client = LMStudioClient()
