"""
Result type for standardized error handling.

Provides a consistent pattern for functions that can succeed or fail,
avoiding the inconsistent mix of:
- Returning bool
- Returning Optional[T]
- Returning dict with "error" key
- Returning tuple (success, value_or_error)
- Raising exceptions

Usage:
    from .result import Result, Ok, Err

    def fetch_user(user_id: str) -> Result[User, str]:
        if not user_id:
            return Err("User ID is required")
        user = db.get_user(user_id)
        if not user:
            return Err(f"User {user_id} not found")
        return Ok(user)

    # Using the result:
    result = fetch_user("123")
    if result.is_ok():
        user = result.unwrap()
    else:
        error_msg = result.error

    # Or with match-like pattern:
    match result:
        case Ok(user):
            print(f"Found {user.name}")
        case Err(error):
            print(f"Error: {error}")
"""
from dataclasses import dataclass
from typing import TypeVar, Generic, Union, Optional, Callable

T = TypeVar("T")  # Success type
E = TypeVar("E")  # Error type


@dataclass(frozen=True)
class Ok(Generic[T]):
    """
    Represents a successful result containing a value.

    Usage:
        result = Ok(user_data)
        if result.is_ok():
            data = result.unwrap()
    """
    value: T

    def is_ok(self) -> bool:
        """Check if result is successful."""
        return True

    def is_err(self) -> bool:
        """Check if result is an error."""
        return False

    def unwrap(self) -> T:
        """Get the success value. Raises if called on Err."""
        return self.value

    def unwrap_or(self, default: T) -> T:
        """Get the success value or a default."""
        return self.value

    def unwrap_or_else(self, fn: Callable[[], T]) -> T:
        """Get the success value or compute a default."""
        return self.value

    @property
    def error(self) -> None:
        """Get error (None for Ok)."""
        return None

    def map(self, fn: Callable[[T], "U"]) -> "Result[U, E]":
        """Transform the success value."""
        return Ok(fn(self.value))

    def map_err(self, fn: Callable[["E"], "F"]) -> "Result[T, F]":
        """Transform the error (no-op for Ok)."""
        return self  # type: ignore

    def to_dict(self) -> dict:
        """Convert to dict format for API responses."""
        return {"success": True, "value": self.value}


@dataclass(frozen=True)
class Err(Generic[E]):
    """
    Represents a failed result containing an error.

    Usage:
        result = Err("User not found")
        if result.is_err():
            print(result.error)
    """
    error: E

    def is_ok(self) -> bool:
        """Check if result is successful."""
        return False

    def is_err(self) -> bool:
        """Check if result is an error."""
        return True

    def unwrap(self) -> None:
        """Get the success value. Raises ValueError on Err."""
        raise ValueError(f"Called unwrap() on Err: {self.error}")

    def unwrap_or(self, default: T) -> T:
        """Get the success value or a default."""
        return default

    def unwrap_or_else(self, fn: Callable[[], T]) -> T:
        """Get the success value or compute a default."""
        return fn()

    @property
    def value(self) -> None:
        """Get value (None for Err)."""
        return None

    def map(self, fn: Callable[[T], "U"]) -> "Result[U, E]":
        """Transform the success value (no-op for Err)."""
        return self  # type: ignore

    def map_err(self, fn: Callable[[E], "F"]) -> "Result[T, F]":
        """Transform the error."""
        return Err(fn(self.error))

    def to_dict(self) -> dict:
        """Convert to dict format for API responses."""
        return {"success": False, "error": self.error}


# Type alias for Result
Result = Union[Ok[T], Err[E]]


def from_optional(value: Optional[T], error: E) -> Result[T, E]:
    """
    Convert an Optional value to a Result.

    Args:
        value: The optional value
        error: The error to use if value is None

    Returns:
        Ok(value) if value is not None, else Err(error)
    """
    if value is not None:
        return Ok(value)
    return Err(error)


def from_bool(success: bool, value: T = None, error: E = "Operation failed") -> Result[T, E]:
    """
    Convert a boolean success flag to a Result.

    Args:
        success: Whether the operation succeeded
        value: The success value (if any)
        error: The error message (if failed)

    Returns:
        Ok(value) if success, else Err(error)
    """
    if success:
        return Ok(value)
    return Err(error)


def from_dict(d: dict) -> Result[dict, str]:
    """
    Convert a dict with success/error keys to a Result.

    Many legacy functions return dicts like:
        {"success": True, "data": ...}
        {"success": False, "error": "..."}
        {"exists": True, ...}
        {"exists": False, "error": "..."}

    This function converts them to Result type.

    Args:
        d: Dict with success indicator and data/error

    Returns:
        Ok(d) if successful, else Err(error_message)
    """
    # Check common success patterns
    if d.get("success") is True or d.get("exists") is True:
        return Ok(d)

    # Check for error
    if d.get("success") is False or d.get("exists") is False:
        error = d.get("error", "Operation failed")
        return Err(str(error))

    # If no clear indicator, treat as success
    if "error" not in d:
        return Ok(d)

    return Err(str(d["error"]))


# Common error types for consistency
class ErrorCode:
    """Standard error codes for consistent error handling."""

    # Client errors (4xx equivalent)
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    CONFLICT = "CONFLICT"

    # Server errors (5xx equivalent)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"

    # Domain-specific
    USER_NOT_FOUND = "USER_NOT_FOUND"
    ISSUE_NOT_FOUND = "ISSUE_NOT_FOUND"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


@dataclass(frozen=True)
class AppError:
    """
    Structured error for consistent error responses.

    Includes error code, message, and optional details.
    """
    code: str
    message: str
    details: Optional[dict] = None

    def to_dict(self) -> dict:
        """Convert to dict for API responses."""
        result = {"code": self.code, "message": self.message}
        if self.details:
            result["details"] = self.details
        return result

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


# Helper functions to create common errors
def invalid_input(message: str, details: dict = None) -> Err[AppError]:
    """Create an invalid input error."""
    return Err(AppError(ErrorCode.INVALID_INPUT, message, details))


def not_found(resource: str, identifier: str = None) -> Err[AppError]:
    """Create a not found error."""
    msg = f"{resource} not found"
    if identifier:
        msg = f"{resource} '{identifier}' not found"
    return Err(AppError(ErrorCode.NOT_FOUND, msg))


def unauthorized(message: str = "Authentication required") -> Err[AppError]:
    """Create an unauthorized error."""
    return Err(AppError(ErrorCode.UNAUTHORIZED, message))


def forbidden(message: str = "Permission denied") -> Err[AppError]:
    """Create a forbidden error."""
    return Err(AppError(ErrorCode.FORBIDDEN, message))


def service_unavailable(service: str) -> Err[AppError]:
    """Create a service unavailable error."""
    return Err(AppError(
        ErrorCode.SERVICE_UNAVAILABLE,
        f"{service} service is currently unavailable"
    ))


def circuit_open(service: str) -> Err[AppError]:
    """Create a circuit breaker open error."""
    return Err(AppError(
        ErrorCode.CIRCUIT_OPEN,
        f"{service} circuit breaker is open - service temporarily unavailable"
    ))
