"""
Unit tests for Recall.ai webhook signature verification.

Tests the AuthService.verify_recall_signature method with various
header formats and signature types.
"""
import base64
import hashlib
import hmac
import json
import time
import pytest

from src.bot.services.auth_service import AuthService


class TestRecallWebhookSignatureVerification:
    """Test Recall.ai webhook signature verification."""

    def test_svix_style_signature_valid(self):
        """Test that valid Svix-style signatures are accepted."""
        # Recall.ai uses Svix webhooks with whsec_ prefixed secrets
        raw_secret = b"test-webhook-secret-key-1234"
        secret = "whsec_" + base64.b64encode(raw_secret).decode()

        auth = AuthService(recall_secret=secret)

        # Build a valid webhook request
        msg_id = "msg_test123"
        timestamp = str(int(time.time()))
        body = json.dumps({"event": "bot.status_change", "data": {"bot_id": "abc123"}})

        # Compute signature the way Recall.ai does
        signing_string = f"{msg_id}.{timestamp}.{body}"
        signature_bytes = hmac.new(
            raw_secret,
            signing_string.encode(),
            hashlib.sha256
        ).digest()
        signature_b64 = base64.b64encode(signature_bytes).decode()

        headers = {
            "Webhook-Id": msg_id,
            "Webhook-Timestamp": timestamp,
            "Webhook-Signature": f"v1,{signature_b64}"
        }

        result = auth.verify_recall_signature(headers, body.encode())
        assert result is True, "Valid Svix-style signature should be accepted"

    def test_svix_style_signature_invalid(self):
        """Test that invalid Svix-style signatures are rejected."""
        raw_secret = b"test-webhook-secret-key-1234"
        secret = "whsec_" + base64.b64encode(raw_secret).decode()

        auth = AuthService(recall_secret=secret)

        msg_id = "msg_test123"
        timestamp = str(int(time.time()))
        body = json.dumps({"event": "bot.status_change"})

        # Use wrong signature
        headers = {
            "Webhook-Id": msg_id,
            "Webhook-Timestamp": timestamp,
            "Webhook-Signature": "v1,invalid_signature_here"
        }

        result = auth.verify_recall_signature(headers, body.encode())
        assert result is False, "Invalid signature should be rejected"

    def test_svix_style_tampered_body(self):
        """Test that tampered body is detected."""
        raw_secret = b"test-webhook-secret-key-1234"
        secret = "whsec_" + base64.b64encode(raw_secret).decode()

        auth = AuthService(recall_secret=secret)

        msg_id = "msg_test123"
        timestamp = str(int(time.time()))
        original_body = json.dumps({"event": "bot.status_change", "data": {"bot_id": "abc123"}})
        tampered_body = json.dumps({"event": "bot.status_change", "data": {"bot_id": "HACKED"}})

        # Sign with original body
        signing_string = f"{msg_id}.{timestamp}.{original_body}"
        signature_bytes = hmac.new(
            raw_secret,
            signing_string.encode(),
            hashlib.sha256
        ).digest()
        signature_b64 = base64.b64encode(signature_bytes).decode()

        headers = {
            "Webhook-Id": msg_id,
            "Webhook-Timestamp": timestamp,
            "Webhook-Signature": f"v1,{signature_b64}"
        }

        # Try to verify with tampered body
        result = auth.verify_recall_signature(headers, tampered_body.encode())
        assert result is False, "Tampered body should be rejected"

    def test_expired_timestamp_rejected(self):
        """Test that old timestamps are rejected."""
        raw_secret = b"test-webhook-secret-key-1234"
        secret = "whsec_" + base64.b64encode(raw_secret).decode()

        auth = AuthService(recall_secret=secret)

        msg_id = "msg_test123"
        # Timestamp from 10 minutes ago (should exceed MAX_TIMESTAMP_AGE_SECONDS)
        old_timestamp = str(int(time.time()) - 600)
        body = json.dumps({"event": "bot.status_change"})

        signing_string = f"{msg_id}.{old_timestamp}.{body}"
        signature_bytes = hmac.new(
            raw_secret,
            signing_string.encode(),
            hashlib.sha256
        ).digest()
        signature_b64 = base64.b64encode(signature_bytes).decode()

        headers = {
            "Webhook-Id": msg_id,
            "Webhook-Timestamp": old_timestamp,
            "Webhook-Signature": f"v1,{signature_b64}"
        }

        result = auth.verify_recall_signature(headers, body.encode())
        assert result is False, "Expired timestamp should be rejected"

    def test_legacy_simple_secret_header(self):
        """Test that legacy X-Transcription-Secret header still works."""
        secret = "my-transcription-secret"
        auth = AuthService(recall_secret=secret)

        headers = {
            "X-Transcription-Secret": secret
        }
        body = json.dumps({"event": "transcription"})

        result = auth.verify_recall_signature(headers, body.encode())
        assert result is True, "Legacy simple secret should be accepted"

    def test_legacy_simple_secret_wrong(self):
        """Test that wrong legacy secret is rejected."""
        auth = AuthService(recall_secret="correct-secret")

        headers = {
            "X-Transcription-Secret": "wrong-secret"
        }
        body = json.dumps({"event": "transcription"})

        result = auth.verify_recall_signature(headers, body.encode())
        assert result is False, "Wrong legacy secret should be rejected"

    def test_missing_signature_rejected(self):
        """Test that missing signature headers are rejected."""
        auth = AuthService(recall_secret="some-secret")

        headers = {}  # No signature headers at all
        body = json.dumps({"event": "test"})

        result = auth.verify_recall_signature(headers, body.encode())
        assert result is False, "Missing signature should be rejected"

    def test_no_secret_configured_allows_all_in_dev_mode(self):
        """Test that when no secret is configured in dev mode, webhooks are accepted."""
        # Dev mode: require_production_auth=False allows webhooks without credentials
        auth = AuthService(recall_secret=None, require_production_auth=False)

        headers = {}
        body = json.dumps({"event": "test"})

        result = auth.verify_recall_signature(headers, body.encode())
        assert result is True, "No secret configured should accept in dev mode (require_production_auth=False)"

    def test_no_secret_configured_rejects_in_production(self):
        """Test that when no secret is configured in production mode, webhooks are rejected."""
        # Production mode: require_production_auth=True (default) rejects without credentials
        auth = AuthService(recall_secret=None, require_production_auth=True)

        headers = {}
        body = json.dumps({"event": "test"})

        result = auth.verify_recall_signature(headers, body.encode())
        assert result is False, "No secret configured should reject in production mode"

    def test_raw_secret_without_whsec_prefix(self):
        """Test that raw secrets without whsec_ prefix still work."""
        secret = "raw-secret-no-prefix"
        auth = AuthService(recall_secret=secret)

        msg_id = "msg_test123"
        timestamp = str(int(time.time()))
        body = json.dumps({"event": "test"})

        # Sign with raw secret (not base64 decoded)
        signing_string = f"{msg_id}.{timestamp}.{body}"
        signature_bytes = hmac.new(
            secret.encode(),  # Raw secret
            signing_string.encode(),
            hashlib.sha256
        ).digest()
        signature_b64 = base64.b64encode(signature_bytes).decode()

        headers = {
            "Webhook-Id": msg_id,
            "Webhook-Timestamp": timestamp,
            "Webhook-Signature": f"v1,{signature_b64}"
        }

        result = auth.verify_recall_signature(headers, body.encode())
        assert result is True, "Raw secret without prefix should work"

    def test_multiple_signatures_in_header(self):
        """Test handling of multiple signatures (during secret rotation)."""
        raw_secret = b"new-secret"
        secret = "whsec_" + base64.b64encode(raw_secret).decode()

        auth = AuthService(recall_secret=secret)

        msg_id = "msg_test123"
        timestamp = str(int(time.time()))
        body = json.dumps({"event": "test"})

        # Valid signature
        signing_string = f"{msg_id}.{timestamp}.{body}"
        signature_bytes = hmac.new(
            raw_secret,
            signing_string.encode(),
            hashlib.sha256
        ).digest()
        valid_sig = base64.b64encode(signature_bytes).decode()

        # Multiple signatures (old and new during rotation)
        headers = {
            "Webhook-Id": msg_id,
            "Webhook-Timestamp": timestamp,
            "Webhook-Signature": f"v1,old_invalid_sig v1,{valid_sig}"
        }

        result = auth.verify_recall_signature(headers, body.encode())
        assert result is True, "Valid signature in list should be accepted"

    def test_case_insensitive_header_lookup(self):
        """Test that header lookup is case-insensitive."""
        raw_secret = b"test-secret"
        secret = "whsec_" + base64.b64encode(raw_secret).decode()

        auth = AuthService(recall_secret=secret)

        msg_id = "msg_test123"
        timestamp = str(int(time.time()))
        body = json.dumps({"event": "test"})

        signing_string = f"{msg_id}.{timestamp}.{body}"
        signature_bytes = hmac.new(
            raw_secret,
            signing_string.encode(),
            hashlib.sha256
        ).digest()
        signature_b64 = base64.b64encode(signature_bytes).decode()

        # Use different cases for headers
        headers = {
            "webhook-id": msg_id,  # lowercase
            "WEBHOOK-TIMESTAMP": timestamp,  # uppercase
            "Webhook-Signature": f"v1,{signature_b64}"  # mixed
        }

        result = auth.verify_recall_signature(headers, body.encode())
        assert result is True, "Header lookup should be case-insensitive"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
