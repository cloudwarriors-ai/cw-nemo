"""
Baseline integration tests for routes/zoom.py.

PURPOSE: This test file establishes a baseline before Phase 3 refactoring.
These tests ensure that when helper functions are extracted to utils/,
any regressions are caught immediately.

IMPORTANT: Do NOT modify these tests during refactoring. They should pass
both before and after the extraction.

Tested components (routes/zoom.py):
- _is_duplicate_message (29-44)
- _sanitize_input (47-65)
- _verify_zoom_request (68-106)
- _handle_zoom_challenge (109-128)
- _check_rate_limit (131-142)
- _extract_meeting_url (145-148)
- _process_query (384-426)
- Route: /zoom/webhook
- Route: /api/query
- Route: /api/stats
- Route: /oauth/callback
"""
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import time

import pytest
from unittest.mock import Mock, patch, MagicMock
from flask import Flask, g


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def zoom_temp_db():
    """Create a temporary database with required tables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    from src.bot.database import init_db
    init_db(db_path)

    # Initialize rate limit tables
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meeting_rate_limits (
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    yield db_path

    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def zoom_app(zoom_temp_db):
    """Create a Flask app for zoom route testing."""
    os.environ["DB_PATH"] = zoom_temp_db
    os.environ["ZOOM_BOT_VERIFICATION_TOKEN"] = "zoom-test-token"
    os.environ["ZOOM_BOT_SECRET_TOKEN"] = "zoom-test-secret"

    from src.bot.app import create_app
    app = create_app({
        "TESTING": True,
        "DB_PATH": zoom_temp_db,
        "ZOOM_BOT_TOKEN": "zoom-test-token",
        "ZOOM_BOT_SECRET": "zoom-test-secret",
        "RATE_LIMIT": 10,
        "MEETING_RATE_LIMIT": 3,
        "API_KEY": "",  # Disable API key requirement in tests
    })

    yield app


@pytest.fixture
def zoom_client(zoom_app):
    """Create test client for zoom route testing."""
    return zoom_app.test_client()


# ============================================================================
# Test _extract_meeting_url
# ============================================================================

class TestExtractMeetingUrl:
    """Tests for meeting URL extraction regex."""

    def test_extracts_zoom_url(self):
        """Test extraction of Zoom meeting URL."""
        from src.bot.routes.zoom import _extract_meeting_url

        text = "Please join the meeting at https://zoom.us/j/123456789?pwd=abc123"
        url = _extract_meeting_url(text)

        assert url is not None
        assert "zoom.us" in url
        assert "123456789" in url

    def test_extracts_teams_url(self):
        """Test extraction of Microsoft Teams URL."""
        from src.bot.routes.zoom import _extract_meeting_url

        text = "Meeting: https://teams.microsoft.com/l/meetup-join/abc123"
        url = _extract_meeting_url(text)

        assert url is not None
        assert "teams.microsoft.com" in url

    def test_extracts_google_meet_url(self):
        """Test extraction of Google Meet URL."""
        from src.bot.routes.zoom import _extract_meeting_url

        text = "Join at https://meet.google.com/abc-defg-hij"
        url = _extract_meeting_url(text)

        assert url is not None
        assert "meet.google.com" in url

    def test_returns_none_for_no_meeting_url(self):
        """Test returns None when no meeting URL present."""
        from src.bot.routes.zoom import _extract_meeting_url

        text = "Hello, how are you?"
        url = _extract_meeting_url(text)

        assert url is None

    def test_extracts_first_url_when_multiple(self):
        """Test extracts first meeting URL when multiple present."""
        from src.bot.routes.zoom import _extract_meeting_url

        text = "Join https://zoom.us/j/111 or https://zoom.us/j/222"
        url = _extract_meeting_url(text)

        assert url is not None
        assert "111" in url

    def test_case_insensitive_matching(self):
        """Test URL matching is case insensitive."""
        from src.bot.routes.zoom import _extract_meeting_url

        text = "HTTPS://ZOOM.US/J/123456"
        url = _extract_meeting_url(text)

        assert url is not None


# ============================================================================
# Test _is_duplicate_message (zoom.py version)
# ============================================================================

class TestZoomDuplicateMessage:
    """Tests for shared message deduplication utility used by zoom.py."""

    def test_first_message_not_duplicate(self, zoom_app):
        """Test first occurrence is not a duplicate."""
        from src.bot.utils import is_duplicate_message, get_duplicate_checker

        # Clear the shared cache for test isolation
        get_duplicate_checker().clear()

        result = is_duplicate_message("zoom-unique-msg-1")
        assert result is False

    def test_second_message_is_duplicate(self, zoom_app):
        """Test second occurrence is marked as duplicate."""
        from src.bot.utils import is_duplicate_message, get_duplicate_checker

        get_duplicate_checker().clear()

        is_duplicate_message("zoom-dup-msg-1")
        result = is_duplicate_message("zoom-dup-msg-1")
        assert result is True

    def test_different_messages_not_duplicates(self, zoom_app):
        """Test different messages are not duplicates."""
        from src.bot.utils import is_duplicate_message, get_duplicate_checker

        get_duplicate_checker().clear()

        is_duplicate_message("zoom-msg-a")
        result = is_duplicate_message("zoom-msg-b")
        assert result is False


# ============================================================================
# Test _sanitize_input (zoom.py version)
# ============================================================================

class TestZoomSanitizeInput:
    """Tests for zoom.py's input sanitization."""

    def test_delegates_to_query_service(self, zoom_app):
        """Test sanitization delegates to QueryService when available."""
        from src.bot.routes.zoom import _sanitize_input

        with zoom_app.app_context():
            # QueryService should be available
            result = _sanitize_input("@qabot hello")
            assert result == "hello"

    def test_fallback_without_service(self, zoom_app):
        """Test fallback behavior when QueryService unavailable."""
        from src.bot.routes.zoom import _sanitize_input

        with zoom_app.app_context():
            # Temporarily remove query_service
            original = zoom_app.query_service
            zoom_app.query_service = None

            result = _sanitize_input("@qabot test")
            assert result == "test"

            zoom_app.query_service = original

    def test_empty_input(self, zoom_app):
        """Test empty input returns empty string."""
        from src.bot.routes.zoom import _sanitize_input

        with zoom_app.app_context():
            assert _sanitize_input("") == ""
            assert _sanitize_input(None) == ""


# ============================================================================
# Test _verify_zoom_request (zoom.py version)
# ============================================================================

class TestZoomVerifyRequest:
    """Tests for zoom.py's request verification."""

    def test_delegates_to_auth_service(self, zoom_app):
        """Test verification delegates to AuthService when available."""
        from src.bot.routes.zoom import _verify_zoom_request

        with zoom_app.test_request_context(
            "/zoom/webhook",
            method="POST",
            headers={"Authorization": "Bearer zoom-test-token"}
        ):
            result = _verify_zoom_request({}, None)
            assert result is True

    def test_token_in_body_accepted(self, zoom_app):
        """Test token in request body is accepted."""
        from src.bot.routes.zoom import _verify_zoom_request

        with zoom_app.test_request_context("/zoom/webhook", method="POST"):
            result = _verify_zoom_request({"token": "zoom-test-token"}, None)
            assert result is True

    def test_invalid_token_rejected(self, zoom_app):
        """Test invalid token is rejected."""
        from src.bot.routes.zoom import _verify_zoom_request

        with zoom_app.test_request_context(
            "/zoom/webhook",
            method="POST",
            headers={"Authorization": "Bearer wrong-token"}
        ):
            result = _verify_zoom_request({"token": "also-wrong"}, None)
            assert result is False

    def test_hmac_signature_accepted(self, zoom_app):
        """Test valid HMAC signature is accepted."""
        from src.bot.routes.zoom import _verify_zoom_request

        timestamp = str(int(time.time()))
        body = '{"payload": {"text": "test"}}'
        secret = "zoom-test-secret"

        message = f"v0:{timestamp}:{body}"
        signature = "v0=" + hmac.new(
            secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        with zoom_app.test_request_context(
            "/zoom/webhook",
            method="POST",
            data=body,
            headers={
                "x-zm-signature": signature,
                "x-zm-request-timestamp": timestamp,
            }
        ):
            result = _verify_zoom_request({}, body)
            assert result is True


# ============================================================================
# Test _handle_zoom_challenge (zoom.py version)
# ============================================================================

class TestZoomHandleChallenge:
    """Tests for zoom.py's challenge handler."""

    def test_challenge_response_format(self, zoom_app):
        """Test challenge response has correct format."""
        from src.bot.routes.zoom import _handle_zoom_challenge

        with zoom_app.app_context():
            g.request_id = "test-1"
            data = {"payload": {"plainToken": "test-token-123"}}

            response = _handle_zoom_challenge(data)
            result = json.loads(response.data)

            assert "plainToken" in result
            assert "encryptedToken" in result
            assert result["plainToken"] == "test-token-123"

    def test_challenge_hmac_calculation(self, zoom_app):
        """Test HMAC is calculated correctly for challenge."""
        from src.bot.routes.zoom import _handle_zoom_challenge

        with zoom_app.app_context():
            g.request_id = "test-2"
            plain_token = "verify-me-123"
            data = {"payload": {"plainToken": plain_token}}

            response = _handle_zoom_challenge(data)
            result = json.loads(response.data)

            # Verify HMAC
            expected = hmac.new(
                "zoom-test-secret".encode(),
                plain_token.encode(),
                hashlib.sha256
            ).hexdigest()

            assert result["encryptedToken"] == expected


# ============================================================================
# Test _check_rate_limit (zoom.py version)
# ============================================================================

class TestZoomCheckRateLimit:
    """Tests for zoom.py's rate limit check."""

    def test_delegates_to_service(self, zoom_app):
        """Test rate limit delegates to RateLimitService."""
        from src.bot.routes.zoom import _check_rate_limit

        with zoom_app.app_context():
            result = _check_rate_limit("new-user-1")
            assert result is True

    def test_fallback_allows_all(self, zoom_app):
        """Test fallback allows all requests."""
        from src.bot.routes.zoom import _check_rate_limit

        with zoom_app.app_context():
            # Temporarily remove service
            original = zoom_app.rate_limit_service
            zoom_app.rate_limit_service = None

            result = _check_rate_limit("any-user")
            assert result is True

            zoom_app.rate_limit_service = original


# ============================================================================
# Test Zoom Webhook Route
# ============================================================================

class TestZoomWebhookRoute:
    """Tests for /zoom/webhook route."""

    def test_url_validation_challenge(self, zoom_client):
        """Test URL validation challenge is handled."""
        response = zoom_client.post(
            "/zoom/webhook",
            json={
                "event": "endpoint.url_validation",
                "payload": {"plainToken": "challenge-token"}
            }
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "plainToken" in data
        assert "encryptedToken" in data

    def test_unauthorized_rejected(self, zoom_client):
        """Test unauthorized requests are rejected."""
        response = zoom_client.post(
            "/zoom/webhook",
            json={"payload": {"text": "test"}},
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 401

    def test_valid_token_accepted(self, zoom_client):
        """Test valid token is accepted."""
        response = zoom_client.post(
            "/zoom/webhook",
            json={
                "token": "zoom-test-token",
                "payload": {
                    "text": "help",
                    "userId": "user-1",
                    "userName": "Test User"
                }
            }
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "text" in data

    def test_help_command(self, zoom_client):
        """Test help command returns help text."""
        response = zoom_client.post(
            "/zoom/webhook",
            json={
                "token": "zoom-test-token",
                "payload": {
                    "text": "help",
                    "userId": "user-2",
                    "userName": "Test User"
                }
            }
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "text" in data

    def test_meeting_url_detection(self, zoom_client, zoom_app):
        """Test meeting URL in message triggers join flow."""
        # Mock meeting handler
        zoom_app.meeting_handler = Mock()
        zoom_app.meeting_handler.join_meeting.return_value = {
            "status": "joining",
            "meeting_id": "123",
            "bot_id": "bot-123"
        }

        response = zoom_client.post(
            "/zoom/webhook",
            json={
                "token": "zoom-test-token",
                "payload": {
                    "text": "Join https://zoom.us/j/123456789",
                    "userId": "user-3",
                    "userName": "Test User"
                }
            }
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "text" in data

    def test_empty_query_handled(self, zoom_client):
        """Test empty query returns response."""
        response = zoom_client.post(
            "/zoom/webhook",
            json={
                "token": "zoom-test-token",
                "payload": {
                    "text": "",
                    "userId": "user-4",
                    "userName": "Test User"
                }
            }
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "text" in data


# ============================================================================
# Test OAuth Callback Route
# ============================================================================

class TestOAuthCallbackRoute:
    """Tests for /oauth/callback route."""

    def test_success_with_code(self, zoom_client):
        """Test successful callback with authorization code."""
        response = zoom_client.get("/oauth/callback?code=test-auth-code")

        assert response.status_code == 200
        assert b"Installed Successfully" in response.data

    def test_error_response(self, zoom_client):
        """Test error callback returns error page."""
        response = zoom_client.get("/oauth/callback?error=access_denied")

        assert response.status_code == 400
        assert b"Installation Failed" in response.data

    def test_no_params(self, zoom_client):
        """Test callback with no parameters."""
        response = zoom_client.get("/oauth/callback")

        assert response.status_code == 200
        assert b"OAuth callback" in response.data


# ============================================================================
# Test API Query Route
# ============================================================================

class TestApiQueryRoute:
    """Tests for /api/query route."""

    def test_query_required(self, zoom_client):
        """Test query parameter is required."""
        response = zoom_client.post(
            "/api/query",
            json={"user_name": "Test"}
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_valid_query(self, zoom_client):
        """Test valid query returns response."""
        response = zoom_client.post(
            "/api/query",
            json={"query": "help", "user_name": "Test"}
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "response" in data

    def test_summary_query(self, zoom_client):
        """Test summary query returns response."""
        response = zoom_client.post(
            "/api/query",
            json={"query": "summary", "user_name": "Test"}
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "response" in data


# ============================================================================
# Test API Stats Route
# ============================================================================

class TestApiStatsRoute:
    """Tests for /api/stats route."""

    def test_stats_returns_json(self, zoom_client):
        """Test stats endpoint returns JSON."""
        response = zoom_client.get("/api/stats")

        # May return 200 or 500 depending on DB state
        assert response.status_code in [200, 500]
        data = json.loads(response.data)
        assert isinstance(data, dict)


# ============================================================================
# Test API Cache Refresh Route
# ============================================================================

class TestApiCacheRefreshRoute:
    """Tests for /api/cache/refresh route."""

    def test_no_cache_configured(self, zoom_client, zoom_app):
        """Test response when cache not configured.

        Note: There are duplicate routes in zoom.py (503) and health.py (400).
        The health.py route is registered first and returns 400.
        """
        zoom_app.issue_cache = None

        response = zoom_client.post("/api/cache/refresh")

        # health.py returns 400 for no cache (it's registered first)
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data or "success" in data


# ============================================================================
# Test _process_query (zoom.py version)
# ============================================================================

class TestZoomProcessQuery:
    """Tests for zoom.py's query processing."""

    def test_delegates_to_query_service(self, zoom_app):
        """Test query processing delegates to QueryService."""
        from src.bot.routes.zoom import _process_query

        with zoom_app.app_context():
            g.request_id = "test-query-1"
            g.start_time = time.time()

            result = _process_query(
                text="help",
                user_name="Test User",
                request_id="req-1",
                user_id="user-1"
            )

            assert result is not None
            assert isinstance(result, str)

    def test_fallback_to_brain(self, zoom_app):
        """Test fallback to qa_brain when service unavailable."""
        from src.bot.routes.zoom import _process_query
        from src.bot.llm_brain import ChatResponse, Capability

        with zoom_app.app_context():
            g.request_id = "test-query-2"
            original_service = zoom_app.query_service
            zoom_app.query_service = None

            # Mock brain
            mock_brain = Mock()
            mock_brain.chat_query.return_value = ChatResponse(
                capability=Capability.HELP,
                response="Brain response",
                filters=None,
                confidence=0.9,
                latency_ms=100
            )
            zoom_app.qa_brain = mock_brain

            result = _process_query(
                text="test query",
                user_name="Test",
                request_id="req-2"
            )

            assert "Brain response" in result
            zoom_app.query_service = original_service

    def test_final_fallback(self, zoom_app):
        """Test final fallback when nothing available."""
        from src.bot.routes.zoom import _process_query

        with zoom_app.app_context():
            g.request_id = "test-query-3"
            original_service = zoom_app.query_service
            original_brain = zoom_app.qa_brain
            zoom_app.query_service = None
            zoom_app.qa_brain = None

            result = _process_query(
                text="anything",
                user_name="Test",
                request_id="req-3"
            )

            assert "help" in result.lower()
            zoom_app.query_service = original_service
            zoom_app.qa_brain = original_brain


# ============================================================================
# Test Zoom Send API Route
# ============================================================================

class TestApiZoomSendRoute:
    """Tests for /api/zoom/send route."""

    def test_message_required(self, zoom_client):
        """Test message parameter is required."""
        response = zoom_client.post(
            "/api/zoom/send",
            json={"channel": "general"}
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_send_without_chatbot(self, zoom_client, zoom_app):
        """Test send when chatbot not configured."""
        zoom_app.zoom_chatbot = None

        response = zoom_client.post(
            "/api/zoom/send",
            json={"message": "Test message"}
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "logged"


# ============================================================================
# Test Meeting Registration Route
# ============================================================================

class TestMeetingRegistrationRoute:
    """Tests for /api/zoom/meetings/register route."""

    def test_email_required(self, zoom_client):
        """Test email is required."""
        response = zoom_client.post(
            "/api/zoom/meetings/register",
            json={"first_name": "Test"}
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "email" in data.get("error", "").lower()

    def test_first_name_required(self, zoom_client):
        """Test first_name is required."""
        response = zoom_client.post(
            "/api/zoom/meetings/register",
            json={"email": "test@example.com"}
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "first_name" in data.get("error", "").lower()

    def test_no_zoom_meetings_client(self, zoom_client, zoom_app):
        """Test response when Zoom Meetings client not configured."""
        zoom_app.zoom_meetings = None

        response = zoom_client.post(
            "/api/zoom/meetings/register",
            json={
                "email": "test@example.com",
                "first_name": "Test"
            }
        )

        assert response.status_code == 503


# ============================================================================
# End-to-end flow tests
# ============================================================================

class TestZoomEndToEndFlows:
    """End-to-end tests for complete request flows."""

    def test_complete_help_flow(self, zoom_client):
        """Test complete help request flow."""
        response = zoom_client.post(
            "/zoom/webhook",
            json={
                "token": "zoom-test-token",
                "payload": {
                    "text": "@qabot help",
                    "userId": "e2e-user-1",
                    "userName": "E2E User",
                    "messageId": "e2e-msg-1"
                }
            }
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "text" in data

    def test_hmac_authenticated_flow(self, zoom_client):
        """Test flow with HMAC authentication."""
        timestamp = str(int(time.time()))
        body = '{"payload": {"text": "help", "userId": "hmac-user", "userName": "HMAC User"}}'
        secret = "zoom-test-secret"

        message = f"v0:{timestamp}:{body}"
        signature = "v0=" + hmac.new(
            secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        response = zoom_client.post(
            "/zoom/webhook",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-zm-signature": signature,
                "x-zm-request-timestamp": timestamp
            }
        )

        assert response.status_code == 200

    def test_api_query_flow(self, zoom_client):
        """Test complete API query flow."""
        response = zoom_client.post(
            "/api/query",
            json={
                "query": "summary",
                "user_name": "API Test",
                "user_id": "api-user-1"
            }
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "response" in data
