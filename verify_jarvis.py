#!/usr/bin/env python3
"""
Verify JARVIS Model Setup

This script checks if:
1. JARVIS model exists in Ollama
2. JRVS is configured to use JARVIS
3. JARVIS responds correctly
"""

import asyncio
import subprocess
from llm.ollama_client import ollama_client
from config import DEFAULT_MODEL


def check_ollama_running():
    """Check if Ollama is running"""
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/tags"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False


def check_jarvis_model_exists():
    """Check if JARVIS model exists in Ollama"""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return "jarvis" in result.stdout.lower()
    except:
        return False


async def test_jarvis_response():
    """Test JARVIS model response"""
    try:
        response = await ollama_client.generate(
            prompt="Hello JARVIS, please introduce yourself briefly.",
            context="",
            stream=False
        )
        return response if response else None
    except Exception as e:
        return f"Error: {e}"


async def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║            JARVIS Model Verification                      ║
╚═══════════════════════════════════════════════════════════╝
    """)

    # Check 1: Ollama running
    print("1️⃣  Checking if Ollama is running...")
    if check_ollama_running():
        print("   ✅ Ollama is running\n")
    else:
        print("   ❌ Ollama is not running")
        print("   → Start it with: ollama serve\n")
        return

    # Check 2: JARVIS model exists
    print("2️⃣  Checking if JARVIS model exists...")
    if check_jarvis_model_exists():
        print("   ✅ JARVIS model found\n")
    else:
        print("   ❌ JARVIS model not found")
        print("   → Create it with: ./create_jarvis_model.sh")
        print("   → Or: ollama create jarvis -f Modelfile.jarvis\n")
        return

    # Check 3: JRVS configuration
    print("3️⃣  Checking JRVS configuration...")
    print(f"   Current default model: {DEFAULT_MODEL}")
    if DEFAULT_MODEL.lower() == "jarvis":
        print("   ✅ JRVS configured to use JARVIS\n")
    else:
        print("   ⚠️  JRVS not configured to use JARVIS")
        print(f"   → Edit config.py: DEFAULT_MODEL = 'jarvis'\n")

    # Check 4: Test JARVIS response
    print("4️⃣  Testing JARVIS response...")
    print("   Sending test prompt to JARVIS...\n")

    response = await test_jarvis_response()

    if response and "error" not in str(response).lower()[:50]:
        print("   ✅ JARVIS responded successfully!\n")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("📝 JARVIS Response:")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"\n{response}\n")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    else:
        print(f"   ❌ Error getting response: {response}\n")
        return

    # Final status
    print("\n╔═══════════════════════════════════════════════════════════╗")
    print("║                  ✅ VERIFICATION COMPLETE                 ║")
    print("╚═══════════════════════════════════════════════════════════╝\n")

    print("🎯 Next Steps:")
    print("   • Start JRVS web server: python3 web_server.py")
    print("   • Or use CLI: python3 main.py")
    print("   • JARVIS is now your default AI assistant!\n")

    print("💡 Test Commands:")
    print("   • ollama run jarvis 'What are your capabilities?'")
    print("   • python3 main.py  (and chat with JARVIS)")
    print("")


if __name__ == "__main__":
    asyncio.run(main())
