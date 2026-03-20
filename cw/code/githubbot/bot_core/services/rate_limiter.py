"""Rate limiting service for validation requests"""
import os
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional
import redis

logger = logging.getLogger(__name__)


class ValidationRateLimiter:
    """
    Rate limits validation requests per user/channel and tracks daily budget.

    Uses Redis for distributed rate limiting across multiple workers.
    """

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """
        Initialize rate limiter.

        Args:
            redis_client: Redis client instance (if None, creates new one)
        """
        if redis_client is None:
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
            self.redis = redis.from_url(redis_url, decode_responses=True)
        else:
            self.redis = redis_client

        # Configuration from environment
        self.max_per_user_per_hour = int(
            os.getenv('MAX_VALIDATIONS_PER_USER_PER_HOUR', '10')
        )
        self.max_per_channel_per_hour = int(
            os.getenv('MAX_VALIDATIONS_PER_CHANNEL_PER_HOUR', '50')
        )
        self.daily_budget_usd = float(
            os.getenv('DAILY_VALIDATION_BUDGET_USD', '3.00')
        )

    def check_user_limit(self, user_jid: str) -> Tuple[bool, str]:
        """
        Check if user has exceeded hourly limit.

        Args:
            user_jid: User's JID

        Returns:
            Tuple of (allowed, error_message)
        """
        if not user_jid:
            return True, ""

        try:
            key = f"rate_limit:user:{user_jid}:hour"
            count = int(self.redis.get(key) or 0)

            if count >= self.max_per_user_per_hour:
                return False, (
                    f"⏸️ You've reached the limit of {self.max_per_user_per_hour} "
                    f"validations per hour. Please try again later."
                )

            # Increment with 1-hour expiry
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, 3600)
            pipe.execute()

            return True, ""

        except redis.RedisError as e:
            logger.error(f"Failed to check user rate limit: {e}", exc_info=True)
            # Fail open - allow request if Redis is down
            return True, ""

    def check_channel_limit(self, channel_jid: str) -> Tuple[bool, str]:
        """
        Check if channel has exceeded hourly limit.

        Args:
            channel_jid: Channel's JID

        Returns:
            Tuple of (allowed, error_message)
        """
        if not channel_jid:
            return True, ""

        try:
            key = f"rate_limit:channel:{channel_jid}:hour"
            count = int(self.redis.get(key) or 0)

            if count >= self.max_per_channel_per_hour:
                return False, (
                    f"⏸️ This channel has reached the limit of {self.max_per_channel_per_hour} "
                    f"validations per hour. Please try again later."
                )

            # Increment with 1-hour expiry
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, 3600)
            pipe.execute()

            return True, ""

        except redis.RedisError as e:
            logger.error(f"Failed to check channel rate limit: {e}", exc_info=True)
            # Fail open
            return True, ""

    def check_daily_budget(self) -> Tuple[bool, str]:
        """
        Check if daily validation budget exceeded.

        Returns:
            Tuple of (allowed, error_message)
        """
        try:
            key = "rate_limit:cost:daily"
            cost_today = float(self.redis.get(key) or 0)

            if cost_today >= self.daily_budget_usd:
                return False, (
                    "⏸️ Daily validation budget exceeded. "
                    "Validation temporarily disabled until tomorrow."
                )

            return True, ""

        except redis.RedisError as e:
            logger.error(f"Failed to check daily budget: {e}", exc_info=True)
            # Fail open
            return True, ""

    def record_validation_cost(self, cost_usd: float) -> None:
        """
        Record validation cost to daily budget.

        Args:
            cost_usd: Cost in USD
        """
        if cost_usd <= 0:
            return

        try:
            key = "rate_limit:cost:daily"

            # Increment cost
            pipe = self.redis.pipeline()
            pipe.incrbyfloat(key, cost_usd)

            # Expire at midnight UTC
            now = datetime.utcnow()
            midnight = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            seconds_until_midnight = int((midnight - now).total_seconds())

            pipe.expire(key, seconds_until_midnight)
            results = pipe.execute()

            new_total = results[0]
            logger.info(
                f"Recorded validation cost: ${cost_usd:.4f}. "
                f"Daily total: ${new_total:.2f} / ${self.daily_budget_usd:.2f}"
            )

        except redis.RedisError as e:
            logger.error(f"Failed to record validation cost: {e}", exc_info=True)

    def get_daily_cost(self) -> float:
        """
        Get total cost for today.

        Returns:
            Cost in USD
        """
        try:
            key = "rate_limit:cost:daily"
            return float(self.redis.get(key) or 0)
        except (ValueError, TypeError, redis.RedisError):
            return 0.0

    def get_user_remaining(self, user_jid: str) -> int:
        """
        Get remaining validations for user this hour.

        Args:
            user_jid: User's JID

        Returns:
            Number of remaining validations
        """
        try:
            key = f"rate_limit:user:{user_jid}:hour"
            used = int(self.redis.get(key) or 0)
            return max(0, self.max_per_user_per_hour - used)
        except (ValueError, TypeError, redis.RedisError):
            return self.max_per_user_per_hour

    def get_channel_remaining(self, channel_jid: str) -> int:
        """
        Get remaining validations for channel this hour.

        Args:
            channel_jid: Channel's JID

        Returns:
            Number of remaining validations
        """
        try:
            key = f"rate_limit:channel:{channel_jid}:hour"
            used = int(self.redis.get(key) or 0)
            return max(0, self.max_per_channel_per_hour - used)
        except (ValueError, TypeError, redis.RedisError):
            return self.max_per_channel_per_hour

    def reset_user_limit(self, user_jid: str) -> None:
        """
        Manually reset user's hourly limit (admin function).

        Args:
            user_jid: User's JID
        """
        try:
            key = f"rate_limit:user:{user_jid}:hour"
            self.redis.delete(key)
            logger.info(f"Reset rate limit for user {user_jid}")
        except redis.RedisError as e:
            logger.error(f"Failed to reset user limit: {e}", exc_info=True)

    def reset_daily_budget(self) -> None:
        """
        Manually reset daily budget (admin function).
        """
        try:
            key = "rate_limit:cost:daily"
            self.redis.delete(key)
            logger.info("Reset daily validation budget")
        except redis.RedisError as e:
            logger.error(f"Failed to reset daily budget: {e}", exc_info=True)


# Singleton instance
def get_rate_limiter() -> ValidationRateLimiter:
    """Get singleton rate limiter instance"""
    return ValidationRateLimiter()


rate_limiter = get_rate_limiter()
