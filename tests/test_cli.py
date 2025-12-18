#!/usr/bin/env python3
"""
Unit tests for CLI modules
"""
import pytest
from unittest.mock import MagicMock, patch

from cli.themes import ThemeManager


@pytest.mark.unit
def test_theme_manager_initialization():
    """Test theme manager initialization"""
    manager = ThemeManager()
    assert manager is not None
    assert manager.current_theme is not None


@pytest.mark.unit
def test_get_color():
    """Test getting a color from theme"""
    manager = ThemeManager()
    color = manager.get_color("primary")
    
    assert color is not None
    assert isinstance(color, str)


@pytest.mark.unit
def test_set_theme():
    """Test setting a theme"""
    manager = ThemeManager()
    
    # Try to set a theme (if themes exist)
    from config import THEMES
    if THEMES:
        theme_name = list(THEMES.keys())[0]
        result = manager.set_theme(theme_name)
        assert result is True


@pytest.mark.unit
def test_set_invalid_theme():
    """Test setting an invalid theme"""
    manager = ThemeManager()
    result = manager.set_theme("nonexistent_theme")
    
    assert result is False

