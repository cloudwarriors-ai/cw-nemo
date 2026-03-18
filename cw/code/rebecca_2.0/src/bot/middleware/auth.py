"""
Authentication middleware decorators.

Provides consolidated authentication decorators for routes:
- require_api_auth: Standard API key authentication
- require_zoom_auth: Zoom webhook HMAC verification
- require_recall_auth: Recall.ai Svix webhook verification
- require_internal_auth: Internal API auth (API key OR callback secret)

Consolidates duplicate auth logic from multiple route files.
"""
import hmac
from functools import wraps
from flask import request, jsonify, current_app, g


def require_api_auth(f):
    """
    Decorator to require API authentication for endpoints.

    Checks for valid API key in Authorization header or X-API-Key header.
    In dev mode (no API key configured), allows all requests.

    Usage:
        @app.route("/api/endpoint")
        @require_api_auth
        def my_endpoint():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if hasattr(current_app, 'auth_service') and current_app.auth_service:
            if not current_app.auth_service.verify_api_key(dict(request.headers)):
                current_app.logger.warning(
                    f"[{g.request_id}] Unauthorized API request to {request.path}"
                )
                return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function


def require_internal_auth(f):
    """
    Decorator to require internal API authentication.

    For n8n workflows, checks for valid API key OR callback secret.
    This prevents external parties from triggering internal operations.

    Accepts auth via:
    - API key in Authorization/X-API-Key header
    - N8N callback secret in body, X-Callback-Secret, or X-N8N-Secret header

    Usage:
        @app.route("/api/internal/endpoint")
        @require_internal_auth
        def my_internal_endpoint():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check API key auth first
        if hasattr(current_app, 'auth_service') and current_app.auth_service:
            if current_app.auth_service.verify_api_key(dict(request.headers)):
                return f(*args, **kwargs)

        # Check callback secret (for n8n)
        callback_secret = current_app.config.get("N8N_CALLBACK_SECRET", "")
        if callback_secret:
            data = request.json or {}
            provided_secret = (
                data.get("secret") or
                request.headers.get("X-Callback-Secret") or
                request.headers.get("X-N8N-Secret") or
                ""
            )
            if hmac.compare_digest(provided_secret, callback_secret):
                return f(*args, **kwargs)

        current_app.logger.warning(
            f"[{g.request_id}] Unauthorized internal API request to {request.path}"
        )
        return jsonify({"error": "Unauthorized"}), 401

    return decorated_function


def verify_zoom_request(data: dict = None, raw_body: str = None) -> bool:
    """
    Verify request is from Zoom using AuthService.

    Security: Fail-secure design - uses auth_service when available,
    only falls back to direct verification in dev/test mode.

    Checks via auth_service:
    1. HMAC signature verification (preferred)
    2. Token in Authorization header
    3. Token in request body

    Args:
        data: Parsed request JSON data
        raw_body: Raw request body for HMAC verification

    Returns:
        True if request is verified, False otherwise
    """
    if data is None:
        data = request.json or {}
    if raw_body is None:
        raw_body = request.get_data(as_text=True)

    # Primary path: Use auth_service
    if hasattr(current_app, 'auth_service') and current_app.auth_service:
        return current_app.auth_service.verify_zoom_request(
            headers=dict(request.headers),
            body=raw_body,
            data=data
        )

    # Fail-secure: Only allow fallback in dev/test mode
    is_dev_mode = current_app.config.get("TESTING") or current_app.debug
    if not is_dev_mode:
        current_app.logger.error(
            f"[{g.request_id}] SECURITY: Zoom webhook rejected - auth_service not configured"
        )
        return False

    # Dev/test fallback: Direct verification
    import hashlib
    token = current_app.config.get("ZOOM_BOT_TOKEN")
    secret = current_app.config.get("ZOOM_BOT_SECRET")

    # Token in header
    header_token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token and header_token == token:
        return True

    # Token in body
    if token and data.get("token") == token:
        return True

    # HMAC signature verification
    if secret and raw_body:
        signature = request.headers.get("x-zm-signature", "")
        timestamp = request.headers.get("x-zm-request-timestamp", "")

        if signature and timestamp:
            message = f"v0:{timestamp}:{raw_body}"
            expected = "v0=" + hmac.new(
                secret.encode(),
                message.encode(),
                hashlib.sha256
            ).hexdigest()

            if hmac.compare_digest(signature, expected):
                return True

    return False


def verify_recall_webhook() -> bool:
    """
    Verify Recall.ai webhook signature using auth_service.

    Security: Fail-secure design - rejects if auth_service unavailable.
    Only accepts if explicitly verified OR no secret is configured (dev mode).

    Returns:
        True if signature valid, False otherwise
    """
    if not hasattr(current_app, 'auth_service') or not current_app.auth_service:
        # Fail-secure: Reject if auth_service unavailable
        current_app.logger.error(
            f"[{g.request_id}] SECURITY: Recall webhook rejected - auth_service not configured"
        )
        return False

    headers = dict(request.headers)
    body = request.get_data()

    is_valid = current_app.auth_service.verify_recall_signature(headers, body)
    if not is_valid:
        current_app.logger.error(
            f"[{g.request_id}] SECURITY: Recall webhook signature verification failed"
        )

    return is_valid


def require_recall_auth(f):
    """
    Decorator to require Recall.ai webhook authentication.

    Verifies Svix-style webhook signature.

    Usage:
        @app.route("/webhook/recall")
        @require_recall_auth
        def recall_webhook():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not verify_recall_webhook():
            return jsonify({"error": "Invalid signature"}), 401
        return f(*args, **kwargs)
    return decorated_function


def require_zoom_auth(f):
    """
    Decorator to require Zoom webhook authentication.

    Verifies HMAC signature or token.

    Usage:
        @app.route("/webhook/zoom")
        @require_zoom_auth
        def zoom_webhook():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        data = request.json or {}
        raw_body = request.get_data(as_text=True)

        if not verify_zoom_request(data, raw_body):
            current_app.logger.warning(
                f"[{g.request_id}] Unauthorized Zoom webhook request"
            )
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function
