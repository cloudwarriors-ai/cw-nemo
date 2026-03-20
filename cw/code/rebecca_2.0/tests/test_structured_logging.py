"""
Tests for structured logging module.
"""
import json
import logging
import pytest
from io import StringIO

from src.bot.structured_logging import (
    get_logger,
    log_context,
    set_context,
    clear_context,
    log_timing,
    log_request,
    log_external_call,
    log_error,
    StructuredFormatter,
    HumanReadableFormatter,
)


@pytest.fixture
def json_logger():
    """Create a logger with JSON output for testing."""
    logger = logging.getLogger("test_json")
    logger.handlers = []

    # Create a StringIO handler to capture output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    yield logger, stream

    # Cleanup
    clear_context()


@pytest.fixture
def human_logger():
    """Create a logger with human-readable output for testing."""
    logger = logging.getLogger("test_human")
    logger.handlers = []

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(HumanReadableFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    yield logger, stream

    clear_context()


class TestStructuredFormatter:
    """Tests for JSON structured formatter."""

    def test_basic_log_is_valid_json(self, json_logger):
        """Test basic log output is valid JSON."""
        logger, stream = json_logger

        logger.info("Test message")
        stream.flush()

        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["message"] == "Test message"
        assert log_entry["level"] == "INFO"
        assert "timestamp" in log_entry
        assert "location" in log_entry

    def test_log_with_extra_fields(self, json_logger):
        """Test extra fields are included in JSON output."""
        logger, stream = json_logger

        logger.info("Query processed", extra={
            "query": "high priority",
            "user_id": "user123",
            "duration_ms": 150.5
        })
        stream.flush()

        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["query"] == "high priority"
        assert log_entry["user_id"] == "user123"
        assert log_entry["duration_ms"] == 150.5

    def test_exception_logging(self, json_logger):
        """Test exception info is included in JSON output."""
        logger, stream = json_logger

        try:
            raise ValueError("Test error")
        except Exception:
            logger.exception("An error occurred")

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert "exception" in log_entry
        assert log_entry["exception"]["type"] == "ValueError"
        assert "Test error" in log_entry["exception"]["message"]
        assert log_entry["exception"]["traceback"] is not None


class TestHumanReadableFormatter:
    """Tests for human-readable formatter."""

    def test_basic_log_format(self, human_logger):
        """Test basic log format is human readable."""
        logger, stream = human_logger

        logger.info("Test message")
        stream.flush()

        output = stream.getvalue()
        assert "INFO" in output
        assert "Test message" in output

    def test_log_with_context(self, human_logger):
        """Test log with context shows context info."""
        logger, stream = human_logger

        with log_context(request_id="req-12345678", user_id="user-abcdefgh"):
            logger.info("Request started")

        stream.flush()
        output = stream.getvalue()

        assert "req=req-1234" in output
        assert "user=user-ab" in output


class TestLogContext:
    """Tests for log context management."""

    def test_log_context_adds_fields(self, json_logger):
        """Test log_context adds fields to all logs in block."""
        logger, stream = json_logger

        with log_context(request_id="abc123", user_id="user456"):
            logger.info("Inside context")

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["request_id"] == "abc123"
        assert log_entry["user_id"] == "user456"

    def test_log_context_removes_fields_after_block(self, json_logger):
        """Test log_context removes fields after block exits."""
        logger, stream = json_logger

        with log_context(request_id="abc123"):
            pass

        logger.info("Outside context")
        stream.flush()

        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert "request_id" not in log_entry

    def test_nested_log_context(self, json_logger):
        """Test nested log contexts work correctly."""
        logger, stream = json_logger

        with log_context(request_id="outer"):
            with log_context(user_id="inner"):
                logger.info("Nested")

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["request_id"] == "outer"
        assert log_entry["user_id"] == "inner"

    def test_set_context_persists(self, json_logger):
        """Test set_context persists across function calls."""
        logger, stream = json_logger

        set_context(request_id="persistent123")
        logger.info("First log")

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["request_id"] == "persistent123"

    def test_clear_context(self, json_logger):
        """Test clear_context removes all context."""
        logger, stream = json_logger

        set_context(request_id="abc", user_id="xyz")
        clear_context()
        logger.info("After clear")

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert "request_id" not in log_entry
        assert "user_id" not in log_entry


class TestLogTiming:
    """Tests for log_timing context manager."""

    def test_log_timing_records_duration(self, json_logger):
        """Test log_timing records operation duration."""
        logger, stream = json_logger

        import time
        with log_timing(logger, "test_operation"):
            time.sleep(0.01)  # 10ms

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["operation"] == "test_operation"
        assert "duration_ms" in log_entry
        assert log_entry["duration_ms"] >= 10
        assert log_entry["success"] is True

    def test_log_timing_on_exception(self, json_logger):
        """Test log_timing marks failure on exception."""
        logger, stream = json_logger

        with pytest.raises(ValueError):
            with log_timing(logger, "failing_operation"):
                raise ValueError("Test failure")

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["operation"] == "failing_operation"
        assert log_entry["success"] is False

    def test_log_timing_with_extra_fields(self, json_logger):
        """Test log_timing includes extra fields."""
        logger, stream = json_logger

        with log_timing(logger, "db_query", table="users", query_type="select"):
            pass

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["table"] == "users"
        assert log_entry["query_type"] == "select"


class TestLogRequest:
    """Tests for log_request function."""

    def test_log_request_basic(self, json_logger):
        """Test log_request with basic fields."""
        logger, stream = json_logger

        log_request(
            logger,
            method="GET",
            path="/api/health",
            status_code=200,
            duration_ms=15.5
        )

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["event_type"] == "http_request"
        assert log_entry["http"]["method"] == "GET"
        assert log_entry["http"]["path"] == "/api/health"
        assert log_entry["http"]["status_code"] == 200
        assert log_entry["duration_ms"] == 15.5

    def test_log_request_error_level(self, json_logger):
        """Test log_request uses error level for 5xx."""
        logger, stream = json_logger

        log_request(
            logger,
            method="POST",
            path="/api/fail",
            status_code=500,
            duration_ms=100.0
        )

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["level"] == "ERROR"

    def test_log_request_warning_level(self, json_logger):
        """Test log_request uses warning level for 4xx."""
        logger, stream = json_logger

        log_request(
            logger,
            method="GET",
            path="/api/notfound",
            status_code=404,
            duration_ms=5.0
        )

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["level"] == "WARNING"


class TestLogExternalCall:
    """Tests for log_external_call function."""

    def test_log_external_call_success(self, json_logger):
        """Test log_external_call for successful call."""
        logger, stream = json_logger

        log_external_call(
            logger,
            service="github",
            operation="fetch_issues",
            duration_ms=250.0,
            success=True,
            status_code=200
        )

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["event_type"] == "external_call"
        assert log_entry["service"] == "github"
        assert log_entry["operation"] == "fetch_issues"
        assert log_entry["duration_ms"] == 250.0
        assert log_entry["success"] is True
        assert log_entry["level"] == "INFO"

    def test_log_external_call_failure(self, json_logger):
        """Test log_external_call for failed call."""
        logger, stream = json_logger

        log_external_call(
            logger,
            service="zoom",
            operation="send_message",
            duration_ms=5000.0,
            success=False,
            error="Connection timeout"
        )

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["success"] is False
        assert log_entry["error"] == "Connection timeout"
        assert log_entry["level"] == "WARNING"


class TestLogError:
    """Tests for log_error function."""

    def test_log_error_basic(self, json_logger):
        """Test log_error with basic message."""
        logger, stream = json_logger

        log_error(logger, "Something went wrong", error_code="INTERNAL_ERROR")

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["event_type"] == "error"
        assert log_entry["error_code"] == "INTERNAL_ERROR"
        assert log_entry["level"] == "ERROR"

    def test_log_error_with_exception(self, json_logger):
        """Test log_error with exception."""
        logger, stream = json_logger

        try:
            raise ValueError("Test exception")
        except ValueError as e:
            log_error(logger, "Error occurred", error=e)

        stream.flush()
        output = stream.getvalue().strip()
        log_entry = json.loads(output)

        assert log_entry["exception_type"] == "ValueError"
        assert "Test exception" in log_entry["exception_message"]


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_logger(self):
        """Test get_logger returns a configured logger."""
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_get_logger_same_instance(self):
        """Test get_logger returns same instance for same name."""
        logger1 = get_logger("same_name")
        logger2 = get_logger("same_name")
        assert logger1 is logger2
