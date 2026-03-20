"""
Database-backed rate limiting utilities.

Extracted from app.py during Phase 3 refactoring.
"""
import sqlite3
import time
from typing import Optional

from flask import Flask


def check_rate_limit_db(
    app: Flask,
    user_id: str,
    table: str = "rate_limits",
    limit: Optional[int] = None,
    window_seconds: int = 3600
) -> bool:
    """
    Check if user is within rate limits using database.

    Works correctly with multiple workers by using database-level
    tracking instead of in-memory state.

    Args:
        app: Flask application
        user_id: User identifier to check
        table: Rate limit table name (must be in allowlist)
        limit: Maximum requests allowed (defaults to RATE_LIMIT config)
        window_seconds: Time window in seconds (default 1 hour)

    Returns:
        True if OK (within limit), False if rate limited

    Note:
        SECURITY: Table names are validated against an allowlist internally.
        Only "rate_limits" and "meeting_rate_limits" are allowed.
    """
    # SECURITY: Validate table name against allowlist
    ALLOWED_TABLES = frozenset({"rate_limits", "meeting_rate_limits"})
    if table not in ALLOWED_TABLES:
        app.logger.error(f"Invalid rate limit table: {table}")
        return False  # Fail closed for security

    db_path = app.config["DB_PATH"]
    rate_limit = limit if limit is not None else app.config.get("RATE_LIMIT", 20)

    # Rate limit disabled if 0 or negative
    if rate_limit <= 0:
        return True

    now = time.time()
    window_start = now - window_seconds

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Clean old entries
        cursor.execute(
            f"DELETE FROM {table} WHERE timestamp < ?",
            (window_start,)
        )

        # Count recent requests
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE user_id = ? AND timestamp > ?",
            (user_id, window_start)
        )
        count = cursor.fetchone()[0]

        if count >= rate_limit:
            conn.close()
            return False

        # Add new entry
        cursor.execute(
            f"INSERT INTO {table} (user_id, timestamp) VALUES (?, ?)",
            (user_id, now)
        )
        conn.commit()
        conn.close()
        return True

    except Exception as e:
        app.logger.error(f"Rate limit check failed: {e}")
        return False  # Fail closed - deny on error for security


def check_chat_rate_limit(app: Flask, user_id: str) -> bool:
    """
    Check if user is within chat rate limits.

    Convenience function for chat message rate limiting.

    Args:
        app: Flask application
        user_id: User identifier to check

    Returns:
        True if OK (within limit), False if rate limited
    """
    return check_rate_limit_db(
        app=app,
        user_id=user_id,
        table="rate_limits",
        limit=app.config.get("RATE_LIMIT", 20)
    )


def check_meeting_rate_limit(app: Flask, user_id: str) -> bool:
    """
    Check if user is within meeting rate limits.

    Meetings are more expensive (Recall.ai API costs), so we have
    a stricter limit (default: 5 meeting joins per hour).

    Args:
        app: Flask application
        user_id: User identifier to check

    Returns:
        True if OK (within limit), False if rate limited
    """
    return check_rate_limit_db(
        app=app,
        user_id=user_id,
        table="meeting_rate_limits",
        limit=app.config.get("MEETING_RATE_LIMIT", 5)
    )
