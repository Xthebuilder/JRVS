"""
Unit tests for llm.ollama_client module
Tests Ollama client functionality, model switching, and error handling
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
import aiohttp
import json

from llm.ollama_client import OllamaClient


class TestOllamaClient:
    """Test suite for OllamaClient class"""
    
    @pytest.fixture
    def client(self):
        """Create an Ollama client for testing"""
        return OllamaClient(base_url="http://localhost:11434")
    
    @pytest.mark.asyncio
    async def test_initialization(self, client):
        """Test client initialization"""
        assert client.base_url == "http://localhost:11434"
        assert client.current_model is not None
        assert client.session is None
        assert isinstance(client._available_models, list)
    
    @pytest.mark.asyncio
    async def test_check_ollama_connection_success(self, client):
        """Test successful Ollama connection check"""
        with patch.object(client, '_get_session') as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.__aenter__.return_value = mock_response
            mock_response.__aexit__.return_value = None
            
            mock_http_session = AsyncMock()
            mock_http_session.get.return_value = mock_response
            mock_http_session.__aenter__.return_value = mock_http_session
            mock_http_session.__aexit__.return_value = None
            
            mock_session.return_value = mock_http_session
            
            result = await client._check_ollama_connection()
            
            assert result is True
    
    @pytest.mark.asyncio
    async def test_check_ollama_connection_failure(self, client):
        """Test failed Ollama connection check"""
        with patch.object(client, '_get_session') as mock_session:
            mock_session.side_effect = Exception("Connection failed")
            
            result = await client._check_ollama_connection()
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_discover_models_success(self, client):
        """Test successful model discovery"""
        mock_models_data = {
            'models': [
                {'name': 'llama3.1', 'size': 1000000, 'modified_at': '2025-01-01', 'details': {}},
                {'name': 'codellama', 'size': 2000000, 'modified_at': '2025-01-02', 'details': {}}
            ]
        }
        
        with patch.object(client, '_get_session') as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = mock_models_data
            mock_response.__aenter__.return_value = mock_response
            mock_response.__aexit__.return_value = None
            
            mock_http_session = AsyncMock()
            mock_http_session.get.return_value = mock_response
            mock_http_session.__aenter__.return_value = mock_http_session
            mock_http_session.__aexit__.return_value = None
            
            mock_session.return_value = mock_http_session
            
            models = await client.discover_models()
            
            assert len(models) == 2
            assert 'llama3.1' in models
            assert 'codellama' in models
            assert client._available_models == models
    
    @pytest.mark.asyncio
    async def test_discover_models_caching(self, client):
        """Test that model discovery uses caching"""
        # Set last check time to recent
        import time
        client._last_model_check = time.time()
        client._available_models = ['cached_model']
        
        # Should return cached models without making a request
        models = await client.discover_models()
        
        assert models == ['cached_model']
    
    @pytest.mark.asyncio
    async def test_build_prompt_with_context(self, client):
        """Test prompt building with context"""
        user_prompt = "What is Python?"
        context = "Python is a programming language"
        system_prompt = "You are a helpful assistant"
        
        full_prompt = client._build_prompt(user_prompt, context, system_prompt)
        
        assert "System:" in full_prompt
        assert "Context Information:" in full_prompt
        assert "Python is a programming language" in full_prompt
        assert "What is Python?" in full_prompt
    
    @pytest.mark.asyncio
    async def test_build_prompt_without_context(self, client):
        """Test prompt building without context"""
        user_prompt = "Hello!"
        
        full_prompt = client._build_prompt(user_prompt)
        
        assert "Hello!" in full_prompt
        assert "Context Information:" not in full_prompt
    
    @pytest.mark.asyncio
    async def test_build_prompt_with_empty_context(self, client):
        """Test prompt building with empty context"""
        user_prompt = "Test"
        context = "   "  # Whitespace only
        
        full_prompt = client._build_prompt(user_prompt, context)
        
        assert "Context Information:" not in full_prompt
    
    @pytest.mark.asyncio
    async def test_generate_connection_failure(self, client):
        """Test generate when Ollama is not connected"""
        with patch.object(client, '_check_ollama_connection', return_value=False):
            result = await client.generate("Test prompt")
            
            assert result is None
    
    @pytest.mark.asyncio
    async def test_set_base_url(self, client):
        """Test setting a new base URL"""
        new_url = "http://192.168.1.100:11434/"
        
        await client.set_base_url(new_url)
        
        assert client.base_url == "http://192.168.1.100:11434"
        assert client.session is None  # Session should be reset
    
    @pytest.mark.asyncio
    async def test_cleanup(self, client):
        """Test cleanup closes the session"""
        # Create a mock session
        client.session = AsyncMock()
        client.session.closed = False
        
        await client.cleanup()
        
        client.session.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_no_session(self, client):
        """Test cleanup when no session exists"""
        client.session = None
        
        # Should not raise an error
        await client.cleanup()
    
    @pytest.mark.asyncio
    async def test_cleanup_already_closed_session(self, client):
        """Test cleanup when session is already closed"""
        client.session = AsyncMock()
        client.session.closed = True
        
        await client.cleanup()
        
        # close() should not be called on an already closed session
        client.session.close.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_model_info_cached(self, client):
        """Test getting model info from cache"""
        client._model_info['test_model'] = {
            'size': 1000000,
            'modified_at': '2025-01-01'
        }
        
        info = await client.get_model_info('test_model')
        
        assert info['size'] == 1000000
    
    @pytest.mark.asyncio
    async def test_get_model_info_not_cached(self, client):
        """Test getting model info when not cached"""
        with patch.object(client, 'discover_models', return_value=[]):
            info = await client.get_model_info('nonexistent_model')
            
            assert info == {}
    
    @pytest.mark.asyncio
    async def test_list_models_with_current_marker(self, client):
        """Test list_models marks the current model"""
        client.current_model = 'llama3.1'
        client._available_models = ['llama3.1', 'codellama']
        client._model_info = {
            'llama3.1': {'size': 1000000, 'modified_at': '2025-01-01', 'details': {}},
            'codellama': {'size': 2000000, 'modified_at': '2025-01-02', 'details': {}}
        }
        
        with patch.object(client, 'discover_models', return_value=client._available_models):
            model_list = await client.list_models()
            
            assert len(model_list) == 2
            
            llama_model = next(m for m in model_list if m['name'] == 'llama3.1')
            assert llama_model['current'] is True
            
            codellama_model = next(m for m in model_list if m['name'] == 'codellama')
            assert codellama_model['current'] is False
    
    @pytest.mark.asyncio
    async def test_switch_model_exact_match(self, client):
        """Test switching to a model with exact name match"""
        client._available_models = ['llama3.1', 'codellama']
        
        with patch.object(client, 'discover_models', return_value=client._available_models):
            with patch.object(client, 'generate', return_value="Hello"):
                result = await client.switch_model('codellama')
                
                assert result is True
                assert client.current_model == 'codellama'
    
    @pytest.mark.asyncio
    async def test_switch_model_partial_match(self, client):
        """Test switching to a model with partial name match"""
        client._available_models = ['llama3.1:latest']
        
        with patch.object(client, 'discover_models', return_value=client._available_models):
            with patch.object(client, 'generate', return_value="Hello"):
                result = await client.switch_model('llama3.1')
                
                assert result is True
                assert client.current_model == 'llama3.1:latest'
    
    @pytest.mark.asyncio
    async def test_switch_model_not_found(self, client):
        """Test switching to a non-existent model"""
        client._available_models = ['llama3.1']
        
        with patch.object(client, 'discover_models', return_value=client._available_models):
            result = await client.switch_model('nonexistent_model')
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_switch_model_multiple_matches(self, client):
        """Test switching when multiple models match"""
        client._available_models = ['llama3.1:7b', 'llama3.1:13b']
        
        with patch.object(client, 'discover_models', return_value=client._available_models):
            result = await client.switch_model('llama3.1')
            
            assert result is False  # Should fail with multiple matches
    
    @pytest.mark.asyncio
    async def test_switch_model_test_fails(self, client):
        """Test switching when test generation fails"""
        client._available_models = ['test_model']
        
        with patch.object(client, 'discover_models', return_value=client._available_models):
            with patch.object(client, 'generate', return_value=None):  # Test fails
                result = await client.switch_model('test_model')
                
                assert result is False


class TestGlobalOllamaInstance:
    """Test the global ollama_client instance"""
    
    def test_global_instance_exists(self):
        """Test that global ollama_client instance exists"""
        from llm.ollama_client import ollama_client
        
        assert ollama_client is not None
        assert isinstance(ollama_client, OllamaClient)
