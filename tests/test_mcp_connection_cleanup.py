#!/usr/bin/env python3
"""
Unit tests for MCPConnection CancelledError handling during cleanup.

Tests verify that CancelledError exceptions are properly caught and handled
during shutdown cleanup, preventing tracebacks.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from mcp_gateway.client import MCPConnection
from mcp import StdioServerParameters


class TestMCPConnectionCleanup(unittest.IsolatedAsyncioTestCase):
    """Test CancelledError handling in MCPConnection cleanup"""

    def setUp(self):
        """Set up test fixtures"""
        self.server_params = StdioServerParameters(
            command="echo",
            args=["test"],
            env=None
        )

    async def test_aexit_handles_cancelled_error_in_session_cleanup(self):
        """Test that CancelledError during session cleanup is handled silently"""
        connection = MCPConnection(self.server_params)
        
        # Mock the session to raise CancelledError
        mock_session = AsyncMock()
        mock_session.__aexit__ = AsyncMock(side_effect=asyncio.CancelledError("Test cancellation"))
        connection.session = mock_session
        connection._entered = True
        
        # Should not raise an exception
        try:
            await connection.__aexit__(None, None, None)
        except asyncio.CancelledError:
            self.fail("CancelledError should be caught and handled silently")
        
        # Verify session cleanup was attempted (check before it's set to None)
        mock_session.__aexit__.assert_called_once()
        # Verify session was set to None after cleanup
        self.assertIsNone(connection.session)

    async def test_aexit_handles_cancelled_error_in_stdio_cleanup(self):
        """Test that CancelledError during stdio cleanup is handled silently"""
        connection = MCPConnection(self.server_params)
        
        # Mock the stdio context to raise CancelledError
        mock_stdio_ctx = AsyncMock()
        mock_stdio_ctx.__aexit__ = AsyncMock(side_effect=asyncio.CancelledError("Test cancellation"))
        connection.stdio_ctx = mock_stdio_ctx
        connection.session = None  # Session already cleaned up
        connection._entered = True
        
        # Should not raise an exception
        try:
            await connection.__aexit__(None, None, None)
        except asyncio.CancelledError:
            self.fail("CancelledError should be caught and handled silently")
        
        # Verify stdio cleanup was attempted
        mock_stdio_ctx.__aexit__.assert_called_once()
        # Verify stdio_ctx was set to None after cleanup
        self.assertIsNone(connection.stdio_ctx)

    async def test_aexit_handles_regular_exception_in_session_cleanup(self):
        """Test that regular exceptions during session cleanup are handled silently"""
        connection = MCPConnection(self.server_params)
        
        # Mock the session to raise a regular exception
        mock_session = AsyncMock()
        mock_session.__aexit__ = AsyncMock(side_effect=ValueError("Test error"))
        connection.session = mock_session
        connection._entered = True
        
        # Should not raise an exception
        try:
            await connection.__aexit__(None, None, None)
        except ValueError:
            self.fail("Regular exceptions should be caught and handled silently")
        
        # Verify session cleanup was attempted
        mock_session.__aexit__.assert_called_once()
        # Verify session was set to None after cleanup
        self.assertIsNone(connection.session)

    async def test_aexit_handles_cancelled_error_in_both_contexts(self):
        """Test that CancelledError in both session and stdio cleanup is handled"""
        connection = MCPConnection(self.server_params)
        
        # Mock both to raise CancelledError
        mock_session = AsyncMock()
        mock_session.__aexit__ = AsyncMock(side_effect=asyncio.CancelledError("Session cancelled"))
        connection.session = mock_session
        
        mock_stdio_ctx = AsyncMock()
        mock_stdio_ctx.__aexit__ = AsyncMock(side_effect=asyncio.CancelledError("Stdio cancelled"))
        connection.stdio_ctx = mock_stdio_ctx
        connection._entered = True
        
        # Should not raise an exception
        try:
            await connection.__aexit__(None, None, None)
        except asyncio.CancelledError:
            self.fail("CancelledError should be caught and handled silently")
        
        # Verify both cleanups were attempted
        mock_session.__aexit__.assert_called_once()
        mock_stdio_ctx.__aexit__.assert_called_once()
        # Verify both were set to None
        self.assertIsNone(connection.session)
        self.assertIsNone(connection.stdio_ctx)


class TestMCPClientCleanup(unittest.IsolatedAsyncioTestCase):
    """Test CancelledError handling in MCPClient cleanup"""

    async def test_cleanup_handles_cancelled_error_silently(self):
        """Test that CancelledError during cleanup is handled silently"""
        from mcp_gateway.client import MCPClient
        
        client = MCPClient()
        
        # Create a mock connection that raises CancelledError
        mock_connection = AsyncMock()
        mock_connection.__aexit__ = AsyncMock(side_effect=asyncio.CancelledError("Test cancellation"))
        
        client.connections = {"test_server": mock_connection}
        client.initialized = True
        
        # Should not raise an exception
        try:
            await client.cleanup()
        except asyncio.CancelledError:
            self.fail("CancelledError should be caught and handled silently")
        
        # Verify cleanup was attempted via disconnect_server
        # disconnect_server calls connection.__aexit__ and then removes it
        mock_connection.__aexit__.assert_called_once()
        # Verify connection was removed (disconnect_server removes it after __aexit__)
        self.assertNotIn("test_server", client.connections)
        # Verify initialized flag was reset
        self.assertFalse(client.initialized)

    async def test_cleanup_handles_regular_exception_with_message(self):
        """Test that regular exceptions during cleanup print error messages"""
        from mcp_gateway.client import MCPClient
        import io
        import sys
        
        client = MCPClient()
        
        # Create a mock connection that raises a regular exception
        mock_connection = AsyncMock()
        mock_connection.__aexit__ = AsyncMock(side_effect=ValueError("Test error"))
        
        client.connections = {"test_server": mock_connection}
        client.initialized = True
        
        # Capture stdout
        captured_output = io.StringIO()
        
        # Should not raise an exception, but should print error message
        with patch('sys.stdout', captured_output):
            try:
                await client.cleanup()
            except ValueError:
                self.fail("Regular exceptions should be caught")
        
        # Verify cleanup was attempted
        mock_connection.__aexit__.assert_called_once()
        # Verify error message was printed
        output = captured_output.getvalue()
        self.assertIn("Error disconnecting from test_server", output)
        self.assertIn("Test error", output)
        # Verify connection was removed (disconnect_server removes it even if __aexit__ raises)
        self.assertNotIn("test_server", client.connections)
        # Verify initialized flag was reset
        self.assertFalse(client.initialized)

    async def test_cleanup_handles_multiple_servers_with_cancelled_error(self):
        """Test cleanup with multiple servers where one raises CancelledError"""
        from mcp_gateway.client import MCPClient
        
        client = MCPClient()
        
        # Create two mock connections
        mock_connection1 = AsyncMock()
        mock_connection1.__aexit__ = AsyncMock(side_effect=asyncio.CancelledError("Cancelled"))
        
        mock_connection2 = AsyncMock()
        mock_connection2.__aexit__ = AsyncMock()  # Normal cleanup
        
        client.connections = {
            "server1": mock_connection1,
            "server2": mock_connection2
        }
        client.initialized = True
        
        # Should not raise an exception
        try:
            await client.cleanup()
        except asyncio.CancelledError:
            self.fail("CancelledError should be caught and handled silently")
        
        # Verify both cleanups were attempted
        mock_connection1.__aexit__.assert_called_once()
        mock_connection2.__aexit__.assert_called_once()
        # Verify all connections were removed
        self.assertEqual(len(client.connections), 0)
        # Verify initialized flag was reset
        self.assertFalse(client.initialized)


if __name__ == "__main__":
    unittest.main()
