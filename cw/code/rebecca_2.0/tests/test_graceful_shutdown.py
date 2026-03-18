"""
Tests for graceful shutdown handling.
"""
import signal
import threading
import time
import pytest
from unittest.mock import MagicMock, patch

from src.bot.graceful_shutdown import (
    GracefulShutdown,
    get_shutdown_handler,
    set_shutdown_handler,
    shutdown_aware,
    ShutdownInProgressError,
)


@pytest.fixture
def shutdown_handler():
    """Create a shutdown handler for testing."""
    handler = GracefulShutdown(shutdown_timeout=5)
    yield handler
    # Cleanup: reset global handler
    set_shutdown_handler(None)


class TestGracefulShutdown:
    """Tests for GracefulShutdown class."""

    def test_initial_state(self, shutdown_handler):
        """Test initial state is not shutting down."""
        assert shutdown_handler.is_shutting_down() is False
        assert shutdown_handler.get_active_requests() == 0

    def test_increment_decrement_requests(self, shutdown_handler):
        """Test request counting."""
        shutdown_handler.increment_requests()
        assert shutdown_handler.get_active_requests() == 1

        shutdown_handler.increment_requests()
        assert shutdown_handler.get_active_requests() == 2

        shutdown_handler.decrement_requests()
        assert shutdown_handler.get_active_requests() == 1

        shutdown_handler.decrement_requests()
        assert shutdown_handler.get_active_requests() == 0

    def test_decrement_below_zero(self, shutdown_handler):
        """Test decrement doesn't go below zero."""
        shutdown_handler.decrement_requests()
        assert shutdown_handler.get_active_requests() == 0

    def test_register_callback(self, shutdown_handler):
        """Test callback registration."""
        callback = MagicMock()
        shutdown_handler.register_callback(callback)

        assert len(shutdown_handler._callbacks) == 1
        assert shutdown_handler._callbacks[0] is callback

    def test_callbacks_run_on_shutdown(self, shutdown_handler):
        """Test callbacks are executed during shutdown."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        shutdown_handler.register_callback(callback1)
        shutdown_handler.register_callback(callback2)

        # Trigger internal shutdown sequence
        shutdown_handler._is_shutting_down = True
        shutdown_handler._run_callbacks()

        callback1.assert_called_once()
        callback2.assert_called_once()

    def test_callbacks_run_in_reverse_order(self, shutdown_handler):
        """Test callbacks run in LIFO order."""
        call_order = []

        def callback1():
            call_order.append(1)

        def callback2():
            call_order.append(2)

        def callback3():
            call_order.append(3)

        shutdown_handler.register_callback(callback1)
        shutdown_handler.register_callback(callback2)
        shutdown_handler.register_callback(callback3)

        shutdown_handler._run_callbacks()

        # Should be reversed: 3, 2, 1
        assert call_order == [3, 2, 1]

    def test_callback_exception_continues(self, shutdown_handler):
        """Test exception in callback doesn't stop others."""
        callback1 = MagicMock()
        callback2 = MagicMock(side_effect=ValueError("Test error"))
        callback3 = MagicMock()

        shutdown_handler.register_callback(callback1)
        shutdown_handler.register_callback(callback2)  # Will raise
        shutdown_handler.register_callback(callback3)

        shutdown_handler._run_callbacks()

        # All should be called despite exception
        callback3.assert_called_once()
        callback2.assert_called_once()
        callback1.assert_called_once()

    def test_wait_for_shutdown(self, shutdown_handler):
        """Test wait_for_shutdown blocks until signal."""
        result = []

        def waiter():
            got_signal = shutdown_handler.wait_for_shutdown(timeout=0.5)
            result.append(got_signal)

        thread = threading.Thread(target=waiter)
        thread.start()

        # Signal shutdown
        shutdown_handler._shutdown_event.set()
        thread.join()

        assert result == [True]

    def test_wait_for_shutdown_timeout(self, shutdown_handler):
        """Test wait_for_shutdown times out."""
        result = shutdown_handler.wait_for_shutdown(timeout=0.01)
        assert result is False

    def test_wait_for_requests(self, shutdown_handler):
        """Test waiting for in-flight requests."""
        shutdown_handler.increment_requests()

        # Start a thread that will decrement after a delay
        def delayed_decrement():
            time.sleep(0.1)
            shutdown_handler.decrement_requests()

        thread = threading.Thread(target=delayed_decrement)
        thread.start()

        # This should wait for the request to complete
        start = time.time()
        shutdown_handler._wait_for_requests()
        elapsed = time.time() - start

        # Should have waited at least 0.1s
        assert elapsed >= 0.1
        assert shutdown_handler.get_active_requests() == 0

        thread.join()

    def test_is_shutting_down_flag(self, shutdown_handler):
        """Test shutdown flag is set correctly."""
        assert shutdown_handler.is_shutting_down() is False

        shutdown_handler._is_shutting_down = True
        assert shutdown_handler.is_shutting_down() is True


class TestShutdownAwareDecorator:
    """Tests for shutdown_aware decorator."""

    def test_decorator_tracks_requests(self, shutdown_handler):
        """Test decorator increments/decrements requests."""
        set_shutdown_handler(shutdown_handler)

        @shutdown_aware
        def my_function():
            # During execution, request should be tracked
            assert shutdown_handler.get_active_requests() == 1
            return "result"

        result = my_function()

        assert result == "result"
        assert shutdown_handler.get_active_requests() == 0

    def test_decorator_raises_during_shutdown(self, shutdown_handler):
        """Test decorator raises when shutdown in progress."""
        set_shutdown_handler(shutdown_handler)
        shutdown_handler._is_shutting_down = True

        @shutdown_aware
        def my_function():
            return "result"

        with pytest.raises(ShutdownInProgressError):
            my_function()

    def test_decorator_decrements_on_exception(self, shutdown_handler):
        """Test decorator decrements even on exception."""
        set_shutdown_handler(shutdown_handler)

        @shutdown_aware
        def failing_function():
            assert shutdown_handler.get_active_requests() == 1
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            failing_function()

        # Request should be decremented even on error
        assert shutdown_handler.get_active_requests() == 0

    def test_decorator_works_without_handler(self):
        """Test decorator works when no handler is set."""
        set_shutdown_handler(None)

        @shutdown_aware
        def my_function():
            return "result"

        result = my_function()
        assert result == "result"


class TestGlobalHandler:
    """Tests for global handler functions."""

    def test_get_set_handler(self, shutdown_handler):
        """Test get/set global handler."""
        assert get_shutdown_handler() is None

        set_shutdown_handler(shutdown_handler)
        assert get_shutdown_handler() is shutdown_handler

        set_shutdown_handler(None)
        assert get_shutdown_handler() is None


class TestConcurrency:
    """Tests for thread-safety."""

    def test_concurrent_request_tracking(self, shutdown_handler):
        """Test request tracking is thread-safe."""
        num_threads = 10
        iterations = 100

        def worker():
            for _ in range(iterations):
                shutdown_handler.increment_requests()
                time.sleep(0.001)  # Small delay
                shutdown_handler.decrement_requests()

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # After all threads complete, count should be 0
        assert shutdown_handler.get_active_requests() == 0
