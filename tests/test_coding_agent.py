#!/usr/bin/env python3
"""Test script for JRVS Coding Agent"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_coding_agent():
    """Test the coding agent functionality"""
    try:
        from mcp.coding_agent import coding_agent
        print("✓ Coding agent imported successfully")

        # Test code generation
        print("\n=== Testing Code Generation ===")
        result = await coding_agent.generate_code(
            task="Create a function that calculates fibonacci numbers",
            language="python",
            include_tests=False
        )

        if "error" not in result:
            print("✓ Code generation successful")
            print(f"Generated code:\n{result.get('code', 'N/A')[:200]}...")
        else:
            print(f"✗ Code generation failed: {result['error']}")

        # Test code explanation
        print("\n=== Testing Code Explanation ===")
        test_code = """
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
"""
        explanation = await coding_agent.explain_code(test_code, "python", "brief")
        print(f"✓ Explanation: {explanation[:200]}...")

        # Test file operations
        print("\n=== Testing File Operations ===")
        test_file = "/tmp/jrvs_test.py"
        write_result = await coding_agent.write_file(
            test_file,
            test_code,
            create_dirs=True,
            backup=False
        )

        if write_result.get("success"):
            print(f"✓ File written: {test_file}")

            read_result = await coding_agent.read_file(test_file)
            if not read_result.get("error"):
                print(f"✓ File read: {read_result.get('lines')} lines")
            else:
                print(f"✗ File read failed: {read_result.get('error')}")
        else:
            print(f"✗ File write failed: {write_result.get('error')}")

        print("\n=== All Tests Complete ===")

    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_coding_agent())
