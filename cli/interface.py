"""Main CLI interface for Jarvis AI Agent"""
import asyncio
import uuid
from typing import Dict, List, Optional
import signal
import sys

from .themes import theme
from .commands import CommandHandler
from llm.ollama_client import ollama_client
from rag.retriever import rag_retriever
from scraper.web_scraper import web_scraper
from core.database import db
from core.calendar import calendar

class JarvisCLI:
    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.running = True
        self.command_handler = CommandHandler(self)
        self.conversation_history = []

    async def initialize(self):
        """Initialize all components"""
        theme.print_status("Initializing Jarvis AI Agent...", "info")
        
        try:
            # Initialize components
            await db.initialize()
            await calendar.initialize()
            await rag_retriever.initialize()
            
            # Discover available models
            models = await ollama_client.discover_models()
            if not models:
                theme.print_error("No Ollama models found. Please install Ollama and pull some models.")
                return False
            
            theme.print_success(f"Found {len(models)} Ollama models")
            theme.print_success("Jarvis AI Agent initialized successfully!")
            
            return True
            
        except Exception as e:
            theme.print_error(f"Initialization failed: {e}")
            return False

    async def start(self):
        """Start the CLI interface"""
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Clear screen and show banner
        theme.clear_screen()
        theme.print_banner()
        
        # Initialize components
        if not await self.initialize():
            return
        
        theme.print_separator()
        theme.print_info("Type '/help' for available commands or start chatting!")
        theme.print_separator()
        
        # Main interaction loop
        while self.running:
            try:
                user_input = theme.print_prompt("jarvis")
                
                if not user_input.strip():
                    continue
                
                # Handle commands or chat
                if user_input.startswith('/'):
                    await self.command_handler.handle_command(user_input[1:])
                else:
                    await self.handle_chat_message(user_input)
                    
            except KeyboardInterrupt:
                if theme.confirm("Are you sure you want to exit?"):
                    break
            except Exception as e:
                theme.print_error(f"Unexpected error: {e}")
        
        await self.cleanup()

    async def handle_chat_message(self, message: str):
        """Handle regular chat messages"""
        try:
            # Check for natural language calendar requests
            if await self._try_parse_calendar_request(message):
                return

            # Show thinking indicator
            with theme.show_progress("Thinking...") as progress:
                task = progress.add_task("", total=None)
                
                # Get context from RAG
                context = await rag_retriever.retrieve_context(message, self.session_id)
                progress.update(task, description="Generating response...")
                
                # Generate response with context injection
                response = await ollama_client.generate(
                    prompt=message,
                    context=context,
                    stream=False  # We'll handle our own display
                )
            
            if response:
                # Display response
                theme.print_response(response)
                
                # Store conversation
                await db.add_conversation(
                    session_id=self.session_id,
                    user_message=message,
                    ai_response=response,
                    model_used=ollama_client.current_model,
                    context_used=context[:500] + "..." if len(context) > 500 else context
                )
                
                # Add to local history
                self.conversation_history.append({
                    'user': message,
                    'assistant': response,
                    'model': ollama_client.current_model
                })
                
            else:
                theme.print_error("Failed to generate response")
                
        except Exception as e:
            theme.print_error(f"Chat error: {e}")

    async def handle_streaming_response(self, message: str):
        """Handle streaming chat response"""
        try:
            # Get context
            context = await rag_retriever.retrieve_context(message, self.session_id)
            
            theme.print_status("Assistant:", "info")
            
            # Start streaming response
            response = ""
            async for chunk in self._generate_streaming(message, context):
                print(chunk, end='', flush=True)
                response += chunk
            
            print()  # New line after response
            
            # Store conversation
            if response:
                await db.add_conversation(
                    session_id=self.session_id,
                    user_message=message,
                    ai_response=response,
                    model_used=ollama_client.current_model,
                    context_used=context[:500] + "..." if len(context) > 500 else context
                )
                
        except Exception as e:
            theme.print_error(f"Streaming error: {e}")

    async def _generate_streaming(self, message: str, context: str):
        """Generate streaming response (placeholder for actual streaming)"""
        # This would integrate with the actual Ollama streaming API
        response = await ollama_client.generate(
            prompt=message,
            context=context,
            stream=False
        )
        
        if response:
            # Simulate streaming by yielding chunks
            for i in range(0, len(response), 10):
                yield response[i:i+10]
                await asyncio.sleep(0.05)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        if not hasattr(self, '_shutting_down'):
            self._shutting_down = True
            theme.print_warning("\nShutdown signal received...")
            self.running = False
            # Force exit if needed
            import sys
            sys.exit(0)

    async def cleanup(self):
        """Clean up resources"""
        theme.print_status("Cleaning up...", "info")
        
        try:
            await ollama_client.cleanup()
            await web_scraper.cleanup()
            await rag_retriever.cleanup()
            
            theme.print_success("Goodbye!")
            
        except Exception as e:
            theme.print_error(f"Cleanup error: {e}")

    # Utility methods for commands
    async def list_models(self):
        """List available models"""
        models = await ollama_client.list_models()
        if models:
            theme.print_model_info(models, ollama_client.current_model)
        else:
            theme.print_error("No models available")

    async def switch_model(self, model_name: str):
        """Switch to a different model"""
        if await ollama_client.switch_model(model_name):
            theme.print_success(f"Switched to model: {model_name}")
        else:
            theme.print_error(f"Failed to switch to model: {model_name}")

    async def scrape_url(self, url: str):
        """Scrape a URL and add to knowledge base"""
        with theme.show_progress(f"Scraping {url}...") as progress:
            task = progress.add_task("", total=None)
            
            doc_id = await web_scraper.scrape_and_store(url)
            
            if doc_id:
                theme.print_success(f"Successfully scraped and stored: {url}")
            else:
                theme.print_error(f"Failed to scrape: {url}")

    async def search_documents(self, query: str):
        """Search stored documents"""
        results = await rag_retriever.search_documents(query)
        
        if results:
            theme.print_status(f"Found {len(results)} results:", "info")
            
            for result in results:
                theme.print_info(f"• {result['title']} ({result.get('similarity', 0):.2f})")
                theme.console.print(f"  {result['preview']}")
                if result.get('url'):
                    theme.console.print(f"  URL: {result['url']}")
                theme.print_separator(length=30)
        else:
            theme.print_warning("No documents found")

    async def show_stats(self):
        """Show system statistics"""
        stats = await rag_retriever.get_stats()
        
        # Add current session info
        stats['session'] = {
            'session_id': self.session_id[:8] + "...",
            'conversations': len(self.conversation_history),
            'current_model': ollama_client.current_model
        }
        
        theme.print_stats(stats)

    def show_conversation_history(self, limit: int = 5):
        """Show recent conversation history"""
        if not self.conversation_history:
            theme.print_warning("No conversation history")
            return
        
        theme.print_status("Recent Conversations:", "info")
        
        for i, conv in enumerate(self.conversation_history[-limit:], 1):
            theme.console.print(f"\n[{theme.get_color('accent')}]#{i}[/]")
            theme.console.print(f"[{theme.get_color('primary')}]User:[/] {conv['user'][:100]}{'...' if len(conv['user']) > 100 else ''}")
            theme.console.print(f"[{theme.get_color('secondary')}]Assistant:[/] {conv['assistant'][:200]}{'...' if len(conv['assistant']) > 200 else ''}")
            theme.console.print(f"[dim]Model: {conv['model']}[/]")

    def set_theme(self, theme_name: str):
        """Set CLI theme"""
        theme.set_theme(theme_name)

    async def show_calendar(self):
        """Show upcoming events"""
        events = await calendar.get_upcoming_events(days=7)
        if events:
            theme.print_status("Upcoming Events (Next 7 Days):", "info")
            from datetime import datetime
            for event in events:
                event_dt = datetime.fromisoformat(event['event_date'])
                theme.console.print(f"[{theme.get_color('accent')}]#{event['id']}[/] {event['title']}")
                theme.console.print(f"  Date: {event_dt.strftime('%Y-%m-%d %H:%M')}")
                if event['description']:
                    theme.console.print(f"  {event['description']}")
                theme.print_separator(length=30)
        else:
            theme.print_warning("No upcoming events")

    async def show_today_events(self):
        """Show today's events"""
        events = await calendar.get_today_events()
        if events:
            theme.print_status("Today's Events:", "info")
            from datetime import datetime
            for event in events:
                event_dt = datetime.fromisoformat(event['event_date'])
                theme.console.print(f"[{theme.get_color('accent')}]#{event['id']}[/] {event['title']}")
                theme.console.print(f"  Time: {event_dt.strftime('%H:%M')}")
                if event['description']:
                    theme.console.print(f"  {event['description']}")
                theme.print_separator(length=30)
        else:
            theme.print_info("No events today")

    async def add_event(self, args: List[str]):
        """Add a calendar event"""
        try:
            from datetime import datetime
            # Parse: /event 2025-11-10 14:30 Team meeting
            date_str = args[0]
            time_str = args[1]
            title = " ".join(args[2:])

            event_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            event_id = await calendar.add_event(title, event_dt)
            theme.print_success(f"Event #{event_id} added: {title} on {event_dt.strftime('%Y-%m-%d %H:%M')}")
        except Exception as e:
            theme.print_error(f"Failed to add event: {e}")

    async def complete_event(self, event_id: int):
        """Mark event as completed"""
        try:
            await calendar.mark_completed(event_id)
            theme.print_success(f"Event #{event_id} marked as completed")
        except Exception as e:
            theme.print_error(f"Failed to complete event: {e}")

    async def _try_parse_calendar_request(self, message: str) -> bool:
        """Try to parse natural language calendar requests"""
        import re
        from datetime import datetime, timedelta

        msg_lower = message.lower()

        # Pattern: "meeting/event/reminder tomorrow/today at X"
        if any(word in msg_lower for word in ['meeting', 'event', 'reminder', 'appointment']):
            time_match = re.search(r'at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?', msg_lower)

            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2)) if time_match.group(2) else 0
                meridiem = time_match.group(3)

                # Convert to 24-hour format
                if meridiem == 'pm' and hour != 12:
                    hour += 12
                elif meridiem == 'am' and hour == 12:
                    hour = 0

                # Determine date
                if 'tomorrow' in msg_lower:
                    event_date = datetime.now() + timedelta(days=1)
                elif 'today' in msg_lower:
                    event_date = datetime.now()
                else:
                    event_date = datetime.now()

                # Set time
                event_date = event_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

                # Extract title (simplified)
                title = message.split('at')[0].strip()
                if not title or len(title) < 3:
                    title = "Meeting"

                event_id = await calendar.add_event(title, event_date)
                theme.print_success(f"✓ Event added: {title} on {event_date.strftime('%Y-%m-%d %H:%M')}")
                return True

        return False

    def show_help(self):
        """Show help information"""
        commands = {
            "/help": "Show this help message",
            "/models": "List available Ollama models",
            "/switch <model>": "Switch to a different model",
            "/scrape <url>": "Scrape a website and add to knowledge base",
            "/search <query>": "Search stored documents",
            "/calendar": "Show upcoming events (7 days)",
            "/today": "Show today's events",
            "/event <date> <time> <title>": "Add calendar event",
            "/complete <id>": "Mark event as completed",
            "/stats": "Show system statistics",
            "/history": "Show conversation history",
            "/theme <name>": "Change CLI theme (matrix, cyberpunk, minimal)",
            "/clear": "Clear the screen",
            "/exit": "Exit Jarvis"
        }

        theme.print_help(commands)

# CLI instance
cli = JarvisCLI()