"""
Input validation and sanitization utilities.

Extracted from app.py during Phase 3 refactoring.
"""
import threading
import time
from collections import OrderedDict
from typing import Optional

from ..config import get_config, BOT_MENTIONS

_config = get_config()


def sanitize_input(text: str, max_length: Optional[int] = None) -> str:
    """
    Sanitize user input.

    - Truncates to max length
    - Strips bot mentions
    - Removes dangerous characters

    Args:
        text: Input text to sanitize
        max_length: Maximum allowed length (defaults to config value)

    Returns:
        Sanitized text string
    """
    if not text:
        return ""

    # Use config value if not specified
    max_length = max_length or _config.input.max_input_length

    # Truncate
    text = text[:max_length]

    # Strip bot mentions from beginning
    text_lower = text.lower()
    for mention in BOT_MENTIONS:
        if text_lower.startswith(mention):
            text = text[len(mention):].lstrip()
            break

    # Strip whitespace
    text = text.strip()

    return text


class DuplicateChecker:
    """
    Thread-safe message deduplication checker.

    Uses bounded in-memory cache with TTL to prevent duplicate processing
    when Zoom sends the same webhook multiple times.

    Memory safety: Cache is bounded to max_size entries.
    Uses FIFO eviction (oldest entries removed first) when limit reached.

    Thread safety: Protected by internal lock for multi-threaded WSGI servers.
    """

    def __init__(
        self,
        max_size: int = 10_000,
        ttl_seconds: Optional[float] = None
    ):
        """
        Initialize the duplicate checker.

        Args:
            max_size: Maximum number of entries in the cache
            ttl_seconds: Time-to-live for entries (defaults to config value)
        """
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds or _config.dedup.ttl_seconds
        self._cache: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def is_duplicate(self, message_id: str) -> bool:
        """
        Check if a message has already been processed.

        Args:
            message_id: Unique identifier for the message

        Returns:
            True if message was already processed, False otherwise
        """
        current_time = time.time()

        with self._lock:
            # Evict if at max size (FIFO - oldest first)
            while len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)

            # Clean expired entries (batch limit for performance)
            keys_to_delete = []
            for k, v in self._cache.items():
                if current_time - v > self._ttl_seconds:
                    keys_to_delete.append(k)
                if len(keys_to_delete) >= 100:  # Batch cleanup limit
                    break
            for k in keys_to_delete:
                del self._cache[k]

            # Check if already processed
            if message_id in self._cache:
                return True

            # Mark as processed
            self._cache[message_id] = current_time
            return False

    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        """Return current cache size."""
        with self._lock:
            return len(self._cache)


# Module-level singleton for backwards compatibility
_default_checker: Optional[DuplicateChecker] = None
_checker_lock = threading.Lock()


def get_duplicate_checker() -> DuplicateChecker:
    """Get or create the default duplicate checker instance."""
    global _default_checker
    if _default_checker is None:
        with _checker_lock:
            if _default_checker is None:
                _default_checker = DuplicateChecker()
    return _default_checker


def is_duplicate_message(message_id: str) -> bool:
    """
    Check if a message has already been processed.

    Convenience function using the default checker.

    Args:
        message_id: Unique identifier for the message

    Returns:
        True if message was already processed, False otherwise
    """
    return get_duplicate_checker().is_duplicate(message_id)
