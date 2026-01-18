"""CLI themes and styling system"""
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich import box
import time
from typing import Dict, Optional

from config import THEMES, DEFAULT_THEME, JARVIS_ASCII

class ThemeManager:
    def __init__(self):
        self.console = Console()
        self.current_theme = DEFAULT_THEME
        self.theme_config = THEMES[self.current_theme]

    def set_theme(self, theme_name: str) -> bool:
        """Set the current theme"""
        if theme_name in THEMES:
            self.current_theme = theme_name
            self.theme_config = THEMES[theme_name]
            self.console.print(f"[{self.theme_config['accent']}]Theme switched to: {theme_name}[/]")
            return True
        else:
            self.console.print(f"[red]Unknown theme: {theme_name}[/]")
            self.console.print(f"[yellow]Available themes: {', '.join(THEMES.keys())}[/]")
            return False

    def get_color(self, color_type: str) -> str:
        """Get color for a specific UI element"""
        return self.theme_config.get(color_type, "white")

    def print_banner(self):
        """Print the Jarvis ASCII banner"""
        banner_text = Text(JARVIS_ASCII)
        banner_text.stylize(self.get_color("primary"))
        
        panel = Panel(
            banner_text,
            box=box.DOUBLE,
            border_style=self.get_color("accent"),
            padding=(1, 2)
        )
        
        self.console.print(panel)

    def print_prompt(self, text: str = "❯") -> str:
        """Print input prompt and get user input"""
        prompt_style = f"[{self.get_color('prompt')}]"
        try:
            return Prompt.ask(f"{prompt_style}{text}[/]")
        except EOFError:
            return "/exit"

    def print_response(self, text: str, title: str = "Assistant"):
        """Print AI response in styled panel"""
        response_text = Text(text)
        response_text.stylize(self.get_color("response"))
        
        panel = Panel(
            response_text,
            title=f"[{self.get_color('accent')}]{title}[/]",
            border_style=self.get_color("secondary"),
            padding=(1, 2)
        )
        
        self.console.print(panel)

    def print_status(self, message: str, status_type: str = "info"):
        """Print status message"""
        colors = {
            "info": self.get_color("accent"),
            "success": "green",
            "warning": self.get_color("warning"),
            "error": self.get_color("error")
        }
        
        color = colors.get(status_type, self.get_color("accent"))
        self.console.print(f"[{color}]● {message}[/]")

    def print_error(self, message: str):
        """Print error message"""
        self.console.print(f"[{self.get_color('error')}]✗ Error: {message}[/]")

    def print_success(self, message: str):
        """Print success message"""
        self.console.print(f"[green]✓ {message}[/]")

    def print_warning(self, message: str):
        """Print warning message"""
        self.console.print(f"[{self.get_color('warning')}]⚠ Warning: {message}[/]")

    def print_info(self, message: str):
        """Print info message"""
        self.console.print(f"[{self.get_color('accent')}]ℹ {message}[/]")

    def print_table(self, data: list, headers: list, title: str = None):
        """Print data in a styled table"""
        table = Table(
            title=title,
            box=box.ROUNDED,
            border_style=self.get_color("secondary"),
            header_style=self.get_color("primary")
        )
        
        # Add columns
        for header in headers:
            table.add_column(header, style=self.get_color("response"))
        
        # Add rows
        for row in data:
            table.add_row(*[str(cell) for cell in row])
        
        self.console.print(table)

    def print_code(self, code: str, language: str = "python"):
        """Print syntax highlighted code"""
        syntax = Syntax(
            code,
            language,
            theme="monokai",
            background_color="default"
        )
        
        panel = Panel(
            syntax,
            border_style=self.get_color("secondary"),
            padding=(1, 2)
        )
        
        self.console.print(panel)

    def print_markdown(self, content: str):
        """Print markdown content"""
        md = Markdown(content)
        self.console.print(md)

    def show_progress(self, description: str = "Processing..."):
        """Create a progress indicator"""
        return Progress(
            SpinnerColumn(),
            TextColumn(f"[{self.get_color('primary')}]{description}[/]"),
            console=self.console,
            transient=True
        )

    def show_loading(self, message: str, duration: float = 2.0):
        """Show a loading animation"""
        with self.show_progress(message) as progress:
            task = progress.add_task("", total=100)
            
            for i in range(100):
                time.sleep(duration / 100)
                progress.update(task, advance=1)

    def print_separator(self, char: str = "─", length: int = 50):
        """Print a separator line"""
        separator = char * length
        self.console.print(f"[{self.get_color('secondary')}]{separator}[/]")

    def clear_screen(self):
        """Clear the console screen"""
        self.console.clear()

    def print_help(self, commands: Dict[str, str]):
        """Print help information"""
        help_table = Table(
            title="Available Commands",
            box=box.ROUNDED,
            border_style=self.get_color("accent"),
            header_style=self.get_color("primary")
        )
        
        help_table.add_column("Command", style=self.get_color("accent"), no_wrap=True)
        help_table.add_column("Description", style=self.get_color("response"))
        
        for command, description in commands.items():
            help_table.add_row(command, description)
        
        self.console.print(help_table)

    def animate_text(self, text: str, delay: float = 0.03):
        """Animate text typing effect"""
        for char in text:
            self.console.print(char, end="", style=self.get_color("response"))
            time.sleep(delay)
        self.console.print()  # New line at end

    def print_model_info(self, models: list, current_model: str):
        """Print model information"""
        model_table = Table(
            title="Available Models",
            box=box.ROUNDED,
            border_style=self.get_color("accent"),
            header_style=self.get_color("primary")
        )
        
        model_table.add_column("Model", style=self.get_color("response"))
        model_table.add_column("Status", justify="center")
        model_table.add_column("Size", justify="right")
        
        for model in models:
            status = "🟢 Active" if model['name'] == current_model else "⚪ Available"
            size = self._format_size(model.get('size', 0))
            
            model_table.add_row(
                model['name'],
                status,
                size
            )
        
        self.console.print(model_table)

    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human readable format"""
        if size_bytes == 0:
            return "Unknown"
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        
        return f"{size_bytes:.1f} PB"

    def print_stats(self, stats: Dict):
        """Print system statistics"""
        stats_table = Table(
            title="System Statistics",
            box=box.ROUNDED,
            border_style=self.get_color("accent"),
            header_style=self.get_color("primary")
        )
        
        stats_table.add_column("Metric", style=self.get_color("accent"))
        stats_table.add_column("Value", style=self.get_color("response"))
        
        for key, value in stats.items():
            if isinstance(value, dict):
                # Handle nested stats
                for sub_key, sub_value in value.items():
                    stats_table.add_row(f"{key}.{sub_key}", str(sub_value))
            else:
                stats_table.add_row(key, str(value))
        
        self.console.print(stats_table)

    def confirm(self, message: str) -> bool:
        """Get user confirmation"""
        response = Prompt.ask(
            f"[{self.get_color('warning')}]{message} (y/n)[/]",
            choices=["y", "n"],
            default="n"
        )
        return response.lower() == "y"

# Global theme manager instance
theme = ThemeManager()