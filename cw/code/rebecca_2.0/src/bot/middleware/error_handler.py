"""
Error handling middleware.

Provides standardized error responses for common HTTP errors.
"""

from flask import jsonify, g


def register_error_handlers(app):
    """
    Register error handlers for common HTTP errors.

    Provides consistent JSON error responses.
    """

    @app.errorhandler(400)
    def bad_request(error):
        """Handle 400 Bad Request errors."""
        return jsonify({
            "error": "Bad request",
            "message": str(error.description) if hasattr(error, 'description') else "Invalid request",
            "request_id": getattr(g, 'request_id', None)
        }), 400

    @app.errorhandler(401)
    def unauthorized(error):
        """Handle 401 Unauthorized errors."""
        return jsonify({
            "error": "Unauthorized",
            "message": "Authentication required",
            "request_id": getattr(g, 'request_id', None)
        }), 401

    @app.errorhandler(403)
    def forbidden(error):
        """Handle 403 Forbidden errors."""
        return jsonify({
            "error": "Forbidden",
            "message": "Access denied",
            "request_id": getattr(g, 'request_id', None)
        }), 403

    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 Not Found errors."""
        return jsonify({
            "error": "Not found",
            "message": "Resource not found",
            "request_id": getattr(g, 'request_id', None)
        }), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        """Handle 405 Method Not Allowed errors."""
        return jsonify({
            "error": "Method not allowed",
            "message": "The method is not allowed for this endpoint",
            "request_id": getattr(g, 'request_id', None)
        }), 405

    @app.errorhandler(429)
    def rate_limited(error):
        """Handle 429 Too Many Requests errors."""
        return jsonify({
            "error": "Rate limited",
            "message": "Too many requests. Please try again later.",
            "request_id": getattr(g, 'request_id', None)
        }), 429

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 Internal Server Error."""
        app.logger.error(f"[{getattr(g, 'request_id', '?')}] Internal error: {error}")
        return jsonify({
            "error": "Internal server error",
            "message": "An unexpected error occurred",
            "request_id": getattr(g, 'request_id', None)
        }), 500

    @app.errorhandler(503)
    def service_unavailable(error):
        """Handle 503 Service Unavailable errors."""
        return jsonify({
            "error": "Service unavailable",
            "message": "The service is temporarily unavailable",
            "request_id": getattr(g, 'request_id', None)
        }), 503

    @app.errorhandler(Exception)
    def unhandled_exception(error):
        """Handle unhandled exceptions."""
        app.logger.exception(f"[{getattr(g, 'request_id', '?')}] Unhandled exception: {error}")
        return jsonify({
            "error": "Internal server error",
            "message": "An unexpected error occurred",
            "request_id": getattr(g, 'request_id', None)
        }), 500
