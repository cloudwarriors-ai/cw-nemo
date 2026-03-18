"""
Circuit Breaker pattern implementation for external service resilience.

Prevents cascading failures by temporarily blocking requests to failing services.
After a recovery timeout, allows limited requests through to test if service recovered.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Service failing, requests blocked with fallback
- HALF_OPEN: Testing if service recovered, limited requests allowed

Usage:
    breaker = CircuitBreaker("openrouter", failure_threshold=5)

    @breaker
    def call_api():
        return requests.post(...)

    # Or manually:
    if breaker.can_execute():
        try:
            result = call_api()
            breaker.record_success()
        except Exception as e:
            breaker.record_failure()
            raise
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, TypeVar, Generic

from .config import CircuitBreakerConfig, get_config


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitStats:
    """Statistics for a circuit breaker."""
    failures: int = 0
    successes: int = 0
    consecutive_failures: int = 0
    last_failure_time: Optional[float] = None  # monotonic time
    last_state_change: float = field(default_factory=time.monotonic)  # monotonic time
    total_blocked: int = 0


class CircuitBreaker:
    """
    Circuit breaker for external service calls.

    Automatically tracks failures and opens circuit after threshold reached.
    After recovery timeout, allows limited requests to test recovery.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = None,
        recovery_timeout: int = None,
        half_open_requests: int = None,
        logger: logging.Logger = None,
        config: CircuitBreakerConfig = None,
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Service name (for logging)
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before trying again
            half_open_requests: Requests allowed in half-open state
            logger: Logger instance
            config: Circuit breaker config (uses defaults if not provided)
        """
        self.name = name
        self.logger = logger or logging.getLogger(f"circuit_breaker.{name}")

        # Get config values
        config = config or get_config().circuit_breaker
        self.failure_threshold = failure_threshold or config.failure_threshold
        self.recovery_timeout = recovery_timeout or config.recovery_timeout_seconds
        self.half_open_requests = half_open_requests or config.half_open_requests

        # State
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._half_open_count = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            return self._state

    @property
    def stats(self) -> CircuitStats:
        """Get circuit statistics."""
        with self._lock:
            return CircuitStats(
                failures=self._stats.failures,
                successes=self._stats.successes,
                consecutive_failures=self._stats.consecutive_failures,
                last_failure_time=self._stats.last_failure_time,
                last_state_change=self._stats.last_state_change,
                total_blocked=self._stats.total_blocked,
            )

    def can_execute(self) -> bool:
        """
        Check if a request can proceed.

        Returns True if request allowed, False if blocked.
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                if self._should_attempt_recovery():
                    self._transition_to(CircuitState.HALF_OPEN)
                    self._half_open_count = 1  # Count this request as the first half-open attempt
                    return True
                self._stats.total_blocked += 1
                return False

            if self._state == CircuitState.HALF_OPEN:
                # Allow limited requests in half-open state
                if self._half_open_count < self.half_open_requests:
                    self._half_open_count += 1
                    return True
                self._stats.total_blocked += 1
                return False

            return False

    def record_success(self) -> None:
        """Record a successful request."""
        with self._lock:
            self._stats.successes += 1
            self._stats.consecutive_failures = 0

            if self._state == CircuitState.HALF_OPEN:
                # Success in half-open state, close circuit
                self._transition_to(CircuitState.CLOSED)
                self.logger.info(f"Circuit {self.name} closed (service recovered)")

    def record_failure(self) -> None:
        """Record a failed request."""
        with self._lock:
            self._stats.failures += 1
            self._stats.consecutive_failures += 1
            self._stats.last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Failure in half-open state, open circuit again
                self._transition_to(CircuitState.OPEN)
                self.logger.warning(
                    f"Circuit {self.name} reopened (recovery failed)"
                )

            elif self._state == CircuitState.CLOSED:
                if self._stats.consecutive_failures >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
                    self.logger.error(
                        f"Circuit {self.name} opened after {self.failure_threshold} failures"
                    )

    def reset(self) -> None:
        """Manually reset circuit to closed state."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._stats.consecutive_failures = 0
            self._half_open_count = 0
            self.logger.info(f"Circuit {self.name} manually reset")

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self._stats.last_failure_time is None:
            return True
        return time.monotonic() - self._stats.last_failure_time >= self.recovery_timeout

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state. Must be called with lock held."""
        self._state = new_state
        self._stats.last_state_change = time.monotonic()

    def __call__(self, func: Callable) -> Callable:
        """
        Decorator to wrap a function with circuit breaker.

        Usage:
            @breaker
            def call_api():
                ...
        """
        def wrapper(*args, **kwargs):
            if not self.can_execute():
                raise CircuitOpenError(
                    f"Circuit {self.name} is open. Service unavailable."
                )
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    def get_status(self) -> dict:
        """Get circuit status as dictionary (for health checks)."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "consecutive_failures": self._stats.consecutive_failures,
                "total_failures": self._stats.failures,
                "total_successes": self._stats.successes,
                "total_blocked": self._stats.total_blocked,
                "last_failure": self._stats.last_failure_time,
                "last_state_change": self._stats.last_state_change,
            }


class CircuitOpenError(Exception):
    """Raised when circuit is open and request is blocked."""
    pass


# Global circuit breakers for external services
_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_circuit_breaker(
    name: str,
    failure_threshold: int = None,
    recovery_timeout: int = None,
    logger: logging.Logger = None,
) -> CircuitBreaker:
    """
    Get or create a circuit breaker by name.

    Thread-safe singleton pattern per service name.

    Args:
        name: Service name (e.g., "openrouter", "github")
        failure_threshold: Override default threshold
        recovery_timeout: Override default timeout
        logger: Logger instance

    Returns:
        CircuitBreaker instance
    """
    with _breakers_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                logger=logger,
            )
        return _breakers[name]


def get_all_circuit_statuses() -> list[dict]:
    """Get status of all circuit breakers (for health check)."""
    with _breakers_lock:
        return [breaker.get_status() for breaker in _breakers.values()]


def reset_all_circuits() -> None:
    """Reset all circuit breakers (useful for testing)."""
    with _breakers_lock:
        for breaker in _breakers.values():
            breaker.reset()
        _breakers.clear()
