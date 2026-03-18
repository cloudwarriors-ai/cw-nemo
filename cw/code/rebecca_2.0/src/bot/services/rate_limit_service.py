"""
Rate limiting service.

Provides consistent rate limiting across all endpoints.
Uses database storage for multi-worker compatibility.
"""

import sqlite3
import time
from typing import Optional
import logging


class RateLimitService:
    """
    Service for managing rate limits.

    Supports different rate limit types:
    - chat: Regular chat queries (default 20/hour)
    - meeting: Meeting joins (default 5/hour)
    """

    # SECURITY: Allowlist of valid table names for rate limiting.
    # Prevents SQL injection via table name interpolation.
    _ALLOWED_TABLES = frozenset({"rate_limits", "meeting_rate_limits"})

    def __init__(
        self,
        db_path: str,
        logger: Optional[logging.Logger] = None
    ):
        self.db_path = db_path
        self.logger = logger or logging.getLogger(__name__)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Ensure rate limit tables exist."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Chat rate limits
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    user_id TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_rate_limits_user
                ON rate_limits(user_id, timestamp)
            """)

            # Meeting rate limits (stricter)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meeting_rate_limits (
                    user_id TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_meeting_rate_limits_user
                ON meeting_rate_limits(user_id, timestamp)
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.warning(f"Failed to ensure rate limit tables: {e}")

    def check_chat_limit(
        self,
        user_id: str,
        limit: int = 20
    ) -> bool:
        """
        Check if user is within chat rate limits.

        Args:
            user_id: User identifier
            limit: Max requests per hour

        Returns:
            True if OK to proceed, False if rate limited
        """
        return self._check_limit(
            user_id=user_id,
            limit=limit,
            table="rate_limits"
        )

    def check_meeting_limit(
        self,
        user_id: str,
        limit: int = 5
    ) -> bool:
        """
        Check if user is within meeting rate limits.

        Args:
            user_id: User identifier
            limit: Max meeting joins per hour

        Returns:
            True if OK to proceed, False if rate limited
        """
        return self._check_limit(
            user_id=user_id,
            limit=limit,
            table="meeting_rate_limits"
        )

    def _check_limit(
        self,
        user_id: str,
        limit: int,
        table: str
    ) -> bool:
        """
        Generic rate limit check.

        Returns True if within limit and records the request.
        Returns False if limit exceeded.

        Raises:
            ValueError: If table name is not in the allowlist.
        """
        # SECURITY: Validate table name against allowlist (defense-in-depth).
        # SQLite does not support parameterized table names, so allowlist
        # validation is the appropriate security control here.
        if table not in self._ALLOWED_TABLES:
            self.logger.error(f"Invalid table name attempted: {table}")
            raise ValueError(f"Invalid rate limit table: {table}")

        if limit <= 0:
            return True  # Disabled

        now = time.time()
        hour_ago = now - 3600

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Clean old entries
            # SECURITY: Table name validated above against _ALLOWED_TABLES
            cursor.execute(
                f"DELETE FROM {table} WHERE timestamp < ?",
                (hour_ago,)
            )

            # Count recent requests
            cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id = ? AND timestamp > ?",
                (user_id, hour_ago)
            )
            count = cursor.fetchone()[0]

            if count >= limit:
                conn.close()
                return False

            # Record this request
            cursor.execute(
                f"INSERT INTO {table} (user_id, timestamp) VALUES (?, ?)",
                (user_id, now)
            )
            conn.commit()
            conn.close()
            return True

        except Exception as e:
            self.logger.error(f"Rate limit check failed: {e}")
            return False  # Fail closed - deny on error for security

    def reset_user(self, user_id: str) -> None:
        """Reset all rate limits for a user (for testing)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rate_limits WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM meeting_rate_limits WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.warning(f"Failed to reset rate limits: {e}")

    def reset_all(self) -> None:
        """Reset all rate limits (for testing)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rate_limits")
            cursor.execute("DELETE FROM meeting_rate_limits")
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.warning(f"Failed to reset all rate limits: {e}")
