"""
Middleware for cross-cutting concerns.

Provides request/response processing for:
- Request ID generation
- Request timing and logging
- Error handling
- Security headers
- Authentication decorators
"""

from .request_logging import register_request_logging
from .error_handler import register_error_handlers
from .security import register_security_headers
from .auth import (
    require_api_auth,
    require_internal_auth,
    require_zoom_auth,
    require_recall_auth,
    verify_zoom_request,
    verify_recall_webhook,
)


def register_all_middleware(app):
    """Register all middleware on the Flask app."""
    register_request_logging(app)
    register_error_handlers(app)
    register_security_headers(app)


__all__ = [
    "register_all_middleware",
    "register_request_logging",
    "register_error_handlers",
    "register_security_headers",
    # Auth decorators
    "require_api_auth",
    "require_internal_auth",
    "require_zoom_auth",
    "require_recall_auth",
    "verify_zoom_request",
    "verify_recall_webhook",
]
