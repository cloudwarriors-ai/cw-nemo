"""
Utility functions for QA Continuity Agent.

Includes:
- Retry logic with exponential backoff
- Structured logging configuration
- Rate limit handling
"""
import functools
import logging
import os
import random
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Callable, TypeVar

T = TypeVar("T")


# Exit codes for Task Scheduler integration
class ExitCode:
    SUCCESS = 0
    CONFIG_ERROR = 1
    GITHUB_ERROR = 2
    ZOOM_ERROR = 3
    RATE_LIMITED = 4
    UNKNOWN_ERROR = 5


def setup_logging(
    log_file: str = "qa_agent.log",
    log_dir: str = None,
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    backup_count: int = 30,  # Keep 30 days
) -> logging.Logger:
    """
    Configure structured logging with file rotation.

    Args:
        log_file: Name of the log file
        log_dir: Directory for log files (defaults to current directory)
        level: Logging level
        max_bytes: Max size before rotation
        backup_count: Number of backup files to keep

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger("qa_agent")
    logger.setLevel(level)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Log format with timestamp, level, and message
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler with rotation
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, log_file)
    else:
        log_path = log_file

    try:
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info(f"Logging to file: {log_path}")
    except Exception as e:
        logger.warning(f"Could not create log file: {e}. Logging to console only.")

    return logger


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,),
    logger: logging.Logger = None,
) -> Callable:
    """
    Decorator for retrying functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential calculation
        jitter: Add random jitter to prevent thundering herd
        exceptions: Tuple of exceptions to catch and retry
        logger: Logger instance for retry messages

    Returns:
        Decorated function
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            log = logger or logging.getLogger("qa_agent")
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        log.error(f"{func.__name__} failed after {max_retries + 1} attempts: {e}")
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)

                    # Add jitter (0-50% of delay)
                    if jitter:
                        delay = delay * (1 + random.random() * 0.5)

                    log.warning(
                        f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)

            raise last_exception

        return wrapper
    return decorator


def wait_for_rate_limit_reset(reset_timestamp: datetime, logger: logging.Logger = None) -> None:
    """
    Wait until GitHub rate limit resets.

    Args:
        reset_timestamp: When the rate limit resets
        logger: Logger instance
    """
    log = logger or logging.getLogger("qa_agent")
    now = datetime.now()

    if reset_timestamp > now:
        wait_seconds = (reset_timestamp - now).total_seconds() + 5  # Add 5s buffer
        log.warning(f"Rate limit exceeded. Waiting {wait_seconds:.0f}s until reset...")
        time.sleep(wait_seconds)
        log.info("Rate limit reset. Resuming...")


def redact_token(token: str) -> str:
    """Redact a token for safe logging."""
    if not token:
        return "<empty>"
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


def validate_token_format(token: str, token_name: str = "token") -> bool:
    """
    Validate token format (basic checks).

    Args:
        token: The token to validate
        token_name: Name for error messages

    Returns:
        True if valid, raises ValueError if not
    """
    if not token:
        raise ValueError(f"{token_name} is required but not set")

    if len(token) < 10:
        raise ValueError(f"{token_name} appears too short to be valid")

    if " " in token or "\n" in token:
        raise ValueError(f"{token_name} contains invalid characters (spaces/newlines)")

    return True
