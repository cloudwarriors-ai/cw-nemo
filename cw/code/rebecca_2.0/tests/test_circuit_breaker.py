"""
Tests for circuit breaker pattern implementation.

Tests circuit breaker states, transitions, and recovery behavior.
"""
import pytest
import time
from unittest.mock import Mock, patch

from src.bot.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
    get_circuit_breaker,
    get_all_circuit_statuses,
    reset_all_circuits,
)


class TestCircuitBreakerStates:
    """Tests for circuit breaker state management."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker for testing."""
        reset_all_circuits()
        return CircuitBreaker(
            name="test",
            failure_threshold=3,
            recovery_timeout=1,  # Short timeout for testing
            half_open_requests=1,
        )

    def test_initial_state_is_closed(self, breaker):
        """Test that circuit starts in closed state."""
        assert breaker.state == CircuitState.CLOSED
        assert breaker.can_execute()

    def test_success_keeps_circuit_closed(self, breaker):
        """Test that successes keep the circuit closed."""
        breaker.record_success()
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.stats.successes == 2
        assert breaker.stats.consecutive_failures == 0

    def test_failures_open_circuit_at_threshold(self, breaker):
        """Test that circuit opens after threshold failures."""
        for _ in range(3):  # Threshold is 3
            breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert not breaker.can_execute()

    def test_open_circuit_blocks_requests(self, breaker):
        """Test that open circuit blocks requests."""
        # Open the circuit
        for _ in range(3):
            breaker.record_failure()

        assert not breaker.can_execute()
        assert breaker.stats.total_blocked == 1

    def test_circuit_transitions_to_half_open(self, breaker):
        """Test that circuit transitions to half-open after recovery timeout."""
        # Open the circuit
        for _ in range(3):
            breaker.record_failure()

        # Wait for recovery timeout
        time.sleep(1.1)

        # Should now allow request and be in half-open
        assert breaker.can_execute()
        assert breaker.state == CircuitState.HALF_OPEN

    def test_success_in_half_open_closes_circuit(self, breaker):
        """Test that success in half-open state closes the circuit."""
        # Open the circuit
        for _ in range(3):
            breaker.record_failure()

        # Wait for recovery timeout
        time.sleep(1.1)

        # Should transition to half-open on can_execute
        breaker.can_execute()
        assert breaker.state == CircuitState.HALF_OPEN

        # Success should close it
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_failure_in_half_open_reopens_circuit(self, breaker):
        """Test that failure in half-open state reopens the circuit."""
        # Open the circuit
        for _ in range(3):
            breaker.record_failure()

        # Wait for recovery timeout
        time.sleep(1.1)

        # Transition to half-open
        breaker.can_execute()
        assert breaker.state == CircuitState.HALF_OPEN

        # Failure should reopen
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerReset:
    """Tests for circuit breaker reset functionality."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker for testing."""
        reset_all_circuits()
        return CircuitBreaker(
            name="test-reset",
            failure_threshold=3,
            recovery_timeout=60,  # Long timeout
        )

    def test_reset_closes_circuit(self, breaker):
        """Test that reset closes an open circuit."""
        # Open the circuit
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Reset
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.can_execute()


class TestCircuitBreakerDecorator:
    """Tests for circuit breaker as decorator."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker for testing."""
        reset_all_circuits()
        return CircuitBreaker(
            name="test-decorator",
            failure_threshold=2,
            recovery_timeout=60,
        )

    def test_decorator_passes_through_on_success(self, breaker):
        """Test that decorator passes through successful calls."""
        @breaker
        def successful_func():
            return "success"

        result = successful_func()
        assert result == "success"
        assert breaker.stats.successes == 1

    def test_decorator_records_failure_on_exception(self, breaker):
        """Test that decorator records failure on exception."""
        @breaker
        def failing_func():
            raise ValueError("test error")

        with pytest.raises(ValueError):
            failing_func()

        assert breaker.stats.failures == 1
        assert breaker.stats.consecutive_failures == 1

    def test_decorator_raises_circuit_open_error(self, breaker):
        """Test that decorator raises CircuitOpenError when circuit is open."""
        @breaker
        def some_func():
            return "result"

        # Open the circuit
        for _ in range(2):
            breaker.record_failure()

        with pytest.raises(CircuitOpenError):
            some_func()


class TestCircuitBreakerStats:
    """Tests for circuit breaker statistics."""

    def test_get_status_returns_dict(self):
        """Test that get_status returns proper dictionary."""
        reset_all_circuits()
        breaker = CircuitBreaker(name="test-status", failure_threshold=3)

        breaker.record_success()
        breaker.record_failure()

        status = breaker.get_status()

        assert status["name"] == "test-status"
        assert status["state"] == "closed"
        assert status["total_successes"] == 1
        assert status["total_failures"] == 1
        assert status["consecutive_failures"] == 1
        assert status["total_blocked"] == 0


class TestCircuitBreakerGlobalFunctions:
    """Tests for global circuit breaker management functions."""

    def test_get_circuit_breaker_creates_new(self):
        """Test that get_circuit_breaker creates new breaker."""
        reset_all_circuits()
        breaker = get_circuit_breaker("new-service")
        assert breaker is not None
        assert breaker.name == "new-service"

    def test_get_circuit_breaker_returns_same_instance(self):
        """Test that get_circuit_breaker returns same instance for same name."""
        reset_all_circuits()
        breaker1 = get_circuit_breaker("same-service")
        breaker2 = get_circuit_breaker("same-service")
        assert breaker1 is breaker2

    def test_get_all_circuit_statuses(self):
        """Test that get_all_circuit_statuses returns all breakers."""
        reset_all_circuits()
        get_circuit_breaker("service-1")
        get_circuit_breaker("service-2")

        statuses = get_all_circuit_statuses()
        assert len(statuses) == 2
        names = [s["name"] for s in statuses]
        assert "service-1" in names
        assert "service-2" in names

    def test_reset_all_circuits(self):
        """Test that reset_all_circuits clears all breakers."""
        get_circuit_breaker("to-clear-1")
        get_circuit_breaker("to-clear-2")

        reset_all_circuits()

        statuses = get_all_circuit_statuses()
        assert len(statuses) == 0


class TestCircuitBreakerHalfOpenLimit:
    """Tests for half-open request limiting."""

    def test_half_open_limits_requests(self):
        """Test that half-open state limits concurrent requests."""
        reset_all_circuits()
        breaker = CircuitBreaker(
            name="test-half-open",
            failure_threshold=2,
            recovery_timeout=0.01,  # Very short recovery for testing
            half_open_requests=1,  # Only 1 request allowed
        )

        # Open circuit
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout to pass
        time.sleep(0.02)

        # First request should be allowed (triggers half-open)
        assert breaker.can_execute()
        assert breaker.state == CircuitState.HALF_OPEN

        # Second request should be blocked (already at limit)
        assert not breaker.can_execute()
        assert breaker.stats.total_blocked == 1


class TestCircuitBreakerThreadSafety:
    """Tests for thread safety (basic checks)."""

    def test_concurrent_access(self):
        """Test basic concurrent access doesn't crash."""
        import threading
        reset_all_circuits()

        breaker = CircuitBreaker(name="test-thread", failure_threshold=100)
        errors = []

        def record_operations():
            try:
                for _ in range(100):
                    breaker.record_success()
                    breaker.record_failure()
                    breaker.can_execute()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_operations) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Just verify no crash, exact counts may vary
        assert breaker.stats.successes > 0
        assert breaker.stats.failures > 0
