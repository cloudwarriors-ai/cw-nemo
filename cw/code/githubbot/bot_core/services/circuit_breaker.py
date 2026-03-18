"""Redis-backed distributed circuit breaker for validation service"""
import os
import logging
from datetime import datetime, timedelta
from typing import Optional
import redis

logger = logging.getLogger(__name__)


class RedisCircuitBreaker:
    """
    Distributed circuit breaker using Redis for state management.

    States:
    - CLOSED: Normal operation, requests allowed
    - OPEN: Too many failures, requests blocked
    - HALF_OPEN: Testing if service recovered

    This works across multiple workers/processes since state is in Redis.
    """

    STATE_CLOSED = 0
    STATE_OPEN = 1
    STATE_HALF_OPEN = 2

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        key_prefix: str = 'validation:cb',
        failure_threshold: int = None,
        reset_timeout: int = None
    ):
        """
        Initialize circuit breaker.

        Args:
            redis_client: Redis client instance (if None, creates new one)
            key_prefix: Prefix for Redis keys
            failure_threshold: Number of failures before opening circuit
            reset_timeout: Seconds before attempting to close circuit
        """
        if redis_client is None:
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
            self.redis = redis.from_url(redis_url, decode_responses=True)
        else:
            self.redis = redis_client

        self.key_prefix = key_prefix
        self.failure_threshold = failure_threshold or int(
            os.getenv('CIRCUIT_BREAKER_FAILURE_THRESHOLD', '5')
        )
        self.reset_timeout = reset_timeout or int(
            os.getenv('CIRCUIT_BREAKER_RESET_TIMEOUT', '300')
        )  # 5 minutes default

        self.failures_key = f"{self.key_prefix}:failures"
        self.state_key = f"{self.key_prefix}:state"
        self.last_failure_key = f"{self.key_prefix}:last_failure"

    def record_failure(self) -> None:
        """Record a failure and potentially open the circuit"""
        try:
            pipe = self.redis.pipeline()

            # Increment failure count
            pipe.incr(self.failures_key)

            # Set last failure timestamp
            pipe.set(self.last_failure_key, datetime.utcnow().isoformat())

            # Set expiry on failures (reset after timeout)
            pipe.expire(self.failures_key, self.reset_timeout)
            pipe.expire(self.last_failure_key, self.reset_timeout)

            results = pipe.execute()
            failure_count = results[0]

            # Open circuit if threshold exceeded
            if failure_count >= self.failure_threshold:
                self.redis.set(self.state_key, self.STATE_OPEN, ex=self.reset_timeout)
                logger.warning(
                    f"Circuit breaker OPENED after {failure_count} failures "
                    f"(threshold: {self.failure_threshold})"
                )

        except redis.RedisError as e:
            logger.error(f"Failed to record circuit breaker failure: {e}", exc_info=True)

    def record_success(self) -> None:
        """Record a success and close the circuit"""
        try:
            pipe = self.redis.pipeline()
            pipe.delete(self.failures_key)
            pipe.delete(self.last_failure_key)
            pipe.set(self.state_key, self.STATE_CLOSED)
            pipe.execute()

            logger.info("Circuit breaker CLOSED after successful request")

        except redis.RedisError as e:
            logger.error(f"Failed to record circuit breaker success: {e}", exc_info=True)

    def should_attempt(self) -> bool:
        """
        Check if request should be attempted.

        Returns:
            True if request should proceed, False if blocked
        """
        try:
            state = self._get_state()

            if state == self.STATE_CLOSED:
                return True

            if state == self.STATE_OPEN:
                # Check if timeout elapsed, switch to half-open
                last_failure_str = self.redis.get(self.last_failure_key)
                if last_failure_str:
                    try:
                        last_failure = datetime.fromisoformat(last_failure_str)
                        elapsed = (datetime.utcnow() - last_failure).total_seconds()

                        if elapsed > self.reset_timeout:
                            self.redis.set(self.state_key, self.STATE_HALF_OPEN)
                            logger.info("Circuit breaker switched to HALF_OPEN state")
                            return True
                    except (ValueError, TypeError):
                        pass

                return False

            if state == self.STATE_HALF_OPEN:
                # Allow one test request
                return True

            return True

        except redis.RedisError as e:
            logger.error(f"Failed to check circuit breaker state: {e}", exc_info=True)
            # Fail open - allow request if Redis is down
            return True

    def get_status(self) -> dict:
        """
        Get circuit breaker status for monitoring.

        Returns:
            Dict with state, failure_count, last_failure
        """
        try:
            state = self._get_state()
            failure_count = int(self.redis.get(self.failures_key) or 0)
            last_failure_str = self.redis.get(self.last_failure_key)

            state_names = {
                self.STATE_CLOSED: 'CLOSED',
                self.STATE_OPEN: 'OPEN',
                self.STATE_HALF_OPEN: 'HALF_OPEN'
            }

            return {
                'state': state_names.get(state, 'UNKNOWN'),
                'state_code': state,
                'failure_count': failure_count,
                'failure_threshold': self.failure_threshold,
                'last_failure': last_failure_str,
                'reset_timeout_seconds': self.reset_timeout
            }

        except redis.RedisError as e:
            logger.error(f"Failed to get circuit breaker status: {e}", exc_info=True)
            return {
                'state': 'ERROR',
                'error': str(e)
            }

    def _get_state(self) -> int:
        """Get current circuit breaker state"""
        try:
            state_str = self.redis.get(self.state_key)
            if state_str is None:
                return self.STATE_CLOSED
            return int(state_str)
        except (ValueError, TypeError, redis.RedisError):
            return self.STATE_CLOSED

    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state"""
        try:
            pipe = self.redis.pipeline()
            pipe.delete(self.failures_key)
            pipe.delete(self.last_failure_key)
            pipe.set(self.state_key, self.STATE_CLOSED)
            pipe.execute()

            logger.info("Circuit breaker manually RESET to CLOSED state")

        except redis.RedisError as e:
            logger.error(f"Failed to reset circuit breaker: {e}", exc_info=True)


# Singleton instance for validation circuit breaker
def get_validation_circuit_breaker() -> RedisCircuitBreaker:
    """Get singleton circuit breaker instance"""
    return RedisCircuitBreaker(key_prefix='validation:cb')


validation_circuit_breaker = get_validation_circuit_breaker()
