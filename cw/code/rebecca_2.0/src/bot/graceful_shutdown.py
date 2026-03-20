"""
Graceful shutdown handler for the QA Bot.

Handles SIGTERM and SIGINT signals to gracefully shut down the application,
ensuring:
- In-flight requests complete (up to timeout)
- Database connections are properly closed
- Async writers are flushed
- External resources are cleaned up

Usage:
    from .graceful_shutdown import GracefulShutdown

    # In create_app():
    shutdown_handler = GracefulShutdown(
        app=app,
        shutdown_timeout=30,
        logger=app.logger
    )
    shutdown_handler.register()

    # Register cleanup callbacks
    shutdown_handler.register_callback(lambda: db.close())
    shutdown_handler.register_callback(lambda: async_writer.stop())
"""
import atexit
import logging
import signal
import sys
import threading
import time
from typing import Callable, Optional, List
from functools import wraps


class GracefulShutdown:
    """
    Handles graceful shutdown of the Flask application.

    Intercepts SIGTERM and SIGINT signals to allow in-flight requests
    to complete before shutting down.
    """

    def __init__(
        self,
        app=None,
        shutdown_timeout: int = 30,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the shutdown handler.

        Args:
            app: Flask application instance
            shutdown_timeout: Max seconds to wait for cleanup (default: 30)
            logger: Logger instance
        """
        self.app = app
        self.shutdown_timeout = shutdown_timeout
        self.logger = logger or logging.getLogger(__name__)

        self._shutdown_event = threading.Event()
        self._is_shutting_down = False
        self._callbacks: List[Callable] = []
        self._original_handlers = {}
        self._active_requests = 0
        self._requests_lock = threading.Lock()

    def register(self) -> "GracefulShutdown":
        """
        Register signal handlers and shutdown hooks.

        Returns:
            self for chaining
        """
        # Register signal handlers (only on main thread)
        if threading.current_thread() is threading.main_thread():
            # Store original handlers
            self._original_handlers[signal.SIGTERM] = signal.signal(
                signal.SIGTERM, self._handle_signal
            )
            self._original_handlers[signal.SIGINT] = signal.signal(
                signal.SIGINT, self._handle_signal
            )

            self.logger.info("Graceful shutdown handlers registered")
        else:
            self.logger.warning(
                "Cannot register signal handlers from non-main thread"
            )

        # Register atexit handler as fallback
        atexit.register(self._cleanup_on_exit)

        # Register Flask shutdown callback if app provided
        if self.app:
            @self.app.teardown_appcontext
            def _teardown(exc):
                if self._is_shutting_down:
                    self._decrement_requests()

        return self

    def register_callback(self, callback: Callable) -> None:
        """
        Register a cleanup callback to run on shutdown.

        Callbacks are executed in reverse order of registration (LIFO).

        Args:
            callback: Function to call during shutdown (no arguments)
        """
        self._callbacks.append(callback)
        self.logger.debug(f"Registered shutdown callback: {callback.__name__ if hasattr(callback, '__name__') else 'anonymous'}")

    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress."""
        return self._is_shutting_down

    def wait_for_shutdown(self, timeout: float = None) -> bool:
        """
        Wait for shutdown signal.

        Useful for background threads that should stop on shutdown.

        Args:
            timeout: Max seconds to wait (None = forever)

        Returns:
            True if shutdown signal received, False on timeout
        """
        return self._shutdown_event.wait(timeout=timeout)

    def increment_requests(self) -> None:
        """Increment active request counter."""
        with self._requests_lock:
            self._active_requests += 1

    def decrement_requests(self) -> None:
        """Decrement active request counter."""
        self._decrement_requests()

    def _decrement_requests(self) -> None:
        """Internal: Decrement active request counter."""
        with self._requests_lock:
            self._active_requests = max(0, self._active_requests - 1)

    def get_active_requests(self) -> int:
        """Get count of active requests."""
        with self._requests_lock:
            return self._active_requests

    def _handle_signal(self, signum: int, frame) -> None:
        """
        Handle shutdown signal.

        Args:
            signum: Signal number
            frame: Current stack frame
        """
        signal_name = signal.Signals(signum).name
        self.logger.info(f"Received {signal_name}, initiating graceful shutdown...")

        self._is_shutting_down = True
        self._shutdown_event.set()

        # Perform shutdown in a separate thread to not block signal handler
        shutdown_thread = threading.Thread(
            target=self._perform_shutdown,
            name="shutdown-thread"
        )
        shutdown_thread.start()

        # For SIGTERM in production (Kubernetes), we need to wait
        # For SIGINT in dev, we can exit immediately after cleanup
        if signum == signal.SIGTERM:
            shutdown_thread.join(timeout=self.shutdown_timeout)

    def _perform_shutdown(self) -> None:
        """Perform the actual shutdown sequence."""
        self.logger.info("Starting shutdown sequence...")
        start_time = time.time()

        # Phase 1: Wait for in-flight requests
        self._wait_for_requests()

        # Phase 2: Run cleanup callbacks (reverse order)
        self._run_callbacks()

        elapsed = time.time() - start_time
        self.logger.info(f"Shutdown completed in {elapsed:.2f}s")

    def _wait_for_requests(self) -> None:
        """Wait for in-flight requests to complete."""
        deadline = time.time() + self.shutdown_timeout
        poll_interval = 0.5

        active = self.get_active_requests()
        if active > 0:
            self.logger.info(f"Waiting for {active} in-flight requests...")

        while time.time() < deadline:
            active = self.get_active_requests()
            if active == 0:
                self.logger.info("All in-flight requests completed")
                return

            remaining = deadline - time.time()
            self.logger.debug(f"Waiting for {active} requests ({remaining:.1f}s remaining)")
            time.sleep(min(poll_interval, remaining))

        active = self.get_active_requests()
        if active > 0:
            self.logger.warning(
                f"Shutdown timeout reached with {active} requests still in progress"
            )

    def _run_callbacks(self) -> None:
        """Run registered cleanup callbacks."""
        if not self._callbacks:
            return

        self.logger.info(f"Running {len(self._callbacks)} cleanup callbacks...")

        # Run in reverse order (LIFO)
        for callback in reversed(self._callbacks):
            try:
                callback_name = getattr(callback, "__name__", "anonymous")
                self.logger.debug(f"Running callback: {callback_name}")
                callback()
            except Exception as e:
                self.logger.error(f"Cleanup callback failed: {e}", exc_info=True)

        self.logger.info("Cleanup callbacks completed")

    def _cleanup_on_exit(self) -> None:
        """Atexit handler for cleanup."""
        if not self._is_shutting_down:
            self.logger.info("Cleanup via atexit handler")
            self._is_shutting_down = True
            self._run_callbacks()


# Global shutdown handler instance
_shutdown_handler: Optional[GracefulShutdown] = None


def get_shutdown_handler() -> Optional[GracefulShutdown]:
    """Get the global shutdown handler instance."""
    return _shutdown_handler


def set_shutdown_handler(handler: GracefulShutdown) -> None:
    """Set the global shutdown handler instance."""
    global _shutdown_handler
    _shutdown_handler = handler


def shutdown_aware(f: Callable) -> Callable:
    """
    Decorator to make a function shutdown-aware.

    The decorated function will:
    1. Increment request counter on entry
    2. Decrement request counter on exit
    3. Return early if shutdown is in progress

    Usage:
        @shutdown_aware
        def handle_request():
            # This will be tracked for graceful shutdown
            pass
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        handler = get_shutdown_handler()

        if handler and handler.is_shutting_down():
            # During shutdown, reject new requests
            raise ShutdownInProgressError("Server is shutting down")

        if handler:
            handler.increment_requests()

        try:
            return f(*args, **kwargs)
        finally:
            if handler:
                handler.decrement_requests()

    return wrapper


class ShutdownInProgressError(Exception):
    """Raised when a request is made during shutdown."""
    pass


def create_shutdown_middleware(app, shutdown_handler: GracefulShutdown):
    """
    Create Flask middleware for request tracking.

    This middleware tracks active requests for graceful shutdown.

    Usage:
        create_shutdown_middleware(app, shutdown_handler)
    """
    @app.before_request
    def _track_request_start():
        if shutdown_handler.is_shutting_down():
            from flask import jsonify
            return jsonify({"error": "Service unavailable - shutdown in progress"}), 503
        shutdown_handler.increment_requests()

    @app.teardown_request
    def _track_request_end(exc):
        shutdown_handler.decrement_requests()
