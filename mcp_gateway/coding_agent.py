"""
JARCORE - JARVIS Autonomous Reasoning & Coding Engine

AI-powered coding assistant using Ollama local models.
JARCORE brings professional development capabilities to JARVIS.

Features:
- Code generation from natural language
- Code analysis and refactoring suggestions
- File operations (read, write, edit)
- Code execution and testing
- Multi-language support
- Context-aware coding using RAG
"""

import os
import ast
import json
import asyncio
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

from llm.ollama_client import ollama_client
from rag.retriever import rag_retriever


@dataclass
class CodeEditOperation:
    """Represents a code editing operation"""
    file_path: str
    operation: str  # "create", "edit", "delete"
    content: Optional[str]
    line_start: Optional[int]
    line_end: Optional[int]
    reasoning: str
    timestamp: str


class JARCORE:
    """JARVIS Autonomous Reasoning & Coding Engine"""

    def __init__(self, workspace_root: str = "/home/xmanz/JRVS"):
        self.workspace_root = Path(workspace_root)
        self.edit_history: List[CodeEditOperation] = []
        self.supported_languages = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".sh": "bash",
            ".sql": "sql",
            ".html": "html",
            ".css": "css",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml"
        }

    async def generate_code(
        self,
        task: str,
        language: str = "python",
        context: Optional[str] = None,
        include_tests: bool = False
    ) -> Dict[str, Any]:
        """
        Generate code from natural language description

        Args:
            task: Natural language description of what code should do
            language: Programming language to use
            context: Additional context (file contents, requirements, etc.)
            include_tests: Whether to generate test cases

        Returns:
            Dictionary with generated code, explanation, and metadata
        """
        # Get relevant context from RAG if not provided
        if context is None:
            await rag_retriever.initialize()
            context = await rag_retriever.retrieve_context(
                f"{language} code: {task}"
            )

        # Build prompt for code generation
        system_prompt = f"""You are an expert {language} programmer. Generate clean, efficient,
well-documented code based on the user's requirements. Include:
1. Complete, working code
2. Inline comments for complex logic
3. Error handling where appropriate
4. Type hints/annotations (if language supports them)
5. {"Unit tests" if include_tests else ""}

Format your response as JSON:
{{
  "code": "the actual code",
  "explanation": "brief explanation of the approach",
  "dependencies": ["list", "of", "required", "packages"],
  "usage_example": "how to use the code",
  "tests": "test code (if requested)"
}}
"""

        user_prompt = f"""Task: {task}

Language: {language}

{"Additional Context: " + context if context else ""}

Generate the code following best practices for {language}."""

        try:
            response = await ollama_client.generate(
                prompt=user_prompt,
                context="",
                system_prompt=system_prompt,
                stream=False
            )

            # Extract JSON from response
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(response[json_start:json_end])
                result["language"] = language
                result["task"] = task
                result["timestamp"] = datetime.now().isoformat()
                return result
            else:
                return {
                    "error": "Could not parse AI response",
                    "raw_response": response
                }

        except Exception as e:
            return {
                "error": str(e),
                "task": task,
                "language": language
            }

    async def analyze_code(
        self,
        code: str,
        language: str = "python",
        analysis_type: str = "comprehensive"
    ) -> Dict[str, Any]:
        """
        Analyze code for issues, improvements, and best practices

        Args:
            code: Code to analyze
            language: Programming language
            analysis_type: "comprehensive", "security", "performance", "style"

        Returns:
            Analysis results with suggestions
        """
        analysis_prompts = {
            "comprehensive": "Analyze for bugs, performance, security, and style issues",
            "security": "Focus on security vulnerabilities and potential exploits",
            "performance": "Focus on performance optimizations and efficiency",
            "style": "Focus on code style, readability, and best practices"
        }

        system_prompt = f"""You are a {language} code reviewer. {analysis_prompts.get(analysis_type, analysis_prompts['comprehensive'])}.

Provide analysis as JSON:
{{
  "issues": [
    {{
      "severity": "critical|high|medium|low",
      "type": "bug|security|performance|style",
      "line": line_number,
      "description": "what's wrong",
      "suggestion": "how to fix it"
    }}
  ],
  "metrics": {{
    "complexity": "high|medium|low",
    "maintainability": "score out of 10",
    "test_coverage_needed": true/false
  }},
  "suggestions": ["overall", "improvement", "suggestions"],
  "positive_aspects": ["what's", "done", "well"]
}}
"""

        user_prompt = f"""Analyze this {language} code:

```{language}
{code}
```

Provide {analysis_type} analysis."""

        try:
            response = await ollama_client.generate(
                prompt=user_prompt,
                context="",
                system_prompt=system_prompt,
                stream=False
            )

            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(response[json_start:json_end])
                result["language"] = language
                result["analysis_type"] = analysis_type
                result["timestamp"] = datetime.now().isoformat()
                return result
            else:
                return {
                    "error": "Could not parse analysis",
                    "raw_response": response
                }

        except Exception as e:
            return {
                "error": str(e),
                "language": language
            }

    async def refactor_code(
        self,
        code: str,
        language: str = "python",
        refactor_goal: str = "improve readability and maintainability"
    ) -> Dict[str, Any]:
        """
        Refactor code according to specified goals

        Args:
            code: Code to refactor
            language: Programming language
            refactor_goal: What to optimize for

        Returns:
            Refactored code with explanation of changes
        """
        system_prompt = f"""You are an expert {language} programmer specializing in refactoring.
Refactor the given code to {refactor_goal}.

Respond with JSON:
{{
  "refactored_code": "the improved code",
  "changes": [
    {{
      "description": "what was changed",
      "reason": "why it was changed",
      "impact": "expected improvement"
    }}
  ],
  "before_metrics": {{"complexity": "X", "lines": Y}},
  "after_metrics": {{"complexity": "X", "lines": Y}}
}}
"""

        user_prompt = f"""Refactor this {language} code:

```{language}
{code}
```

Goal: {refactor_goal}"""

        try:
            response = await ollama_client.generate(
                prompt=user_prompt,
                context="",
                system_prompt=system_prompt,
                stream=False
            )

            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(response[json_start:json_end])
                result["original_code"] = code
                result["language"] = language
                result["timestamp"] = datetime.now().isoformat()
                return result
            else:
                return {
                    "error": "Could not parse refactoring result",
                    "raw_response": response
                }

        except Exception as e:
            return {
                "error": str(e),
                "language": language
            }

    async def explain_code(
        self,
        code: str,
        language: str = "python",
        detail_level: str = "medium"
    ) -> str:
        """
        Generate natural language explanation of code

        Args:
            code: Code to explain
            language: Programming language
            detail_level: "brief", "medium", "detailed"

        Returns:
            Natural language explanation
        """
        detail_instructions = {
            "brief": "Provide a brief 2-3 sentence summary",
            "medium": "Provide a clear explanation of what the code does and how",
            "detailed": "Provide detailed explanation including logic flow, edge cases, and design decisions"
        }

        system_prompt = f"""You are a {language} code educator. Explain code clearly for developers.
{detail_instructions.get(detail_level, detail_instructions['medium'])}.

Make the explanation accessible but technically accurate."""

        user_prompt = f"""Explain this {language} code:

```{language}
{code}
```
"""

        try:
            response = await ollama_client.generate(
                prompt=user_prompt,
                context="",
                system_prompt=system_prompt,
                stream=False
            )
            return response

        except Exception as e:
            return f"Error explaining code: {e}"

    async def fix_code_errors(
        self,
        code: str,
        error_message: str,
        language: str = "python"
    ) -> Dict[str, Any]:
        """
        Fix code based on error messages

        Args:
            code: Code with errors
            error_message: Error message from execution/linting
            language: Programming language

        Returns:
            Fixed code with explanation
        """
        system_prompt = f"""You are an expert {language} debugger. Fix the code based on the error message.

Respond with JSON:
{{
  "fixed_code": "corrected code",
  "issue_identified": "what was wrong",
  "fix_explanation": "how it was fixed",
  "prevention_tip": "how to avoid this in future"
}}
"""

        user_prompt = f"""Fix this {language} code:

```{language}
{code}
```

Error message:
```
{error_message}
```
"""

        try:
            response = await ollama_client.generate(
                prompt=user_prompt,
                context="",
                system_prompt=system_prompt,
                stream=False
            )

            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(response[json_start:json_end])
                result["original_code"] = code
                result["original_error"] = error_message
                result["language"] = language
                result["timestamp"] = datetime.now().isoformat()
                return result
            else:
                return {
                    "error": "Could not parse fix result",
                    "raw_response": response
                }

        except Exception as e:
            return {
                "error": str(e),
                "language": language
            }

    async def read_file(self, file_path: str) -> Dict[str, Any]:
        """
        Read a file with syntax detection

        Args:
            file_path: Path to file (relative to workspace or absolute)

        Returns:
            File content, language, and metadata
        """
        try:
            # Resolve path
            if not Path(file_path).is_absolute():
                full_path = self.workspace_root / file_path
            else:
                full_path = Path(file_path)

            if not full_path.exists():
                return {
                    "error": f"File not found: {file_path}",
                    "exists": False
                }

            # Detect language
            suffix = full_path.suffix.lower()
            language = self.supported_languages.get(suffix, "text")

            # Read content
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Get file stats
            stats = full_path.stat()

            return {
                "path": str(full_path),
                "relative_path": str(full_path.relative_to(self.workspace_root)) if full_path.is_relative_to(self.workspace_root) else str(full_path),
                "content": content,
                "language": language,
                "lines": len(content.split('\n')),
                "size_bytes": stats.st_size,
                "modified": datetime.fromtimestamp(stats.st_mtime).isoformat(),
                "exists": True
            }

        except Exception as e:
            return {
                "error": str(e),
                "path": file_path,
                "exists": False
            }

    async def write_file(
        self,
        file_path: str,
        content: str,
        create_dirs: bool = True,
        backup: bool = True
    ) -> Dict[str, Any]:
        """
        Write content to file

        Args:
            file_path: Path to file
            content: Content to write
            create_dirs: Create parent directories if needed
            backup: Create backup of existing file

        Returns:
            Write operation result
        """
        try:
            # Resolve path
            if not Path(file_path).is_absolute():
                full_path = self.workspace_root / file_path
            else:
                full_path = Path(file_path)

            # Create parent directories
            if create_dirs:
                full_path.parent.mkdir(parents=True, exist_ok=True)

            # Backup existing file
            if backup and full_path.exists():
                backup_path = full_path.with_suffix(full_path.suffix + '.backup')
                import shutil
                shutil.copy2(full_path, backup_path)

            # Write file
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # Log operation
            operation = CodeEditOperation(
                file_path=str(full_path),
                operation="create" if not full_path.exists() else "edit",
                content=content,
                line_start=None,
                line_end=None,
                reasoning="File write operation",
                timestamp=datetime.now().isoformat()
            )
            self.edit_history.append(operation)

            return {
                "success": True,
                "path": str(full_path),
                "relative_path": str(full_path.relative_to(self.workspace_root)) if full_path.is_relative_to(self.workspace_root) else str(full_path),
                "bytes_written": len(content.encode('utf-8')),
                "lines": len(content.split('\n')),
                "backed_up": backup and full_path.exists()
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "path": file_path
            }

    async def execute_code(
        self,
        code: str,
        language: str = "python",
        timeout: int = 30,
        capture_output: bool = True
    ) -> Dict[str, Any]:
        """
        Execute code safely and return results

        Args:
            code: Code to execute
            language: Programming language
            timeout: Execution timeout in seconds
            capture_output: Whether to capture stdout/stderr

        Returns:
            Execution results including output, errors, exit code
        """
        # Language execution commands
        executors = {
            "python": ["python3", "-c", code],
            "bash": ["bash", "-c", code],
            "javascript": ["node", "-e", code],
            "go": None,  # Requires file compilation
            "rust": None  # Requires file compilation
        }

        cmd = executors.get(language)

        if cmd is None:
            return {
                "success": False,
                "error": f"Direct execution not supported for {language}. Use file-based execution.",
                "language": language
            }

        try:
            start_time = datetime.now()

            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                timeout=timeout
            )

            duration = (datetime.now() - start_time).total_seconds()

            return {
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": result.stdout if capture_output else None,
                "stderr": result.stderr if capture_output else None,
                "duration_seconds": duration,
                "language": language,
                "timestamp": datetime.now().isoformat()
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Execution timed out after {timeout} seconds",
                "language": language,
                "timeout": timeout
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": f"Interpreter/runtime not found for {language}",
                "language": language
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "language": language
            }

    async def generate_tests(
        self,
        code: str,
        language: str = "python",
        test_framework: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate unit tests for given code

        Args:
            code: Code to test
            language: Programming language
            test_framework: Specific framework (pytest, jest, etc.)

        Returns:
            Generated test code
        """
        default_frameworks = {
            "python": "pytest",
            "javascript": "jest",
            "typescript": "jest",
            "go": "testing",
            "rust": "cargo test",
            "java": "junit"
        }

        framework = test_framework or default_frameworks.get(language, "standard library")

        system_prompt = f"""You are a {language} testing expert. Generate comprehensive unit tests using {framework}.

Include:
1. Tests for normal cases
2. Edge cases
3. Error cases
4. Mock dependencies if needed

Respond with JSON:
{{
  "test_code": "complete test code",
  "test_cases": [
    {{
      "name": "test name",
      "description": "what it tests",
      "type": "normal|edge|error"
    }}
  ],
  "setup_instructions": "how to run tests",
  "dependencies": ["required", "packages"]
}}
"""

        user_prompt = f"""Generate tests for this {language} code:

```{language}
{code}
```

Use {framework} framework."""

        try:
            response = await ollama_client.generate(
                prompt=user_prompt,
                context="",
                system_prompt=system_prompt,
                stream=False
            )

            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(response[json_start:json_end])
                result["language"] = language
                result["framework"] = framework
                result["timestamp"] = datetime.now().isoformat()
                return result
            else:
                return {
                    "error": "Could not parse test generation result",
                    "raw_response": response
                }

        except Exception as e:
            return {
                "error": str(e),
                "language": language
            }

    async def code_completion(
        self,
        partial_code: str,
        cursor_position: Optional[int] = None,
        language: str = "python"
    ) -> List[str]:
        """
        Provide code completion suggestions

        Args:
            partial_code: Code written so far
            cursor_position: Position where completion is needed
            language: Programming language

        Returns:
            List of completion suggestions
        """
        system_prompt = f"""You are a {language} code completion engine. Suggest logical completions.

Provide 3-5 suggestions as JSON array:
["suggestion1", "suggestion2", "suggestion3"]
"""

        user_prompt = f"""Complete this {language} code:

```{language}
{partial_code}
```

Cursor at position: {cursor_position if cursor_position else "end"}"""

        try:
            response = await ollama_client.generate(
                prompt=user_prompt,
                context="",
                system_prompt=system_prompt,
                stream=False
            )

            # Try to extract JSON array
            json_start = response.find('[')
            json_end = response.rfind(']') + 1
            if json_start >= 0 and json_end > json_start:
                suggestions = json.loads(response[json_start:json_end])
                return suggestions if isinstance(suggestions, list) else []
            else:
                return []

        except Exception as e:
            return []

    def get_edit_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent edit history"""
        recent = self.edit_history[-limit:] if len(self.edit_history) > limit else self.edit_history
        return [
            {
                "file_path": op.file_path,
                "operation": op.operation,
                "reasoning": op.reasoning,
                "timestamp": op.timestamp
            }
            for op in recent
        ]


# Global JARCORE instance
jarcore = JARCORE()
