"""
Security middleware.

Provides security headers for all responses including HSTS for HTTPS enforcement.
"""
from flask import redirect, request


# HSTS configuration: 1 year in seconds
HSTS_MAX_AGE = 31536000  # 365 days


def register_security_headers(app):
    """
    Register security headers middleware.

    Adds security-related HTTP headers to all responses.
    In production mode with HTTPS, adds HSTS header to enforce secure connections.

    Configuration:
        ENFORCE_HTTPS: Set to True in production to redirect HTTP to HTTPS
        HSTS_ENABLED: Set to True to add Strict-Transport-Security header
    """

    @app.before_request
    def enforce_https():
        """
        Redirect HTTP to HTTPS in production mode.

        Only applies when:
        - ENFORCE_HTTPS config is True
        - Request is not already HTTPS
        - Not a health check (allow HTTP health checks from load balancers)
        """
        enforce = app.config.get("ENFORCE_HTTPS", False)
        is_production = not (app.config.get("TESTING") or app.debug)

        if enforce and is_production:
            # Check if request is HTTP (not HTTPS)
            # X-Forwarded-Proto is set by load balancers/proxies
            proto = request.headers.get("X-Forwarded-Proto", request.scheme)

            if proto != "https":
                # Skip health checks (allow HTTP for load balancer health probes)
                if request.path in ("/health", "/health/live", "/health/ready"):
                    return None

                # Redirect to HTTPS
                url = request.url.replace("http://", "https://", 1)
                return redirect(url, code=301)

        return None

    @app.after_request
    def add_security_headers(response):
        """Add security headers to response."""
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # XSS protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy for API responses
        if response.content_type and 'application/json' in response.content_type:
            response.headers["Content-Security-Policy"] = "default-src 'none'"

        # Permissions policy (restrict browser features)
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), "
            "payment=(), usb=(), magnetometer=(), gyroscope=()"
        )

        # HSTS (HTTP Strict Transport Security)
        # Only add in production and when HSTS is enabled
        # Note: HSTS should only be sent over HTTPS connections
        is_production = not (app.config.get("TESTING") or app.debug)
        hsts_enabled = app.config.get("HSTS_ENABLED", is_production)
        proto = request.headers.get("X-Forwarded-Proto", request.scheme)

        if hsts_enabled and proto == "https":
            # max-age: How long browser should remember to only use HTTPS
            # includeSubDomains: Apply to all subdomains
            # preload: Eligible for browser HSTS preload lists
            response.headers["Strict-Transport-Security"] = (
                f"max-age={HSTS_MAX_AGE}; includeSubDomains; preload"
            )

        return response
