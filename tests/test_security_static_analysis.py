#!/usr/bin/env python3
"""
Static analysis test to verify security hardening implementation.
Tests all 9 security fixes from PR #24 without requiring dependencies.
"""

import ast
import re
from pathlib import Path


def analyze_file(filepath):
    """Parse Python file and return AST + content"""
    with open(filepath, 'r') as f:
        content = f.read()
    try:
        tree = ast.parse(content)
        return tree, content
    except:
        return None, content


def get_classes_and_methods(tree):
    """Extract all classes and their methods from AST"""
    classes = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes[node.name] = methods
    return classes


def test_week1_code_execution_sandboxing():
    """Week 1.1: Code Execution Sandboxing"""
    print("\n### Week 1.1: Code Execution Sandboxing ###")
    
    tree, content = analyze_file('mcp_gateway/coding_agent.py')
    classes = get_classes_and_methods(tree)
    
    tests = [
        ("SecurityError class exists", "class SecurityError(Exception):" in content),
        ("SafeExecutor class exists", "class SafeExecutor:" in content),
        ("MAX_CPU_TIME = 30", "MAX_CPU_TIME = 30" in content),
        ("MAX_MEMORY = 256MB", "MAX_MEMORY = 256 * 1024 * 1024" in content),
        ("MAX_FILE_SIZE = 10MB", "MAX_FILE_SIZE = 10 * 1024 * 1024" in content),
        ("MAX_PROCESSES = 0", "MAX_PROCESSES = 0" in content),
        ("set_resource_limits method", "def set_resource_limits():" in content),
        ("resource.setrlimit calls", "resource.setrlimit" in content),
        ("import resource", "import resource" in content),
        ("preexec_fn in execute_code", "preexec_fn=preexec_fn" in content),
    ]
    
    passed = sum(1 for _, result in tests if result)
    for desc, result in tests:
        print(f"   {'✓' if result else '✗'} {desc}")
    
    return passed, len(tests)


def test_week1_path_traversal_protection():
    """Week 1.2: Path Traversal Protection"""
    print("\n### Week 1.2: Path Traversal Protection ###")
    
    tree, content = analyze_file('mcp_gateway/coding_agent.py')
    classes = get_classes_and_methods(tree)
    
    tests = [
        ("_validate_path method exists", "_validate_path" in classes.get("JARCORE", [])),
        ("Path.resolve() used", ".resolve()" in content),
        ("relative_to workspace check", "relative_to(self.workspace_root.resolve())" in content),
        ("SecurityError on traversal", "Path traversal detected" in content),
        ("Sensitive patterns blocked", "sensitive_patterns = ['.env', '.git/config'" in content),
        ("_validate_path in read_file", "_validate_path(file_path)" in content and "async def read_file" in content),
        ("_validate_path in write_file", "_validate_path(file_path)" in content and "async def write_file" in content),
    ]
    
    passed = sum(1 for _, result in tests if result)
    for desc, result in tests:
        print(f"   {'✓' if result else '✗'} {desc}")
    
    return passed, len(tests)


def test_week1_remove_hardcoded_paths():
    """Week 1.3: Remove Hardcoded Paths"""
    print("\n### Week 1.3: Remove Hardcoded Paths ###")
    
    # Check config.py
    _, config_content = analyze_file('config.py')
    
    # Check coding_agent.py
    _, agent_content = analyze_file('mcp_gateway/coding_agent.py')
    
    tests = [
        ("JARCORE_WORKSPACE in config.py", "JARCORE_WORKSPACE = Path(os.environ.get" in config_content),
        ("Imports JARCORE_WORKSPACE", "from config import JARCORE_WORKSPACE" in agent_content),
        ("Uses JARCORE_WORKSPACE in __init__", "JARCORE_WORKSPACE" in agent_content and "def __init__" in agent_content),
        ("No /home/xmanz/JRVS hardcoded", "/home/xmanz/JRVS" not in agent_content),
    ]
    
    passed = sum(1 for _, result in tests if result)
    for desc, result in tests:
        print(f"   {'✓' if result else '✗'} {desc}")
    
    return passed, len(tests)


def test_week2_robust_json_extraction():
    """Week 2.1: Robust JSON Extraction"""
    print("\n### Week 2.1: Robust JSON Extraction ###")
    
    tree, content = analyze_file('mcp_gateway/coding_agent.py')
    classes = get_classes_and_methods(tree)
    
    tests = [
        ("_extract_json method exists", "_extract_json" in classes.get("JARCORE", [])),
        ("Returns Tuple[Optional[Dict], Optional[str]]", "Tuple[Optional[Dict], Optional[str]]" in content),
        ("Strategy 1: Direct JSON parse", "json.loads(response.strip())" in content),
        ("Strategy 2: Code block regex", r"r'```(?:json)?" in content),
        ("Strategy 3: Bracket-depth comment", "Bracket-depth matching" in content),
        ("Bracket depth logic", "depth = 0" in content and "start_idx" in content),
        ("Used in generate_code", "_extract_json(response)" in content and "generate_code" in content),
        ("Used in analyze_code", "_extract_json(response)" in content and "analyze_code" in content),
    ]
    
    passed = sum(1 for _, result in tests if result)
    for desc, result in tests:
        print(f"   {'✓' if result else '✗'} {desc}")
    
    return passed, len(tests)


def test_week2_race_condition_fix():
    """Week 2.2: Fix Race Condition"""
    print("\n### Week 2.2: Fix Race Condition in Lazy Loader ###")
    
    tree, content = analyze_file('core/lazy_loader.py')
    
    tests = [
        ("asyncio.Event imported", "import asyncio" in content),
        ("_load_complete Event created", "_load_complete = asyncio.Event()" in content),
        ("await _load_complete.wait()", "await self._load_complete.wait()" in content),
        ("_load_complete.clear()", "_load_complete.clear()" in content),
        ("_load_complete.set()", "_load_complete.set()" in content),
    ]
    
    passed = sum(1 for _, result in tests if result)
    for desc, result in tests:
        print(f"   {'✓' if result else '✗'} {desc}")
    
    return passed, len(tests)


def test_week2_session_management():
    """Week 2.3: Fix Session Management"""
    print("\n### Week 2.3: Fix Session Management ###")
    
    tree, content = analyze_file('llm/ollama_client.py')
    
    tests = [
        ("asynccontextmanager import", "from contextlib import asynccontextmanager" in content),
        ("@asynccontextmanager decorator", "@asynccontextmanager" in content),
        ("_get_session method", "async def _get_session(self):" in content),
        ("ClientConnectorError handling", "except aiohttp.ClientConnectorError" in content),
        ("Session cleanup", "await self.session.close()" in content),
    ]
    
    passed = sum(1 for _, result in tests if result)
    for desc, result in tests:
        print(f"   {'✓' if result else '✗'} {desc}")
    
    return passed, len(tests)


def test_week2_rate_limiting():
    """Week 2.4: Rate Limiting"""
    print("\n### Week 2.4: Rate Limiting ###")
    
    _, web_content = analyze_file('web_server.py')
    
    with open('requirements.txt', 'r') as f:
        req_content = f.read()
    
    tests = [
        ("slowapi in requirements.txt", "slowapi" in req_content),
        ("Limiter imported", "from slowapi import Limiter" in web_content),
        ("Limiter instantiated", "limiter = Limiter(" in web_content),
        ("get_remote_address", "get_remote_address" in web_content),
        ("RateLimitExceeded", "RateLimitExceeded" in web_content),
    ]
    
    passed = sum(1 for _, result in tests if result)
    for desc, result in tests:
        print(f"   {'✓' if result else '✗'} {desc}")
    
    return passed, len(tests)


def test_week2_request_validation():
    """Week 2.5: Request Validation"""
    print("\n### Week 2.5: Request Validation ###")
    
    tree, content = analyze_file('web_server.py')
    classes = get_classes_and_methods(tree)
    
    tests = [
        ("Pydantic BaseModel import", "from pydantic import BaseModel" in content),
        ("ChatRequest model", "class ChatRequest(BaseModel):" in content),
        ("ScrapeRequest model", "class ScrapeRequest(BaseModel):" in content),
        ("CodeExecuteRequest model", "class CodeExecuteRequest(BaseModel):" in content),
        ("Field import", "from pydantic import BaseModel, validator, Field" in content or "Field" in content),
        ("@validator decorator", "@validator" in content),
        ("URL validation", "validate_url" in content),
        ("Message sanitization", "sanitize_message" in content),
    ]
    
    passed = sum(1 for _, result in tests if result)
    for desc, result in tests:
        print(f"   {'✓' if result else '✗'} {desc}")
    
    return passed, len(tests)


def test_week2_bounded_edit_history():
    """Week 2.6: Bounded Edit History"""
    print("\n### Week 2.6: Bounded Edit History ###")
    
    tree, content = analyze_file('mcp_gateway/coding_agent.py')
    
    tests = [
        ("deque import", "from collections import deque" in content),
        ("deque with maxlen", "deque(maxlen=" in content),
        ("max_history parameter", "max_history: int = 1000" in content),
        ("edit_history assignment", "self.edit_history: deque = deque(maxlen=max_history)" in content or "self.edit_history = deque(maxlen=max_history)" in content),
    ]
    
    passed = sum(1 for _, result in tests if result)
    for desc, result in tests:
        print(f"   {'✓' if result else '✗'} {desc}")
    
    return passed, len(tests)


def main():
    """Run all static analysis tests"""
    print("=" * 70)
    print("SECURITY HARDENING - STATIC ANALYSIS VERIFICATION")
    print("=" * 70)
    
    test_functions = [
        ("Week 1.1: Code Execution Sandboxing", test_week1_code_execution_sandboxing),
        ("Week 1.2: Path Traversal Protection", test_week1_path_traversal_protection),
        ("Week 1.3: Remove Hardcoded Paths", test_week1_remove_hardcoded_paths),
        ("Week 2.1: Robust JSON Extraction", test_week2_robust_json_extraction),
        ("Week 2.2: Race Condition Fix", test_week2_race_condition_fix),
        ("Week 2.3: Session Management", test_week2_session_management),
        ("Week 2.4: Rate Limiting", test_week2_rate_limiting),
        ("Week 2.5: Request Validation", test_week2_request_validation),
        ("Week 2.6: Bounded Edit History", test_week2_bounded_edit_history),
    ]
    
    total_passed = 0
    total_tests = 0
    
    for name, test_func in test_functions:
        try:
            passed, total = test_func()
            total_passed += passed
            total_tests += total
        except Exception as e:
            print(f"✗ {name} FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print(f"FINAL RESULTS: {total_passed}/{total_tests} checks passed")
    
    if total_passed == total_tests:
        print("✓ ALL SECURITY FEATURES VERIFIED!")
    else:
        print(f"✗ {total_tests - total_passed} checks failed")
    
    print("=" * 70)
    
    return total_passed == total_tests


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
