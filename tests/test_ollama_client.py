#!/usr/bin/env python3
"""
Unit tests for LLM clients (ollama_client)
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from llm.ollama_client import OllamaClient


@pytest.fixture
def mock_ollama_client():
    """Create a mock ollama client"""
    client = OllamaClient(base_url="http://localhost:11434")
    return client


@pytest.mark.unit
def test_ollama_client_initialization(mock_ollama_client):
    """Test ollama client initialization"""
    assert mock_ollama_client.base_url == "http://localhost:11434"
    assert mock_ollama_client.session is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_with_mock():
    """Test generate method with mocked response"""
    client = OllamaClient()
    
    # Mock the session
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value='{"response": "Mocked response"}')
    
    mock_session = MagicMock()
    mock_session.post = AsyncMock(return_value=mock_response)
    
    client.session = mock_session
    
    # Test generate
    with patch.object(client, '_ensure_session', new_callable=AsyncMock):
        result = await client.generate("Test prompt", stream=False)
        
        # Verify session.post was called
        assert mock_session.post.called


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_models_with_mock():
    """Test list_models method with mocked response"""
    client = OllamaClient()
    
    mock_models = {
        "models": [
            {"name": "llama3.1:8b", "size": 4661224384},
            {"name": "codellama:7b", "size": 3826793677}
        ]
    }
    
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=mock_models)
    
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    
    client.session = mock_session
    
    with patch.object(client, '_ensure_session', new_callable=AsyncMock):
        models = await client.list_models()
        
        assert len(models) == 2
        assert models[0]['name'] == "llama3.1:8b"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_model_with_mock():
    """Test check_model method with mocked response"""
    client = OllamaClient()
    
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"status": "success"})
    
    mock_session = MagicMock()
    mock_session.post = AsyncMock(return_value=mock_response)
    
    client.session = mock_session
    
    with patch.object(client, '_ensure_session', new_callable=AsyncMock):
        result = await client.check_model("llama3.1")
        assert result is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cleanup():
    """Test cleanup method"""
    client = OllamaClient()
    
    # Create a mock session
    mock_session = AsyncMock()
    client.session = mock_session
    
    await client.cleanup()
    
    # Verify session.close was called
    mock_session.close.assert_called_once()
    assert client.session is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_model():
    """Test setting the current model"""
    client = OllamaClient()
    
    new_model = "llama3.1:8b"
    client.set_model(new_model)
    
    assert client.current_model == new_model


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_handling_generate():
    """Test error handling in generate method"""
    client = OllamaClient()
    
    # Mock session that raises an exception
    mock_session = MagicMock()
    mock_session.post = AsyncMock(side_effect=Exception("Connection error"))
    
    client.session = mock_session
    
    with patch.object(client, '_ensure_session', new_callable=AsyncMock):
        result = await client.generate("Test", stream=False)
        
        # Should return empty string or handle error gracefully
        assert result is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_handling_list_models():
    """Test error handling in list_models method"""
    client = OllamaClient()
    
    # Mock session that raises an exception
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=Exception("Connection error"))
    
    client.session = mock_session
    
    with patch.object(client, '_ensure_session', new_callable=AsyncMock):
        models = await client.list_models()
        
        # Should return empty list on error
        assert models == []
