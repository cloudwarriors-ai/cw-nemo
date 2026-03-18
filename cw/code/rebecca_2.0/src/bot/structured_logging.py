"""
Structured logging for the QA Bot.

Provides JSON-formatted logs that can be aggregated, searched, and analyzed
by log management tools (Datadog, Splunk, ELK, CloudWatch, etc.)

Key features:
- JSON output format for log aggregation
- Request context (request_id, user_id, etc.)
- Performance metrics (duration, response_time)
- Error context (exception info, stack traces)
- Standardized field names across all services

Usage:
    from .structured_logging import get_logger, log_context

    logger = get_logger(__name__)

    # Basic logging
    logger.info("Processing query", extra={"query": text, "user_id": user_id})

    # With context manager
    with log_context(request_id=req_id, user_id=user_id):
        logger.info("Starting request")
        # All logs inside this block will have request_id and user_id

    # With timing
    with log_timing(logger, "database_query"):
        result = db.execute(query)
    # Automatically logs duration
"""
import json
import logging
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, Any, Dict
from threading import local

# Thread-local storage for log context
_log_context = local()


class StructuredFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.

    Outputs logs as JSON objects with consistent field names for log aggregation.
    """

    # Standard fields always included
    STANDARD_FIELDS = {
        "timestamp", "level", "logger", "message",
        "request_id", "user_id", "duration_ms"
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        # Base log structure
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add file location for debugging
        log_entry["location"] = {
            "file": record.filename,
            "line": record.lineno,
            "function": record.funcName
        }

        # Add thread-local context (request_id, user_id, etc.)
        context = getattr(_log_context, "data", {})
        for key, value in context.items():
            if key not in log_entry:
                log_entry[key] = value

        # Add any extra fields from the log call
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if key not in logging.LogRecord.__dict__ and key not in log_entry:
                    # Skip internal attributes
                    if not key.startswith("_") and key not in (
                        "name", "msg", "args", "created", "filename", "funcName",
                        "levelname", "levelno", "lineno", "module", "msecs",
                        "pathname", "process", "processName", "relativeCreated",
                        "stack_info", "exc_info", "exc_text", "thread", "threadName",
                        "taskName", "message"
                    ):
                        log_entry[key] = _serialize_value(value)

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info)
            }

        return json.dumps(log_entry, default=str)


class HumanReadableFormatter(logging.Formatter):
    """
    Human-readable formatter for development/console output.

    Includes color coding and structured context display.
    """

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format log record for human readability."""
        # Color for level
        color = self.COLORS.get(record.levelname, "")
        reset = self.RESET

        # Format timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Get context
        context = getattr(_log_context, "data", {})
        request_id = context.get("request_id", "")
        user_id = context.get("user_id", "")

        # Build context string
        ctx_parts = []
        if request_id:
            ctx_parts.append(f"req={request_id[:8]}")
        if user_id:
            ctx_parts.append(f"user={user_id[:8]}")

        ctx_str = f" [{', '.join(ctx_parts)}]" if ctx_parts else ""

        # Build main line
        main_line = (
            f"{timestamp} {color}{record.levelname:8}{reset} "
            f"{record.name}{ctx_str}: {record.getMessage()}"
        )

        # Add extra fields
        extra_lines = []
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                    if key not in (
                        "name", "msg", "args", "created", "filename", "funcName",
                        "levelname", "levelno", "lineno", "module", "msecs",
                        "pathname", "process", "processName", "relativeCreated",
                        "stack_info", "exc_info", "exc_text", "thread", "threadName",
                        "taskName", "message"
                    ):
                        extra_lines.append(f"  {key}={_serialize_value(value)}")

        # Add exception if present
        if record.exc_info:
            extra_lines.append("  " + "".join(traceback.format_exception(*record.exc_info)))

        if extra_lines:
            return main_line + "\n" + "\n".join(extra_lines)
        return main_line


def _serialize_value(value: Any) -> Any:
    """Serialize a value for JSON output."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    return str(value)


def get_logger(name: str, use_json: bool = None) -> logging.Logger:
    """
    Get a logger configured for structured logging.

    Args:
        name: Logger name (typically __name__)
        use_json: If True, use JSON format. If False, use human-readable.
                  If None, detect from environment (JSON in production).

    Returns:
        Configured logger instance
    """
    import os

    logger = logging.getLogger(name)

    # Only configure if no handlers
    if not logger.handlers:
        # Determine format
        if use_json is None:
            # Use JSON in production, human-readable in dev
            use_json = os.getenv("FLASK_ENV") == "production" or os.getenv("JSON_LOGS") == "true"

        handler = logging.StreamHandler(sys.stdout)

        if use_json:
            handler.setFormatter(StructuredFormatter())
        else:
            handler.setFormatter(HumanReadableFormatter())

        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

    return logger


@contextmanager
def log_context(**kwargs):
    """
    Context manager to add context to all logs within the block.

    Usage:
        with log_context(request_id="abc123", user_id="user456"):
            logger.info("Processing request")  # Includes request_id and user_id
    """
    # Get or create context dict
    if not hasattr(_log_context, "data"):
        _log_context.data = {}

    # Store old context
    old_context = _log_context.data.copy()

    # Add new context
    _log_context.data.update(kwargs)

    try:
        yield
    finally:
        # Restore old context
        _log_context.data = old_context


def set_context(**kwargs):
    """
    Set log context for the current thread.

    Useful when you want to set context once and have it persist
    across multiple function calls (e.g., in middleware).
    """
    if not hasattr(_log_context, "data"):
        _log_context.data = {}
    _log_context.data.update(kwargs)


def clear_context():
    """Clear all log context for the current thread."""
    _log_context.data = {}


@contextmanager
def log_timing(
    logger: logging.Logger,
    operation: str,
    level: int = logging.INFO,
    **extra_fields
):
    """
    Context manager to log operation duration.

    Usage:
        with log_timing(logger, "database_query", table="users"):
            result = db.execute(query)
        # Logs: "database_query completed" with duration_ms

    Args:
        logger: Logger to use
        operation: Name of the operation being timed
        level: Log level (default: INFO)
        **extra_fields: Additional fields to include in the log
    """
    start_time = time.perf_counter()

    try:
        yield
        success = True
    except Exception:
        success = False
        raise
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000

        log_data = {
            "operation": operation,
            "duration_ms": round(duration_ms, 2),
            "success": success,
            **extra_fields
        }

        logger.log(level, f"{operation} completed", extra=log_data)


def log_request(
    logger: logging.Logger,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    request_id: str = None,
    user_id: str = None,
    **extra_fields
):
    """
    Log an HTTP request with standardized fields.

    Args:
        logger: Logger to use
        method: HTTP method
        path: Request path
        status_code: Response status code
        duration_ms: Request duration in milliseconds
        request_id: Optional request ID
        user_id: Optional user ID
        **extra_fields: Additional fields
    """
    log_data = {
        "event_type": "http_request",
        "http": {
            "method": method,
            "path": path,
            "status_code": status_code
        },
        "duration_ms": round(duration_ms, 2),
    }

    if request_id:
        log_data["request_id"] = request_id
    if user_id:
        log_data["user_id"] = user_id

    log_data.update(extra_fields)

    # Determine log level based on status code
    if status_code >= 500:
        level = logging.ERROR
    elif status_code >= 400:
        level = logging.WARNING
    else:
        level = logging.INFO

    logger.log(level, f"{method} {path} {status_code}", extra=log_data)


def log_external_call(
    logger: logging.Logger,
    service: str,
    operation: str,
    duration_ms: float,
    success: bool,
    status_code: int = None,
    error: str = None,
    **extra_fields
):
    """
    Log an external service call with standardized fields.

    Args:
        logger: Logger to use
        service: Service name (e.g., "github", "zoom", "recall")
        operation: Operation performed (e.g., "fetch_issues", "send_message")
        duration_ms: Call duration in milliseconds
        success: Whether the call succeeded
        status_code: Optional HTTP status code
        error: Optional error message
        **extra_fields: Additional fields
    """
    log_data = {
        "event_type": "external_call",
        "service": service,
        "operation": operation,
        "duration_ms": round(duration_ms, 2),
        "success": success,
    }

    if status_code is not None:
        log_data["status_code"] = status_code
    if error:
        log_data["error"] = error

    log_data.update(extra_fields)

    level = logging.INFO if success else logging.WARNING
    logger.log(level, f"{service}.{operation}", extra=log_data)


def log_error(
    logger: logging.Logger,
    message: str,
    error: Exception = None,
    error_code: str = None,
    **extra_fields
):
    """
    Log an error with standardized fields.

    Args:
        logger: Logger to use
        message: Error message
        error: Optional exception
        error_code: Optional error code (e.g., "VALIDATION_FAILED")
        **extra_fields: Additional fields
    """
    log_data = {
        "event_type": "error",
    }

    if error_code:
        log_data["error_code"] = error_code

    if error:
        log_data["exception_type"] = type(error).__name__
        log_data["exception_message"] = str(error)

    log_data.update(extra_fields)

    logger.error(message, extra=log_data, exc_info=error is not None)


# Create a default logger for the package
default_logger = get_logger("qa_agent")
