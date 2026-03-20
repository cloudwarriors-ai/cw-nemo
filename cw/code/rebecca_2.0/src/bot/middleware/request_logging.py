"""
Request logging middleware.

Provides:
- Request ID generation for tracing
- Request timing for performance monitoring
- Structured logging of request/response
"""

import time
import uuid
from flask import g, request


def register_request_logging(app):
    """
    Register request logging middleware.

    Adds request ID and timing to each request, logs completion.
    """

    @app.before_request
    def before_request():
        """Add request ID and timing to each request."""
        g.request_id = str(uuid.uuid4())[:8]
        g.start_time = time.time()

    @app.after_request
    def after_request(response):
        """Log request completion with timing."""
        if hasattr(g, 'start_time'):
            elapsed = (time.time() - g.start_time) * 1000
            log_level = "DEBUG"

            # Use INFO for slower requests or errors
            if elapsed > 1000 or response.status_code >= 400:
                log_level = "INFO"

            # Use WARNING for errors
            if response.status_code >= 500:
                log_level = "WARNING"

            log_func = getattr(app.logger, log_level.lower())
            log_func(
                f"[{getattr(g, 'request_id', '?')}] "
                f"{request.method} {request.path} "
                f"-> {response.status_code} ({elapsed:.0f}ms)"
            )

        # Add request ID to response headers for client-side correlation
        response.headers["X-Request-ID"] = getattr(g, 'request_id', 'unknown')

        return response
