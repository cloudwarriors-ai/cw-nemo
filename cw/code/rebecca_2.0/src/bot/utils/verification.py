"""
Request verification utilities for Zoom and Recall.ai webhooks.

Extracted from app.py during Phase 3 refactoring.

Security Note:
    Dev mode bypasses are ONLY allowed when:
    - TESTING=True (pytest), OR
    - DEBUG=True AND ALLOW_INSECURE_WEBHOOKS=True (explicit opt-in)

    In production (TESTING=False, DEBUG=False), missing auth config
    will FAIL CLOSED (reject requests) rather than allow all.
"""
import hashlib
import hmac
import logging
import os
from typing import Optional

from flask import Flask, Request, jsonify


def _is_dev_mode(app: Flask) -> bool:
    """
    Check if running in development/test mode where auth bypass is allowed.

    Returns True only if:
    - TESTING=True (pytest environment), OR
    - DEBUG=True AND ALLOW_INSECURE_WEBHOOKS=True (explicit opt-in)

    This prevents accidental production deployments without auth.
    """
    if app.config.get("TESTING"):
        return True

    if app.debug and app.config.get("ALLOW_INSECURE_WEBHOOKS"):
        return True

    return False


def verify_zoom_request(
    app: Flask,
    request: Request,
    data: dict,
    raw_body: Optional[str] = None
) -> bool:
    """
    Verify that a request is from Zoom.

    Supports two verification methods:
    1. HMAC signature verification (recommended for production)
    2. Verification token in header or body (legacy/dev mode)

    HMAC verification uses the secret token and request timestamp
    to validate the x-zm-signature header.

    Args:
        app: Flask application
        request: Flask request object
        data: Parsed JSON data
        raw_body: Raw request body (must be passed since request.json consumes stream)

    Returns:
        True if request is verified, False otherwise
    """
    zoom_token = app.config.get("ZOOM_BOT_TOKEN")
    zoom_secret = app.config.get("ZOOM_BOT_SECRET")

    if not zoom_token and not zoom_secret:
        if _is_dev_mode(app):
            app.logger.warning(
                "No Zoom auth configured - allowing request (dev/test mode). "
                "This would be REJECTED in production."
            )
            return True
        else:
            app.logger.error(
                "SECURITY: No Zoom auth configured and not in dev mode. "
                "Set ZOOM_BOT_TOKEN or ZOOM_BOT_SECRET, or enable ALLOW_INSECURE_WEBHOOKS for dev."
            )
            return False

    # Method 1: HMAC signature verification (preferred)
    signature = request.headers.get("x-zm-signature")
    timestamp = request.headers.get("x-zm-request-timestamp")

    if signature and timestamp and zoom_secret and raw_body is not None:
        try:
            # Zoom's HMAC format: v0=<sha256_hex>
            # Message: v0:{timestamp}:{request_body}
            message = f"v0:{timestamp}:{raw_body}"
            expected_sig = "v0=" + hmac.new(
                zoom_secret.encode(),
                message.encode(),
                hashlib.sha256
            ).hexdigest()

            if hmac.compare_digest(signature, expected_sig):
                return True
            else:
                app.logger.warning("HMAC signature mismatch")
        except Exception as e:
            app.logger.error(f"HMAC verification error: {e}")

    # Method 2: Verification token (legacy/fallback)
    if zoom_token:
        # Check header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.replace("Bearer ", "") == zoom_token:
            return True

        # Check body
        if data.get("token") == zoom_token:
            return True

    return False


def create_zoom_challenge_response(
    app: Flask,
    data: dict,
    request_id: str
) -> tuple:
    """
    Create response for Zoom URL validation challenge.

    Zoom sends this to verify the webhook endpoint.

    Args:
        app: Flask application
        data: Parsed JSON data containing the challenge
        request_id: Request ID for logging

    Returns:
        Flask JSON response with plainToken and encryptedToken
    """
    payload = data.get("payload", {})
    plain_token = payload.get("plainToken", "")

    # Hash the token with our secret
    secret = app.config.get("ZOOM_BOT_SECRET", "")
    if secret:
        encrypted = hmac.new(
            secret.encode(),
            plain_token.encode(),
            hashlib.sha256
        ).hexdigest()
    elif _is_dev_mode(app):
        # Dev/test mode: echo back plainToken (Zoom will reject but allows local testing)
        app.logger.warning(
            "No ZOOM_BOT_SECRET configured - echoing plainToken (dev/test mode). "
            "Zoom URL validation will fail in production without secret."
        )
        encrypted = plain_token
    else:
        # Production without secret: return error
        app.logger.error(
            "SECURITY: Cannot complete Zoom challenge - ZOOM_BOT_SECRET not configured."
        )
        encrypted = ""  # This will fail Zoom's validation, which is correct

    app.logger.info(f"[{request_id}] Handled Zoom URL validation challenge")

    return jsonify({
        "plainToken": plain_token,
        "encryptedToken": encrypted
    })


def verify_recall_webhook_signature(
    app: Flask,
    request: Request
) -> bool:
    """
    Verify Recall.ai webhook signature using HMAC.

    Recall.ai sends:
    - X-Recall-Signature: HMAC signature
    - Raw request body

    Args:
        app: Flask application
        request: Flask request object

    Returns:
        True if signature valid, False otherwise
    """
    secret = app.config.get("RECALL_TRANSCRIPTION_SECRET")
    if not secret:
        if _is_dev_mode(app):
            app.logger.warning(
                "No RECALL_TRANSCRIPTION_SECRET configured - allowing webhook (dev/test mode). "
                "This would be REJECTED in production."
            )
            return True
        else:
            app.logger.error(
                "SECURITY: No Recall.ai secret configured and not in dev mode. "
                "Set RECALL_TRANSCRIPTION_SECRET or enable ALLOW_INSECURE_WEBHOOKS for dev."
            )
            return False

    signature = request.headers.get("X-Recall-Signature")
    if not signature:
        # Fall back to simple secret header check
        simple_secret = request.headers.get("X-Transcription-Secret")
        return simple_secret == secret

    # Verify HMAC signature
    try:
        expected = hmac.new(
            secret.encode(),
            request.get_data(),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)
    except Exception:
        return False
