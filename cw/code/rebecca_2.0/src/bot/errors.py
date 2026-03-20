"""
Standardized error handling and response formatting.

Provides consistent error responses across all API endpoints with:
- Standard error structure
- Request ID tracking
- Safe error messages (no internal details exposed)
- HTTP status code mapping

Usage:
    from .errors import ApiError, error_response, ErrorCode

    # Raise in route handlers:
    raise ApiError(ErrorCode.NOT_FOUND, "Intern not found", details={"id": intern_id})

    # Or create response directly:
    return error_response(ErrorCode.BAD_REQUEST, "Missing required field", request_id)
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
from flask import jsonify

from .config import HttpStatus


class ErrorCode(Enum):
    """
    Standardized error codes for API responses.

    Format: CATEGORY_SPECIFIC_ERROR
    """
    # Validation errors (400)
    VALIDATION_ERROR = "validation_error"
    MISSING_FIELD = "missing_field"
    INVALID_FIELD = "invalid_field"
    INVALID_STATUS = "invalid_status"

    # Authentication errors (401)
    UNAUTHORIZED = "unauthorized"
    INVALID_TOKEN = "invalid_token"

    # Not found errors (404)
    NOT_FOUND = "not_found"
    RESOURCE_NOT_FOUND = "resource_not_found"
    INTERN_NOT_FOUND = "intern_not_found"
    MEETING_NOT_FOUND = "meeting_not_found"
    EXECUTION_NOT_FOUND = "execution_not_found"

    # Rate limiting (429)
    RATE_LIMITED = "rate_limited"
    MEETING_RATE_LIMITED = "meeting_rate_limited"

    # Server errors (500)
    INTERNAL_ERROR = "internal_error"
    DATABASE_ERROR = "database_error"
    CACHE_ERROR = "cache_error"

    # Service unavailable (503)
    SERVICE_UNAVAILABLE = "service_unavailable"
    NOT_CONFIGURED = "not_configured"
    CIRCUIT_OPEN = "circuit_open"

    # External service errors
    GITHUB_ERROR = "github_error"
    LLM_ERROR = "llm_error"
    LLM_TIMEOUT = "llm_timeout"
    RECALL_ERROR = "recall_error"
    N8N_ERROR = "n8n_error"


# Map error codes to HTTP status codes
ERROR_STATUS_MAP = {
    # 400 Bad Request
    ErrorCode.VALIDATION_ERROR: HttpStatus.BAD_REQUEST,
    ErrorCode.MISSING_FIELD: HttpStatus.BAD_REQUEST,
    ErrorCode.INVALID_FIELD: HttpStatus.BAD_REQUEST,
    ErrorCode.INVALID_STATUS: HttpStatus.BAD_REQUEST,

    # 401 Unauthorized
    ErrorCode.UNAUTHORIZED: HttpStatus.UNAUTHORIZED,
    ErrorCode.INVALID_TOKEN: HttpStatus.UNAUTHORIZED,

    # 404 Not Found
    ErrorCode.NOT_FOUND: HttpStatus.NOT_FOUND,
    ErrorCode.RESOURCE_NOT_FOUND: HttpStatus.NOT_FOUND,
    ErrorCode.INTERN_NOT_FOUND: HttpStatus.NOT_FOUND,
    ErrorCode.MEETING_NOT_FOUND: HttpStatus.NOT_FOUND,
    ErrorCode.EXECUTION_NOT_FOUND: HttpStatus.NOT_FOUND,

    # 429 Too Many Requests
    ErrorCode.RATE_LIMITED: HttpStatus.TOO_MANY_REQUESTS,
    ErrorCode.MEETING_RATE_LIMITED: HttpStatus.TOO_MANY_REQUESTS,

    # 500 Internal Server Error
    ErrorCode.INTERNAL_ERROR: HttpStatus.INTERNAL_ERROR,
    ErrorCode.DATABASE_ERROR: HttpStatus.INTERNAL_ERROR,
    ErrorCode.CACHE_ERROR: HttpStatus.INTERNAL_ERROR,
    ErrorCode.GITHUB_ERROR: HttpStatus.INTERNAL_ERROR,
    ErrorCode.LLM_ERROR: HttpStatus.INTERNAL_ERROR,
    ErrorCode.LLM_TIMEOUT: HttpStatus.INTERNAL_ERROR,
    ErrorCode.RECALL_ERROR: HttpStatus.INTERNAL_ERROR,
    ErrorCode.N8N_ERROR: HttpStatus.INTERNAL_ERROR,

    # 503 Service Unavailable
    ErrorCode.SERVICE_UNAVAILABLE: HttpStatus.SERVICE_UNAVAILABLE,
    ErrorCode.NOT_CONFIGURED: HttpStatus.SERVICE_UNAVAILABLE,
    ErrorCode.CIRCUIT_OPEN: HttpStatus.SERVICE_UNAVAILABLE,
}


@dataclass
class ApiError(Exception):
    """
    Standard API error that can be raised and caught by error handlers.

    Usage:
        raise ApiError(ErrorCode.NOT_FOUND, "Meeting not found")
        raise ApiError(ErrorCode.VALIDATION_ERROR, "Invalid status", details={"valid": ["active", "inactive"]})
    """
    code: ErrorCode
    message: str
    details: Optional[dict] = None
    request_id: Optional[str] = None

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"

    @property
    def status_code(self) -> int:
        """Get HTTP status code for this error."""
        return ERROR_STATUS_MAP.get(self.code, HttpStatus.INTERNAL_ERROR)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON response."""
        result = {
            "error": {
                "code": self.code.value,
                "message": self.message,
            }
        }
        if self.details:
            result["error"]["details"] = self.details
        if self.request_id:
            result["request_id"] = self.request_id
        return result

    def to_response(self):
        """Convert to Flask JSON response tuple."""
        return jsonify(self.to_dict()), self.status_code


def error_response(
    code: ErrorCode,
    message: str,
    request_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> tuple:
    """
    Create a standardized error response.

    Args:
        code: Error code enum value
        message: Human-readable error message
        request_id: Request ID for tracking
        details: Additional error details (optional)

    Returns:
        Tuple of (JSON response, HTTP status code)
    """
    error = ApiError(
        code=code,
        message=message,
        details=details,
        request_id=request_id,
    )
    return error.to_response()


def success_response(
    data: Any,
    status_code: int = HttpStatus.OK,
    request_id: Optional[str] = None,
) -> tuple:
    """
    Create a standardized success response.

    Args:
        data: Response data (dict or list)
        status_code: HTTP status code (default: 200)
        request_id: Request ID for tracking

    Returns:
        Tuple of (JSON response, HTTP status code)
    """
    if isinstance(data, dict):
        if request_id and "request_id" not in data:
            data["request_id"] = request_id
        return jsonify(data), status_code
    return jsonify({"data": data, "request_id": request_id}), status_code


# User-friendly error messages for common scenarios
USER_FRIENDLY_MESSAGES = {
    ErrorCode.RATE_LIMITED: "You've reached the query limit. Please wait before trying again.",
    ErrorCode.MEETING_RATE_LIMITED: "Meeting join rate limit exceeded. Please wait before joining more meetings.",
    ErrorCode.NOT_CONFIGURED: "This feature is not configured. Please contact an administrator.",
    ErrorCode.CIRCUIT_OPEN: "This service is temporarily unavailable. Please try again later.",
    ErrorCode.LLM_TIMEOUT: "I'm having trouble processing that. Try a simpler query or try again.",
    ErrorCode.GITHUB_ERROR: "Unable to fetch GitHub data. Please try again.",
}


def get_user_friendly_message(code: ErrorCode, default: str = None) -> str:
    """Get user-friendly message for error code."""
    return USER_FRIENDLY_MESSAGES.get(code, default or "An error occurred. Please try again.")


# Comprehensive patterns for secrets that should be redacted from error responses
# SECURITY: This list should be kept up-to-date with new API key formats
_SECRET_PATTERNS = [
    # OpenAI / Anthropic style keys
    r'sk-[a-zA-Z0-9_-]{20,}',
    r'sk-proj-[a-zA-Z0-9_-]{20,}',
    r'sk-ant-[a-zA-Z0-9_-]{20,}',
    # Bearer tokens (OAuth, JWT, etc.)
    r'Bearer\s+[a-zA-Z0-9_.-]{20,}',
    # Webhook secrets (Stripe, Recall, etc.)
    r'whsec_[a-zA-Z0-9_-]{20,}',
    # GitHub tokens
    r'ghp_[a-zA-Z0-9]{36,}',
    r'gho_[a-zA-Z0-9]{36,}',
    r'ghu_[a-zA-Z0-9]{36,}',
    r'ghs_[a-zA-Z0-9]{36,}',
    r'ghr_[a-zA-Z0-9]{36,}',
    r'github_pat_[a-zA-Z0-9_]{22,}',
    # Slack tokens
    r'xox[baprs]-[a-zA-Z0-9-]{10,}',
    # AWS keys
    r'AKIA[0-9A-Z]{16}',
    r'aws_secret_access_key\s*[=:]\s*[a-zA-Z0-9/+=]{40}',
    # Generic API keys (long alphanumeric strings after common prefixes)
    r'api[_-]?key\s*[=:]\s*["\']?[a-zA-Z0-9_-]{20,}["\']?',
    r'secret\s*[=:]\s*["\']?[a-zA-Z0-9_-]{20,}["\']?',
    r'token\s*[=:]\s*["\']?[a-zA-Z0-9_-]{20,}["\']?',
    r'password\s*[=:]\s*["\']?[^\s"\']{8,}["\']?',
    # Basic auth headers
    r'Basic\s+[a-zA-Z0-9+/=]{20,}',
    # Zoom tokens
    r'eyJ[a-zA-Z0-9_-]{50,}\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+',  # JWT format
    # Twilio
    r'AC[a-f0-9]{32}',
    r'SK[a-f0-9]{32}',
    # Generic long hex strings (potential secrets)
    r'[a-f0-9]{64}',  # SHA256 hashes / secrets
]

# Compiled patterns for efficiency
import re as _re
_COMPILED_SECRET_PATTERNS = [_re.compile(p, _re.IGNORECASE) for p in _SECRET_PATTERNS]


def sanitize_response_text(text: str, max_length: int = 200) -> str:
    """
    Sanitize external response text to prevent secret leakage in logs.

    SECURITY: Uses comprehensive pattern matching to redact potential secrets.
    Applies defense-in-depth by:
    1. Truncating to max_length
    2. Redacting known secret patterns
    3. Redacting any remaining long alphanumeric sequences

    Args:
        text: Raw response text to sanitize
        max_length: Maximum length to keep (default 200)

    Returns:
        Sanitized text safe for logging

    Note:
        This function errs on the side of over-redaction for security.
        Better to redact non-secrets than to leak actual secrets.
    """
    if not text:
        return ""

    # Truncate first to limit processing
    sanitized = text[:max_length]

    # Apply all secret patterns
    for pattern in _COMPILED_SECRET_PATTERNS:
        sanitized = pattern.sub('[REDACTED]', sanitized)

    # Final pass: redact any remaining long alphanumeric sequences (32+ chars)
    # that might be unrecognized key formats
    sanitized = _re.sub(r'[a-zA-Z0-9_-]{32,}', '[REDACTED]', sanitized)

    return sanitized


def sanitize_error_json(response_json: dict, safe_fields: tuple = None) -> dict:
    """
    Extract only safe fields from an error response JSON.

    SECURITY: Uses whitelist approach - only explicitly allowed fields are kept.

    Args:
        response_json: Full JSON response from external service
        safe_fields: Tuple of field names to keep (default: common error fields)

    Returns:
        Dict containing only safe fields
    """
    if safe_fields is None:
        safe_fields = ("error", "message", "code", "type", "status", "title")

    return {k: v for k, v in response_json.items() if k in safe_fields}
