#!/usr/bin/env python3
"""
Unit tests for CLI modules
"""
import pytest
from unittest.mock import MagicMock, patch

from cli.themes import Theme, ThemeManager


@pytest.mark.unit
def test_theme_manager_initialization():
    """Test theme manager initialization"""
    manager = ThemeManager()
    assert manager is not None
    assert len(manager.themes) > 0


@pytest.mark.unit
def test_get_theme():
    """Test getting a theme"""
    manager = ThemeManager()
    theme = manager.get_theme("matrix")
    
    assert theme is not None
    assert isinstance(theme, dict) or hasattr(theme, 'primary')


@pytest.mark.unit
def test_get_theme_default():
    """Test getting default theme for invalid name"""
    manager = ThemeManager()
    theme = manager.get_theme("nonexistent_theme")
    
    # Should return a default theme
    assert theme is not None


@pytest.mark.unit
def test_list_themes():
    """Test listing available themes"""
    manager = ThemeManager()
    themes = manager.list_themes()
    
    assert isinstance(themes, list)
    assert len(themes) > 0


@pytest.mark.unit
def test_theme_colors():
    """Test theme colors are valid"""
    manager = ThemeManager()
    
    for theme_name in manager.list_themes():
        theme = manager.get_theme(theme_name)
        assert theme is not None
