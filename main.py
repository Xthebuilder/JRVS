#!/usr/bin/env python3
"""
Jarvis AI Agent - Advanced RAG-powered CLI assistant

A sophisticated AI assistant that combines Ollama LLMs with RAG (Retrieval-Augmented Generation)
capabilities, featuring web scraping, vector search, and intelligent context injection.

Features:
- RAG pipeline with FAISS vector search and BERT embeddings
- Dynamic Ollama model switching
- Web scraping and document ingestion
- Beautiful CLI with customizable themes
- Persistent conversation memory
- Robust error handling and timeout management
- Lazy loading for optimal performance

Usage:
    python main.py [options]

Commands:
    /help           - Show available commands
    /models         - List Ollama models
    /switch <model> - Switch AI model
    /scrape <url>   - Scrape website
    /search <query> - Search documents
    /stats          - Show system stats
    /theme <name>   - Change theme
"""

import asyncio
import sys
import os
from pathlib import Path
import argparse

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from cli.interface import cli
from cli.themes import theme
from core.lazy_loader import health_checker
from config import OLLAMA_BASE_URL

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Jarvis AI Agent - Advanced RAG-powered CLI assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "--theme",
        choices=["matrix", "cyberpunk", "minimal"],
        default="matrix",
        help="CLI theme (default: matrix)"
    )
    
    parser.add_argument(
        "--model",
        help="Default Ollama model to use"
    )
    
    parser.add_argument(
        "--ollama-url",
        default=OLLAMA_BASE_URL,
        help=f"Ollama API URL (default: {OLLAMA_BASE_URL})"
    )
    
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="Skip the ASCII banner on startup"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="Jarvis AI Agent 1.0.0"
    )
    
    return parser.parse_args()

def check_dependencies():
    """Check if required dependencies are available"""
    missing_deps = []
    
    try:
        import torch
    except ImportError:
        missing_deps.append("torch")
    
    try:
        import faiss
    except ImportError:
        missing_deps.append("faiss-cpu")
    
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        missing_deps.append("sentence-transformers")
    
    try:
        from rich.console import Console
    except ImportError:
        missing_deps.append("rich")
    
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        missing_deps.append("beautifulsoup4")
    
    if missing_deps:
        print("Missing required dependencies:")
        for dep in missing_deps:
            print(f"  - {dep}")
        print("\nInstall them with:")
        print(f"  pip install {' '.join(missing_deps)}")
        return False
    
    return True

async def check_ollama_connection(url: str):
    """Check if Ollama is running"""
    import aiohttp
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{url}/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    return True
    except Exception:
        pass
    
    return False

async def setup_health_monitoring():
    """Set up health monitoring for system components"""
    
    # Register health checks
    async def check_ollama():
        return await check_ollama_connection(OLLAMA_BASE_URL)
    
    def check_database():
        try:
            import sqlite3
            return True
        except Exception:
            return False
    
    def check_memory():
        try:
            import psutil
            memory = psutil.virtual_memory()
            return memory.percent < 90  # Consider healthy if < 90% memory usage
        except ImportError:
            return True  # If psutil not available, assume healthy
    
    health_checker.register_component("ollama", check_ollama)
    health_checker.register_component("database", check_database)
    health_checker.register_component("memory", check_memory)
    
    # Start monitoring in background
    asyncio.create_task(health_checker.start_monitoring())

def show_startup_info():
    """Show startup information"""
    theme.print_status("Jarvis AI Agent v1.0.0", "info")
    theme.print_status("Advanced RAG-powered CLI assistant", "info")
    theme.print_separator()

async def main():
    """Main application entry point"""
    args = parse_arguments()
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Set theme
    if args.theme:
        theme.set_theme(args.theme)
    
    # Show startup info
    if not args.no_banner:
        show_startup_info()
    
    # Check Ollama connection
    if not await check_ollama_connection(args.ollama_url):
        theme.print_error("Cannot connect to Ollama!")
        theme.print_info(f"Make sure Ollama is running at {args.ollama_url}")
        theme.print_info("Install Ollama: https://ollama.ai")
        theme.print_info("Start Ollama: ollama serve")
        sys.exit(1)
    
    # Set default model if specified
    if args.model:
        from llm.ollama_client import ollama_client
        await ollama_client.switch_model(args.model)
    
    # Setup health monitoring
    await setup_health_monitoring()
    
    # Enable debug mode if requested
    if args.debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)
        theme.print_info("Debug mode enabled")
    
    try:
        # Start the CLI
        await cli.start()
        
    except KeyboardInterrupt:
        theme.print_warning("Interrupted by user")
    except Exception as e:
        if args.debug:
            import traceback
            traceback.print_exc()
        else:
            theme.print_error(f"Unexpected error: {e}")
    finally:
        # Cleanup
        await health_checker.stop_monitoring()
        theme.print_status("Shutdown complete", "info")

if __name__ == "__main__":
    try:
        # Check Python version
        if sys.version_info < (3, 8):
            print("Error: Python 3.8 or higher is required")
            sys.exit(1)
        
        # Run main application
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)