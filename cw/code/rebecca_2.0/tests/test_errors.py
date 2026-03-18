"""
Tests for standardized error handling module.

Tests error codes, response formatting, and user-friendly messages.
"""
import pytest
from flask import Flask

from src.bot.errors import (
    ErrorCode,
    ApiError,
    error_response,
    success_response,
    get_user_friendly_message,
    sanitize_response_text,
    sanitize_error_json,
    ERROR_STATUS_MAP,
    USER_FRIENDLY_MESSAGES,
)
from src.bot.config import HttpStatus


class TestErrorCode:
    """Tests for ErrorCode enum."""

    def test_validation_errors_defined(self):
        """Test that validation error codes are defined."""
        assert ErrorCode.VALIDATION_ERROR.value == "validation_error"
        assert ErrorCode.MISSING_FIELD.value == "missing_field"
        assert ErrorCode.INVALID_FIELD.value == "invalid_field"

    def test_auth_errors_defined(self):
        """Test that authentication error codes are defined."""
        assert ErrorCode.UNAUTHORIZED.value == "unauthorized"
        assert ErrorCode.INVALID_TOKEN.value == "invalid_token"

    def test_not_found_errors_defined(self):
        """Test that not found error codes are defined."""
        assert ErrorCode.NOT_FOUND.value == "not_found"
        assert ErrorCode.INTERN_NOT_FOUND.value == "intern_not_found"
        assert ErrorCode.MEETING_NOT_FOUND.value == "meeting_not_found"

    def test_rate_limit_errors_defined(self):
        """Test that rate limit error codes are defined."""
        assert ErrorCode.RATE_LIMITED.value == "rate_limited"
        assert ErrorCode.MEETING_RATE_LIMITED.value == "meeting_rate_limited"

    def test_server_errors_defined(self):
        """Test that server error codes are defined."""
        assert ErrorCode.INTERNAL_ERROR.value == "internal_error"
        assert ErrorCode.SERVICE_UNAVAILABLE.value == "service_unavailable"

    def test_external_service_errors_defined(self):
        """Test that external service error codes are defined."""
        assert ErrorCode.GITHUB_ERROR.value == "github_error"
        assert ErrorCode.LLM_ERROR.value == "llm_error"
        assert ErrorCode.LLM_TIMEOUT.value == "llm_timeout"


class TestErrorStatusMap:
    """Tests for error code to HTTP status mapping."""

    def test_validation_errors_map_to_400(self):
        """Test that validation errors map to 400 Bad Request."""
        assert ERROR_STATUS_MAP[ErrorCode.VALIDATION_ERROR] == HttpStatus.BAD_REQUEST
        assert ERROR_STATUS_MAP[ErrorCode.MISSING_FIELD] == HttpStatus.BAD_REQUEST

    def test_auth_errors_map_to_401(self):
        """Test that auth errors map to 401 Unauthorized."""
        assert ERROR_STATUS_MAP[ErrorCode.UNAUTHORIZED] == HttpStatus.UNAUTHORIZED

    def test_not_found_errors_map_to_404(self):
        """Test that not found errors map to 404 Not Found."""
        assert ERROR_STATUS_MAP[ErrorCode.NOT_FOUND] == HttpStatus.NOT_FOUND
        assert ERROR_STATUS_MAP[ErrorCode.INTERN_NOT_FOUND] == HttpStatus.NOT_FOUND

    def test_rate_limit_errors_map_to_429(self):
        """Test that rate limit errors map to 429 Too Many Requests."""
        assert ERROR_STATUS_MAP[ErrorCode.RATE_LIMITED] == HttpStatus.TOO_MANY_REQUESTS

    def test_server_errors_map_to_500(self):
        """Test that server errors map to 500 Internal Server Error."""
        assert ERROR_STATUS_MAP[ErrorCode.INTERNAL_ERROR] == HttpStatus.INTERNAL_ERROR
        assert ERROR_STATUS_MAP[ErrorCode.LLM_ERROR] == HttpStatus.INTERNAL_ERROR

    def test_unavailable_errors_map_to_503(self):
        """Test that unavailable errors map to 503 Service Unavailable."""
        assert ERROR_STATUS_MAP[ErrorCode.SERVICE_UNAVAILABLE] == HttpStatus.SERVICE_UNAVAILABLE
        assert ERROR_STATUS_MAP[ErrorCode.NOT_CONFIGURED] == HttpStatus.SERVICE_UNAVAILABLE


class TestApiError:
    """Tests for ApiError exception class."""

    def test_create_api_error(self):
        """Test creating an ApiError."""
        error = ApiError(
            code=ErrorCode.NOT_FOUND,
            message="User not found",
        )
        assert error.code == ErrorCode.NOT_FOUND
        assert error.message == "User not found"
        assert error.details is None
        assert error.request_id is None

    def test_api_error_with_details(self):
        """Test ApiError with details."""
        error = ApiError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid input",
            details={"field": "email", "reason": "invalid format"},
        )
        assert error.details == {"field": "email", "reason": "invalid format"}

    def test_api_error_with_request_id(self):
        """Test ApiError with request ID."""
        error = ApiError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Something went wrong",
            request_id="abc123",
        )
        assert error.request_id == "abc123"

    def test_api_error_str(self):
        """Test ApiError string representation."""
        error = ApiError(code=ErrorCode.NOT_FOUND, message="Not found")
        assert str(error) == "not_found: Not found"

    def test_api_error_status_code(self):
        """Test ApiError returns correct status code."""
        error = ApiError(code=ErrorCode.NOT_FOUND, message="Not found")
        assert error.status_code == 404

        error2 = ApiError(code=ErrorCode.RATE_LIMITED, message="Too many requests")
        assert error2.status_code == 429

    def test_api_error_to_dict(self):
        """Test ApiError converts to dictionary."""
        error = ApiError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid field",
            details={"field": "name"},
            request_id="req-123",
        )
        result = error.to_dict()

        assert result["error"]["code"] == "validation_error"
        assert result["error"]["message"] == "Invalid field"
        assert result["error"]["details"] == {"field": "name"}
        assert result["request_id"] == "req-123"

    def test_api_error_to_dict_minimal(self):
        """Test ApiError to_dict with minimal data."""
        error = ApiError(code=ErrorCode.NOT_FOUND, message="Not found")
        result = error.to_dict()

        assert result == {"error": {"code": "not_found", "message": "Not found"}}


class TestApiErrorToResponse:
    """Tests for ApiError.to_response() - requires Flask app context."""

    @pytest.fixture
    def app(self):
        """Create a Flask app for testing."""
        return Flask(__name__)

    def test_to_response_returns_tuple(self, app):
        """Test that to_response returns (response, status_code) tuple."""
        error = ApiError(code=ErrorCode.NOT_FOUND, message="Not found")

        with app.app_context():
            response, status = error.to_response()
            assert status == 404

    def test_to_response_json_body(self, app):
        """Test that response body is correct JSON."""
        error = ApiError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid input",
            request_id="test-123",
        )

        with app.app_context():
            response, status = error.to_response()
            data = response.get_json()

            assert data["error"]["code"] == "validation_error"
            assert data["error"]["message"] == "Invalid input"
            assert data["request_id"] == "test-123"


class TestErrorResponseFunction:
    """Tests for error_response() helper function."""

    @pytest.fixture
    def app(self):
        """Create a Flask app for testing."""
        return Flask(__name__)

    def test_error_response_basic(self, app):
        """Test basic error response creation."""
        with app.app_context():
            response, status = error_response(
                ErrorCode.NOT_FOUND,
                "Resource not found",
            )
            assert status == 404
            data = response.get_json()
            assert data["error"]["code"] == "not_found"
            assert data["error"]["message"] == "Resource not found"

    def test_error_response_with_details(self, app):
        """Test error response with details."""
        with app.app_context():
            response, status = error_response(
                ErrorCode.INVALID_STATUS,
                "Invalid status value",
                details={"valid_values": ["active", "inactive"]},
            )
            data = response.get_json()
            assert data["error"]["details"]["valid_values"] == ["active", "inactive"]


class TestSuccessResponseFunction:
    """Tests for success_response() helper function."""

    @pytest.fixture
    def app(self):
        """Create a Flask app for testing."""
        return Flask(__name__)

    def test_success_response_dict(self, app):
        """Test success response with dictionary data."""
        with app.app_context():
            response, status = success_response(
                {"name": "test", "count": 5},
                request_id="req-456",
            )
            assert status == 200
            data = response.get_json()
            assert data["name"] == "test"
            assert data["count"] == 5
            assert data["request_id"] == "req-456"

    def test_success_response_list(self, app):
        """Test success response with list data."""
        with app.app_context():
            response, status = success_response(
                [1, 2, 3],
                request_id="req-789",
            )
            data = response.get_json()
            assert data["data"] == [1, 2, 3]
            assert data["request_id"] == "req-789"

    def test_success_response_custom_status(self, app):
        """Test success response with custom status code."""
        with app.app_context():
            response, status = success_response(
                {"id": "new-123"},
                status_code=201,
            )
            assert status == 201


class TestUserFriendlyMessages:
    """Tests for user-friendly error messages."""

    def test_rate_limited_message(self):
        """Test rate limited user message."""
        msg = get_user_friendly_message(ErrorCode.RATE_LIMITED)
        assert "query limit" in msg.lower() or "wait" in msg.lower()

    def test_circuit_open_message(self):
        """Test circuit open user message."""
        msg = get_user_friendly_message(ErrorCode.CIRCUIT_OPEN)
        assert "unavailable" in msg.lower() or "try again" in msg.lower()

    def test_llm_timeout_message(self):
        """Test LLM timeout user message."""
        msg = get_user_friendly_message(ErrorCode.LLM_TIMEOUT)
        assert "trouble" in msg.lower() or "try" in msg.lower()

    def test_unknown_error_returns_default(self):
        """Test that unknown error returns default message."""
        # Use an error code that doesn't have a user-friendly message
        msg = get_user_friendly_message(ErrorCode.DATABASE_ERROR)
        assert msg == "An error occurred. Please try again."

    def test_custom_default_message(self):
        """Test custom default message."""
        msg = get_user_friendly_message(ErrorCode.DATABASE_ERROR, "Custom default")
        assert msg == "Custom default"

    def test_known_messages_exist(self):
        """Test that known messages are defined."""
        # These should have user-friendly messages
        assert ErrorCode.RATE_LIMITED in USER_FRIENDLY_MESSAGES
        assert ErrorCode.MEETING_RATE_LIMITED in USER_FRIENDLY_MESSAGES
        assert ErrorCode.NOT_CONFIGURED in USER_FRIENDLY_MESSAGES
        assert ErrorCode.CIRCUIT_OPEN in USER_FRIENDLY_MESSAGES
        assert ErrorCode.LLM_TIMEOUT in USER_FRIENDLY_MESSAGES


class TestSanitizeResponseText:
    """Tests for sanitize_response_text() - prevents secret leakage in logs."""

    def test_redacts_openai_keys(self):
        """Test that OpenAI-style keys are redacted."""
        text = "Error with key sk-abc123def456ghi789jkl012mno345pqr678"
        result = sanitize_response_text(text)
        assert "sk-" not in result
        assert "[REDACTED]" in result

    def test_redacts_anthropic_keys(self):
        """Test that Anthropic-style keys are redacted."""
        text = "Key: sk-ant-fake-test-placeholder-key"
        result = sanitize_response_text(text)
        assert "sk-ant" not in result
        assert "[REDACTED]" in result

    def test_redacts_bearer_tokens(self):
        """Test that Bearer tokens are redacted."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
        result = sanitize_response_text(text)
        assert "Bearer" not in result or "eyJ" not in result
        assert "[REDACTED]" in result

    def test_redacts_webhook_secrets(self):
        """Test that webhook secrets (whsec_) are redacted."""
        text = "Webhook secret: whsec_abcdefghij1234567890klmnop"
        result = sanitize_response_text(text)
        assert "whsec_" not in result
        assert "[REDACTED]" in result

    def test_redacts_github_tokens(self):
        """Test that GitHub tokens are redacted."""
        # Personal access token
        text = "Token: ghp_fakeTESTtokenPLACEHOLDERvalue0123456789ab"
        result = sanitize_response_text(text)
        assert "ghp_" not in result
        assert "[REDACTED]" in result

    def test_redacts_aws_keys(self):
        """Test that AWS access keys are redacted."""
        text = "Access key: AKIAIOSFODNN7EXAMPLE"
        result = sanitize_response_text(text)
        assert "AKIA" not in result
        assert "[REDACTED]" in result

    def test_redacts_slack_tokens(self):
        """Test that Slack tokens are redacted."""
        text = "Slack token: xoxb-fake-test-token-placeholder"
        result = sanitize_response_text(text)
        assert "xoxb-" not in result
        assert "[REDACTED]" in result

    def test_redacts_basic_auth(self):
        """Test that Basic auth headers are redacted."""
        text = "Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQxMjM0NTY3ODkw"
        result = sanitize_response_text(text)
        assert "Basic dXNl" not in result
        assert "[REDACTED]" in result

    def test_redacts_jwt_tokens(self):
        """Test that JWT tokens are redacted."""
        text = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = sanitize_response_text(text)
        assert "eyJhbGciOi" not in result
        assert "[REDACTED]" in result

    def test_redacts_long_alphanumeric_sequences(self):
        """Test that long alphanumeric strings (potential secrets) are redacted."""
        text = "Unknown key: abcdefghijklmnopqrstuvwxyz0123456789ABCD"
        result = sanitize_response_text(text)
        # 40+ character sequences should be redacted
        assert "abcdefghijklmnopqrstuvwxyz0123456789" not in result

    def test_truncates_to_max_length(self):
        """Test that output is truncated to max_length."""
        long_text = "x" * 500
        result = sanitize_response_text(long_text, max_length=200)
        assert len(result) <= 200

    def test_preserves_safe_content(self):
        """Test that normal error messages are preserved."""
        text = "Error 404: Resource not found"
        result = sanitize_response_text(text)
        assert "Error 404" in result
        assert "Resource not found" in result

    def test_handles_empty_string(self):
        """Test handling of empty string."""
        assert sanitize_response_text("") == ""

    def test_handles_none(self):
        """Test handling of None input."""
        assert sanitize_response_text(None) == ""

    def test_case_insensitive_patterns(self):
        """Test that patterns work case-insensitively."""
        text = "token: BEARER AbCdEf123456789012345678901234567890"
        result = sanitize_response_text(text)
        assert "BEARER" not in result or "AbCdEf" not in result

    def test_multiple_secrets_in_one_string(self):
        """Test that multiple secrets in one string are all redacted."""
        text = "Keys: sk-abc123456789012345678901234567890 and whsec_xyz987654321098765432109876543210"
        result = sanitize_response_text(text)
        assert "sk-" not in result
        assert "whsec_" not in result
        assert result.count("[REDACTED]") >= 2


class TestSanitizeErrorJson:
    """Tests for sanitize_error_json() - whitelist approach for JSON responses."""

    def test_keeps_safe_fields(self):
        """Test that safe fields are preserved."""
        response = {
            "error": "not_found",
            "message": "User not found",
            "code": 404,
            "type": "NotFoundError",
        }
        result = sanitize_error_json(response)
        assert result["error"] == "not_found"
        assert result["message"] == "User not found"
        assert result["code"] == 404
        assert result["type"] == "NotFoundError"

    def test_removes_unsafe_fields(self):
        """Test that unsafe fields are removed."""
        response = {
            "error": "auth_failed",
            "message": "Invalid credentials",
            "api_key": "sk-secret12345",
            "internal_trace": "stack trace...",
            "database_query": "SELECT * FROM users WHERE password='...'",
        }
        result = sanitize_error_json(response)
        assert "api_key" not in result
        assert "internal_trace" not in result
        assert "database_query" not in result

    def test_custom_safe_fields(self):
        """Test custom safe fields list."""
        response = {
            "custom_field": "value",
            "error": "test",
            "secret": "should_be_removed",
        }
        result = sanitize_error_json(response, safe_fields=("custom_field",))
        assert result == {"custom_field": "value"}
        assert "error" not in result
        assert "secret" not in result

    def test_empty_response(self):
        """Test handling of empty response."""
        result = sanitize_error_json({})
        assert result == {}

    def test_no_matching_fields(self):
        """Test when no safe fields match."""
        response = {"secret_key": "value", "internal_data": "data"}
        result = sanitize_error_json(response)
        assert result == {}
