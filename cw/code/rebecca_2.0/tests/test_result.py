"""
Tests for Result type for standardized error handling.
"""
import pytest
from src.bot.result import (
    Ok, Err, Result,
    from_optional, from_bool, from_dict,
    ErrorCode, AppError,
    invalid_input, not_found, unauthorized, forbidden,
    service_unavailable, circuit_open
)


class TestOk:
    """Tests for Ok result type."""

    def test_ok_is_ok(self):
        """Test Ok reports is_ok as True."""
        result = Ok("success")
        assert result.is_ok() is True
        assert result.is_err() is False

    def test_ok_unwrap(self):
        """Test Ok unwrap returns value."""
        result = Ok(42)
        assert result.unwrap() == 42

    def test_ok_unwrap_or(self):
        """Test Ok unwrap_or returns value, not default."""
        result = Ok("value")
        assert result.unwrap_or("default") == "value"

    def test_ok_error_is_none(self):
        """Test Ok error property is None."""
        result = Ok("value")
        assert result.error is None

    def test_ok_map(self):
        """Test Ok map transforms value."""
        result = Ok(5)
        mapped = result.map(lambda x: x * 2)
        assert mapped.is_ok()
        assert mapped.unwrap() == 10

    def test_ok_map_err_noop(self):
        """Test Ok map_err is a no-op."""
        result = Ok("value")
        mapped = result.map_err(lambda x: x.upper())
        assert mapped.is_ok()
        assert mapped.unwrap() == "value"

    def test_ok_to_dict(self):
        """Test Ok to_dict format."""
        result = Ok({"data": 123})
        assert result.to_dict() == {"success": True, "value": {"data": 123}}


class TestErr:
    """Tests for Err result type."""

    def test_err_is_err(self):
        """Test Err reports is_err as True."""
        result = Err("failed")
        assert result.is_err() is True
        assert result.is_ok() is False

    def test_err_unwrap_raises(self):
        """Test Err unwrap raises ValueError."""
        result = Err("error message")
        with pytest.raises(ValueError) as exc_info:
            result.unwrap()
        assert "error message" in str(exc_info.value)

    def test_err_unwrap_or(self):
        """Test Err unwrap_or returns default."""
        result = Err("error")
        assert result.unwrap_or("default") == "default"

    def test_err_unwrap_or_else(self):
        """Test Err unwrap_or_else calls function."""
        result = Err("error")
        assert result.unwrap_or_else(lambda: "computed") == "computed"

    def test_err_error_property(self):
        """Test Err error property returns error."""
        result = Err("the error")
        assert result.error == "the error"

    def test_err_value_is_none(self):
        """Test Err value property is None."""
        result = Err("error")
        assert result.value is None

    def test_err_map_noop(self):
        """Test Err map is a no-op."""
        result = Err("error")
        mapped = result.map(lambda x: x * 2)
        assert mapped.is_err()
        assert mapped.error == "error"

    def test_err_map_err(self):
        """Test Err map_err transforms error."""
        result = Err("error")
        mapped = result.map_err(lambda x: x.upper())
        assert mapped.is_err()
        assert mapped.error == "ERROR"

    def test_err_to_dict(self):
        """Test Err to_dict format."""
        result = Err("something went wrong")
        assert result.to_dict() == {"success": False, "error": "something went wrong"}


class TestFromOptional:
    """Tests for from_optional converter."""

    def test_from_optional_with_value(self):
        """Test from_optional with non-None value."""
        result = from_optional("value", "error")
        assert result.is_ok()
        assert result.unwrap() == "value"

    def test_from_optional_with_none(self):
        """Test from_optional with None value."""
        result = from_optional(None, "value was none")
        assert result.is_err()
        assert result.error == "value was none"


class TestFromBool:
    """Tests for from_bool converter."""

    def test_from_bool_success(self):
        """Test from_bool with True."""
        result = from_bool(True, "data", "error")
        assert result.is_ok()
        assert result.unwrap() == "data"

    def test_from_bool_failure(self):
        """Test from_bool with False."""
        result = from_bool(False, "data", "the error")
        assert result.is_err()
        assert result.error == "the error"


class TestFromDict:
    """Tests for from_dict converter."""

    def test_from_dict_success_true(self):
        """Test from_dict with success: true."""
        result = from_dict({"success": True, "data": 123})
        assert result.is_ok()
        assert result.unwrap()["data"] == 123

    def test_from_dict_success_false(self):
        """Test from_dict with success: false."""
        result = from_dict({"success": False, "error": "failed"})
        assert result.is_err()
        assert result.error == "failed"

    def test_from_dict_exists_true(self):
        """Test from_dict with exists: true."""
        result = from_dict({"exists": True, "user": "bob"})
        assert result.is_ok()

    def test_from_dict_exists_false(self):
        """Test from_dict with exists: false."""
        result = from_dict({"exists": False, "error": "user not found"})
        assert result.is_err()
        assert result.error == "user not found"

    def test_from_dict_no_indicator_success(self):
        """Test from_dict with no success indicator but no error."""
        result = from_dict({"data": "value"})
        assert result.is_ok()

    def test_from_dict_error_key(self):
        """Test from_dict with error key."""
        result = from_dict({"error": "something broke"})
        assert result.is_err()
        assert result.error == "something broke"


class TestAppError:
    """Tests for AppError structured error type."""

    def test_app_error_creation(self):
        """Test AppError creation."""
        error = AppError(ErrorCode.NOT_FOUND, "User not found")
        assert error.code == ErrorCode.NOT_FOUND
        assert error.message == "User not found"
        assert error.details is None

    def test_app_error_with_details(self):
        """Test AppError with details."""
        error = AppError(
            ErrorCode.VALIDATION_FAILED,
            "Invalid input",
            {"field": "email", "reason": "invalid format"}
        )
        assert error.details == {"field": "email", "reason": "invalid format"}

    def test_app_error_to_dict(self):
        """Test AppError to_dict."""
        error = AppError(ErrorCode.INTERNAL_ERROR, "Something broke")
        assert error.to_dict() == {
            "code": ErrorCode.INTERNAL_ERROR,
            "message": "Something broke"
        }

    def test_app_error_to_dict_with_details(self):
        """Test AppError to_dict with details."""
        error = AppError(
            ErrorCode.INVALID_INPUT,
            "Bad request",
            {"fields": ["name", "email"]}
        )
        d = error.to_dict()
        assert d["details"] == {"fields": ["name", "email"]}

    def test_app_error_str(self):
        """Test AppError string representation."""
        error = AppError(ErrorCode.TIMEOUT, "Request timed out")
        assert str(error) == "[TIMEOUT] Request timed out"


class TestErrorHelpers:
    """Tests for error helper functions."""

    def test_invalid_input(self):
        """Test invalid_input helper."""
        result = invalid_input("Missing required field")
        assert result.is_err()
        assert result.error.code == ErrorCode.INVALID_INPUT
        assert "Missing required field" in result.error.message

    def test_not_found_basic(self):
        """Test not_found helper without identifier."""
        result = not_found("User")
        assert result.is_err()
        assert result.error.code == ErrorCode.NOT_FOUND
        assert "User not found" in result.error.message

    def test_not_found_with_identifier(self):
        """Test not_found helper with identifier."""
        result = not_found("User", "user123")
        assert result.is_err()
        assert "user123" in result.error.message

    def test_unauthorized(self):
        """Test unauthorized helper."""
        result = unauthorized()
        assert result.is_err()
        assert result.error.code == ErrorCode.UNAUTHORIZED

    def test_forbidden(self):
        """Test forbidden helper."""
        result = forbidden("Admin access required")
        assert result.is_err()
        assert result.error.code == ErrorCode.FORBIDDEN
        assert "Admin access required" in result.error.message

    def test_service_unavailable(self):
        """Test service_unavailable helper."""
        result = service_unavailable("GitHub")
        assert result.is_err()
        assert result.error.code == ErrorCode.SERVICE_UNAVAILABLE
        assert "GitHub" in result.error.message

    def test_circuit_open(self):
        """Test circuit_open helper."""
        result = circuit_open("n8n")
        assert result.is_err()
        assert result.error.code == ErrorCode.CIRCUIT_OPEN
        assert "n8n" in result.error.message


class TestResultPatternUsage:
    """Integration tests showing Result pattern usage."""

    def test_chaining_operations(self):
        """Test chaining multiple Result operations."""
        def get_user_age(user_id: str) -> Result:
            if user_id == "123":
                return Ok({"id": "123", "name": "Alice", "age": 30})
            return Err("User not found")

        def validate_adult(user: dict) -> Result:
            if user.get("age", 0) >= 18:
                return Ok(user)
            return Err("User is not an adult")

        # Success case
        result = get_user_age("123")
        assert result.is_ok()

        user = result.unwrap()
        adult_result = validate_adult(user)
        assert adult_result.is_ok()

        # Failure case
        result = get_user_age("456")
        assert result.is_err()
        assert result.error == "User not found"

    def test_unwrap_or_pattern(self):
        """Test unwrap_or for default values."""
        def maybe_get_config(key: str) -> Result:
            configs = {"debug": True}
            if key in configs:
                return Ok(configs[key])
            return Err(f"Config {key} not found")

        # Use default when not found
        debug = maybe_get_config("debug").unwrap_or(False)
        assert debug is True

        production = maybe_get_config("production").unwrap_or(False)
        assert production is False
