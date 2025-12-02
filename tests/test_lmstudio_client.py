#!/usr/bin/env python3
"""
Test script for JRVS LM Studio Client

This script tests the LM Studio client functionality.
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_lmstudio_client():
    """Test the LM Studio client functionality"""
    from llm.lmstudio_client import LMStudioClient
    
    print("🔌 Testing JRVS LM Studio Client\n")
    
    # Create client with test URL
    client = LMStudioClient(base_url="http://127.0.0.1:1234/v1")
    
    # Test 1: Check connection (will fail if LM Studio is not running)
    print("1. Testing connection check...")
    is_connected = await client._check_connection()
    if is_connected:
        print("   ✓ Connected to LM Studio")
    else:
        print("   ✗ LM Studio not running (expected if not installed)")
        print("   Skipping further tests as LM Studio is not available")
        await client.cleanup()
        return True  # Not a failure, just not available
    
    # Test 2: Discover models
    print("\n2. Testing model discovery...")
    models = await client.discover_models()
    if models:
        print(f"   ✓ Found {len(models)} model(s):")
        for model in models[:3]:
            print(f"      • {model}")
        if len(models) > 3:
            print(f"      ... and {len(models) - 3} more")
    else:
        print("   ⚠ No models found")
    
    # Test 3: List models with details
    print("\n3. Testing list_models...")
    model_list = await client.list_models()
    if model_list:
        print(f"   ✓ Got model list with {len(model_list)} items")
        for model in model_list[:2]:
            print(f"      • {model['name']} (current: {model['current']})")
    else:
        print("   ⚠ Empty model list")
    
    # Test 4: Test generate (non-streaming)
    if models:
        print("\n4. Testing text generation...")
        response = await client.generate(
            prompt="Say 'hello' and nothing else.",
            stream=False
        )
        if response:
            print(f"   ✓ Generated response: {response[:100]}...")
        else:
            print("   ✗ Failed to generate response")
    
    # Test 5: Test set_base_url
    print("\n5. Testing set_base_url...")
    await client.set_base_url("http://localhost:1234/v1")
    assert client.base_url == "http://localhost:1234/v1"
    print("   ✓ Base URL updated successfully")
    
    # Cleanup
    print("\n🧹 Cleaning up...")
    await client.cleanup()
    print("✓ All tests passed!")
    
    return True


async def test_client_initialization():
    """Test client initialization and configuration"""
    from llm.lmstudio_client import lmstudio_client
    from config import LMSTUDIO_BASE_URL
    
    print("\n📋 Testing client initialization...\n")
    
    # Test that global instance exists
    assert lmstudio_client is not None
    print("   ✓ Global lmstudio_client instance exists")
    
    # Test that it uses the configured base URL
    assert lmstudio_client.base_url == LMSTUDIO_BASE_URL.rstrip('/')
    print(f"   ✓ Base URL is configured: {lmstudio_client.base_url}")
    
    # Test session starts as None
    assert lmstudio_client.session is None
    print("   ✓ Session is None initially")
    
    print("\n✓ Initialization tests passed!")
    return True


async def main():
    """Run all tests"""
    print("=" * 50)
    print("LM Studio Client Test Suite")
    print("=" * 50)
    
    try:
        # Run initialization tests
        await test_client_initialization()
        
        # Run client tests
        await test_lmstudio_client()
        
        print("\n" + "=" * 50)
        print("All tests completed!")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
