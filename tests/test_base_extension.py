"""
Unit tests for extensions.base — BaseExtension abstract base class.
"""

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from extensions.base import BaseExtension


class TestBaseExtension:
    """Verify the ABC contract enforced by BaseExtension."""

    def test_cannot_instantiate_directly(self):
        """BaseExtension itself should not be instantiable."""
        with pytest.raises(TypeError):
            BaseExtension()

    def test_incomplete_subclass_raises(self):
        """A subclass missing abstract methods cannot be instantiated."""

        class Partial(BaseExtension):
            async def initialize(self):
                pass
            # missing stop, is_running, status

        with pytest.raises(TypeError):
            Partial()

    def test_complete_subclass_instantiates(self):
        """A subclass implementing all abstract methods works fine."""

        class Complete(BaseExtension):
            async def initialize(self):
                pass

            async def stop(self):
                pass

            def is_running(self) -> bool:
                return False

            def status(self) -> Dict[str, Any]:
                return {"state": "idle"}

        ext = Complete()
        assert ext.is_running() is False
        assert ext.status() == {"state": "idle"}

    @pytest.mark.asyncio
    async def test_lifecycle_methods(self):
        """initialize() and stop() should be callable."""
        started = False

        class Lifecycle(BaseExtension):
            async def initialize(self):
                nonlocal started
                started = True

            async def stop(self):
                nonlocal started
                started = False

            def is_running(self) -> bool:
                return started

            def status(self) -> Dict[str, Any]:
                return {"running": started}

        ext = Lifecycle()
        assert ext.is_running() is False
        await ext.initialize()
        assert ext.is_running() is True
        assert ext.status() == {"running": True}
        await ext.stop()
        assert ext.is_running() is False

    def test_required_methods_exist(self):
        """BaseExtension should declare the four abstract methods."""
        abstracts = BaseExtension.__abstractmethods__
        expected = {"initialize", "stop", "is_running", "status"}
        assert expected.issubset(abstracts)
