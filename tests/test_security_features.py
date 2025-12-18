#!/usr/bin/env python3
"""
Test suite to verify security hardening implementation.
Tests all 9 security fixes from PR #24.
"""

import sys
import json
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_security_error_class():
    """Test 1.1: SecurityError exception class exists"""
    from mcp_gateway.coding_agent import SecurityError
    
    try:
        raise SecurityError("Test error")
    except SecurityError as e:
        assert str(e) == "Test error"
        print("✓ Test 1.1: SecurityError class works correctly")
        return True
    return False


def test_safe_executor_class():
    """Test 1.2: SafeExecutor class with resource limits"""
    from mcp_gateway.coding_agent import SafeExecutor
    
    # Verify attributes
    assert SafeExecutor.MAX_CPU_TIME == 30
    assert SafeExecutor.MAX_MEMORY == 256 * 1024 * 1024
    assert SafeExecutor.MAX_FILE_SIZE == 10 * 1024 * 1024
    assert SafeExecutor.MAX_PROCESSES == 0
    
    # Verify method exists
    assert hasattr(SafeExecutor, 'set_resource_limits')
    assert callable(SafeExecutor.set_resource_limits)
    
    print("✓ Test 1.2: SafeExecutor class has correct resource limits")
    return True


def test_path_validation():
    """Test 2: Path traversal protection"""
    from mcp_gateway.coding_agent import JARCORE, SecurityError
    
    # Create JARCORE instance with temp workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        jarcore = JARCORE(workspace_root=tmpdir)
        
        # Test 2.1: Valid path within workspace
        valid_path = "test.py"
        try:
            result = jarcore._validate_path(valid_path)
            assert result.is_relative_to(Path(tmpdir))
            print("✓ Test 2.1: Valid path accepted")
        except SecurityError:
            print("✗ Test 2.1: Valid path rejected incorrectly")
            return False
        
        # Test 2.2: Path traversal attempt
        traversal_path = "../../../etc/passwd"
        try:
            jarcore._validate_path(traversal_path)
            print("✗ Test 2.2: Path traversal not blocked")
            return False
        except SecurityError as e:
            assert "Path traversal detected" in str(e)
            print("✓ Test 2.2: Path traversal blocked")
        
        # Test 2.3: Sensitive file blocking
        sensitive_files = ['.env', '.git/config', 'credentials.json']
        for sensitive in sensitive_files:
            try:
                jarcore._validate_path(sensitive)
                print(f"✗ Test 2.3: Sensitive file {sensitive} not blocked")
                return False
            except SecurityError as e:
                assert "sensitive file blocked" in str(e).lower()
        print("✓ Test 2.3: Sensitive files blocked")
    
    return True


def test_jarcore_workspace_config():
    """Test 3: Configurable workspace (no hardcoded paths)"""
    from mcp_gateway.coding_agent import JARCORE
    from config import JARCORE_WORKSPACE
    
    # Test 3.1: Default workspace from config
    jarcore1 = JARCORE()
    assert jarcore1.workspace_root == JARCORE_WORKSPACE
    print("✓ Test 3.1: Default workspace from JARCORE_WORKSPACE config")
    
    # Test 3.2: Custom workspace
    custom_workspace = "/tmp/custom_workspace"
    jarcore2 = JARCORE(workspace_root=custom_workspace)
    assert str(jarcore2.workspace_root) == custom_workspace
    print("✓ Test 3.2: Custom workspace accepted")
    
    return True


def test_json_extraction():
    """Test 4: Robust JSON extraction"""
    from mcp_gateway.coding_agent import JARCORE
    
    jarcore = JARCORE()
    
    # Test 4.1: Direct JSON
    direct_json = '{"key": "value", "nested": {"data": 123}}'
    result, error = jarcore._extract_json(direct_json)
    assert result == {"key": "value", "nested": {"data": 123}}
    assert error is None
    print("✓ Test 4.1: Direct JSON parsing")
    
    # Test 4.2: JSON in code block
    code_block = '''Here is the response:
```json
{"status": "success", "count": 42}
```
Hope this helps!'''
    result, error = jarcore._extract_json(code_block)
    assert result == {"status": "success", "count": 42}
    assert error is None
    print("✓ Test 4.2: JSON extraction from code block")
    
    # Test 4.3: Nested JSON with surrounding text
    nested_text = 'Some text before {"outer": {"inner": [1, 2, 3]}} some text after'
    result, error = jarcore._extract_json(nested_text)
    assert result == {"outer": {"inner": [1, 2, 3]}}
    assert error is None
    print("✓ Test 4.3: Nested JSON with bracket-depth matching")
    
    # Test 4.4: Invalid JSON
    invalid_json = "This is not JSON at all"
    result, error = jarcore._extract_json(invalid_json)
    assert result is None
    assert error is not None
    print("✓ Test 4.4: Invalid JSON returns error")
    
    return True


def test_bounded_edit_history():
    """Test 9: Bounded edit history with deque"""
    from mcp_gateway.coding_agent import JARCORE
    
    # Test with custom max_history
    jarcore = JARCORE(max_history=5)
    assert jarcore.edit_history.maxlen == 5
    print("✓ Test 9.1: Custom max_history respected")
    
    # Test default max_history
    jarcore_default = JARCORE()
    assert jarcore_default.edit_history.maxlen == 1000
    print("✓ Test 9.2: Default max_history is 1000")
    
    return True


def test_lazy_loader_race_condition():
    """Test 5: Race condition fix in lazy loader"""
    from core.lazy_loader import LazyLoader
    import asyncio
    
    # Verify asyncio.Event is used
    loader = LazyLoader(lambda: "test_resource")
    assert hasattr(loader, '_load_complete')
    assert isinstance(loader._load_complete, asyncio.Event)
    print("✓ Test 5: LazyLoader uses asyncio.Event for synchronization")
    
    return True


def test_pydantic_models():
    """Test 8: Request validation with Pydantic models"""
    # Import directly from web_server
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    
    # Just verify the models can be imported and have validators
    with open('web_server.py', 'r') as f:
        web_server_content = f.read()
    
    assert 'class ChatRequest(BaseModel):' in web_server_content
    assert 'class ScrapeRequest(BaseModel):' in web_server_content
    assert 'class CodeExecuteRequest(BaseModel):' in web_server_content
    assert '@validator' in web_server_content
    print("✓ Test 8: Pydantic validation models defined")
    
    return True


def test_rate_limiting():
    """Test 7: Rate limiting with slowapi"""
    with open('web_server.py', 'r') as f:
        web_server_content = f.read()
    
    assert 'from slowapi import Limiter' in web_server_content
    assert 'limiter = Limiter' in web_server_content
    print("✓ Test 7: Rate limiting with slowapi configured")
    
    with open('requirements.txt', 'r') as f:
        requirements = f.read()
    
    assert 'slowapi' in requirements
    print("✓ Test 7: slowapi in requirements.txt")
    
    return True


def test_session_management():
    """Test 6: Session management in ollama_client"""
    with open('llm/ollama_client.py', 'r') as f:
        ollama_content = f.read()
    
    assert '@asynccontextmanager' in ollama_content
    assert 'async def _get_session(self):' in ollama_content
    print("✓ Test 6: Async session management with context manager")
    
    return True


def main():
    """Run all security tests"""
    print("=" * 70)
    print("SECURITY FEATURES VERIFICATION TEST SUITE")
    print("=" * 70)
    
    tests = [
        ("Week 1.1: SecurityError Class", test_security_error_class),
        ("Week 1.2: SafeExecutor Class", test_safe_executor_class),
        ("Week 1.3: Path Validation", test_path_validation),
        ("Week 1.4: Workspace Configuration", test_jarcore_workspace_config),
        ("Week 2.1: JSON Extraction", test_json_extraction),
        ("Week 2.2: Race Condition Fix", test_lazy_loader_race_condition),
        ("Week 2.3: Session Management", test_session_management),
        ("Week 2.4: Rate Limiting", test_rate_limiting),
        ("Week 2.5: Request Validation", test_pydantic_models),
        ("Week 2.6: Bounded Edit History", test_bounded_edit_history),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        print(f"\n### {name} ###")
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"✗ {name} FAILED")
        except Exception as e:
            failed += 1
            print(f"✗ {name} FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
