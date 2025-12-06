"""
Security: input sanitization and validation
"""

import re
import json
import logging
from typing import Tuple, List, Optional, Dict

from .config import CONFIG

logger = logging.getLogger("CORTANA.security")


class InputSanitizer:
    """Sanitize and validate user inputs"""

    @staticmethod
    def sanitize(text: str, max_length: int = None) -> str:
        """Sanitize text input"""
        if max_length is None:
            max_length = CONFIG["security"]["max_input_length"]

        # Truncate if too long
        if len(text) > max_length:
            logger.warning(f"Input truncated from {len(text)} to {max_length} characters")
            text = text[:max_length]

        # Remove null bytes
        text = text.replace('\x00', '')

        return text

    @staticmethod
    def check_dangerous_patterns(text: str) -> Tuple[bool, List[str]]:
        """Check for dangerous patterns"""
        if not CONFIG["security"]["sanitize_inputs"]:
            return (True, [])

        matches = []
        for pattern in CONFIG["security"]["dangerous_patterns"]:
            if re.search(pattern, text, re.IGNORECASE):
                matches.append(pattern)
                logger.warning(f"Dangerous pattern detected: {pattern}")

        return (len(matches) == 0, matches)

    @staticmethod
    def validate_json(text: str) -> Tuple[bool, Optional[Dict]]:
        """Validate JSON input"""
        try:
            data = json.loads(text)
            return (True, data)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON: {e}")
            return (False, None)
