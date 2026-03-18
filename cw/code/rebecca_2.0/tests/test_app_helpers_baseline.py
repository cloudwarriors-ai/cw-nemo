"""
Baseline integration tests for app.py helper functions.

PURPOSE: This test file establishes a baseline before Phase 3 refactoring.
These tests ensure that when helper functions are extracted to utils/,
any regressions are caught immediately.

IMPORTANT: Do NOT modify these tests during refactoring. They should pass
both before and after the extraction. If a test fails after refactoring,
fix the code, not the test.

Tested functions (app.py lines 700-1660):
- _handle_zoom_challenge (708-734)
- _sanitize_input (737-764)
- _verify_zoom_request (767-825)
- _check_rate_limit_db (828-878)
- _check_meeting_rate_limit (881-927)
- _verify_recall_webhook_signature (930-959)
- _process_query (962-998)
- _get_repo_stats (1201-1241)
- _format_repo_info (1244-1268)
- _handle_onboarding_request (1271-1315)
- _handle_offboarding_request (1318-1361)
- _handle_intern_status_request (1364-1406)
- _handle_meeting_join_request (1409-1444)
- _handle_weekly_report_request (1447-1509)
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
def baseline_temp_db():
    """Create a temporary database with rate limit tables."""
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
def baseline_app(baseline_temp_db):
    """Create a Flask app for baseline testing."""
    os.environ["DB_PATH"] = baseline_temp_db
    os.environ["ZOOM_BOT_VERIFICATION_TOKEN"] = "baseline-test-token"
    os.environ["ZOOM_BOT_SECRET_TOKEN"] = "baseline-test-secret"

    from src.bot.app import create_app
    app = create_app({
        "TESTING": True,
        "DB_PATH": baseline_temp_db,
        "ZOOM_BOT_TOKEN": "baseline-test-token",
        "ZOOM_BOT_SECRET": "baseline-test-secret",
        "RATE_LIMIT": 10,
        "MEETING_RATE_LIMIT": 3,
    })

    yield app


@pytest.fixture
def baseline_client(baseline_app):
    """Create test client for baseline testing."""
    return baseline_app.test_client()


# ============================================================================
# Test _handle_zoom_challenge
# ============================================================================

class TestHandleZoomChallenge:
    """Tests for Zoom URL validation challenge handler."""

    def test_challenge_with_secret_returns_encrypted_token(self, baseline_app):
        """Test challenge response includes properly encrypted token."""
        from src.bot.app import _handle_zoom_challenge

        with baseline_app.app_context():
            g.request_id = "test-123"
            data = {
                "event": "endpoint.url_validation",
                "payload": {"plainToken": "test-token-abc123"}
            }

            response = _handle_zoom_challenge(baseline_app, data)
            result = json.loads(response.data)

            assert "plainToken" in result
            assert result["plainToken"] == "test-token-abc123"
            assert "encryptedToken" in result

            # Verify HMAC calculation
            expected = hmac.new(
                "baseline-test-secret".encode(),
                "test-token-abc123".encode(),
                hashlib.sha256
            ).hexdigest()
            assert result["encryptedToken"] == expected

    def test_challenge_without_secret_echoes_token(self):
        """Test challenge with no secret configured echoes back token."""
        from src.bot.app import create_app, _handle_zoom_challenge

        app = create_app({
            "TESTING": True,
            "ZOOM_BOT_SECRET": "",  # No secret
        })

        with app.app_context():
            g.request_id = "test-124"
            data = {"payload": {"plainToken": "echo-test"}}

            response = _handle_zoom_challenge(app, data)
            result = json.loads(response.data)

            assert result["plainToken"] == "echo-test"
            assert result["encryptedToken"] == "echo-test"

    def test_challenge_with_empty_token(self, baseline_app):
        """Test challenge handles empty token gracefully."""
        from src.bot.app import _handle_zoom_challenge

        with baseline_app.app_context():
            g.request_id = "test-125"
            data = {"payload": {"plainToken": ""}}

            response = _handle_zoom_challenge(baseline_app, data)
            result = json.loads(response.data)

            assert result["plainToken"] == ""
            assert "encryptedToken" in result

    def test_challenge_with_missing_payload(self, baseline_app):
        """Test challenge handles missing payload."""
        from src.bot.app import _handle_zoom_challenge

        with baseline_app.app_context():
            g.request_id = "test-126"
            data = {}

            response = _handle_zoom_challenge(baseline_app, data)
            result = json.loads(response.data)

            assert result["plainToken"] == ""


# ============================================================================
# Test _sanitize_input
# ============================================================================

class TestSanitizeInput:
    """Tests for input sanitization function."""

    def test_normal_input_unchanged(self, baseline_app):
        """Test normal input passes through unchanged."""
        from src.bot.app import _sanitize_input

        assert _sanitize_input("show high priority issues") == "show high priority issues"

    def test_empty_input_returns_empty(self, baseline_app):
        """Test empty input returns empty string."""
        from src.bot.app import _sanitize_input

        assert _sanitize_input("") == ""
        assert _sanitize_input(None) == ""

    def test_strips_qabot_mention(self, baseline_app):
        """Test @qabot mention is stripped."""
        from src.bot.app import _sanitize_input

        assert _sanitize_input("@qabot help") == "help"
        assert _sanitize_input("@QABot show issues") == "show issues"

    def test_strips_qa_hyphen_bot_mention(self, baseline_app):
        """Test @qa-bot mention is stripped."""
        from src.bot.app import _sanitize_input

        assert _sanitize_input("@qa-bot summary") == "summary"

    def test_strips_configured_mentions_only(self, baseline_app):
        """Test only configured bot mentions are stripped.

        BOT_MENTIONS = ["@qabot", "@qa-bot", "@qa_bot"]
        Note: "@qa bot" (with space) and "qabot:" are NOT in the list.
        """
        from src.bot.app import _sanitize_input

        # These ARE in BOT_MENTIONS and should be stripped
        assert _sanitize_input("@qabot test") == "test"
        assert _sanitize_input("@qa-bot test") == "test"
        assert _sanitize_input("@qa_bot test") == "test"

        # These are NOT in BOT_MENTIONS and should NOT be stripped
        assert _sanitize_input("@qa bot test") == "@qa bot test"  # Space not supported
        assert _sanitize_input("qabot: test") == "qabot: test"    # Colon format not supported
        assert _sanitize_input("qa bot test") == "qa bot test"    # No @ sign not supported

    def test_truncates_long_input(self, baseline_app):
        """Test very long input is truncated."""
        from src.bot.app import _sanitize_input

        # Default max is 2000 characters
        long_input = "x" * 5000
        result = _sanitize_input(long_input)
        assert len(result) <= 2000

    def test_custom_max_length(self, baseline_app):
        """Test custom max length is respected."""
        from src.bot.app import _sanitize_input

        result = _sanitize_input("hello world", max_length=5)
        assert result == "hello"

    def test_strips_whitespace(self, baseline_app):
        """Test leading/trailing whitespace is stripped."""
        from src.bot.app import _sanitize_input

        assert _sanitize_input("  help  ") == "help"
        assert _sanitize_input("\t\ntest\n\t") == "test"

    def test_preserves_internal_whitespace(self, baseline_app):
        """Test internal whitespace is preserved."""
        from src.bot.app import _sanitize_input

        assert _sanitize_input("show high priority") == "show high priority"


# ============================================================================
# Test _verify_zoom_request
# ============================================================================

class TestVerifyZoomRequest:
    """Tests for Zoom request verification."""

    def test_valid_hmac_signature_accepted(self, baseline_app):
        """Test valid HMAC signature passes verification."""
        from src.bot.app import _verify_zoom_request

        timestamp = str(int(time.time()))
        body = '{"payload": {"text": "test"}}'
        secret = "baseline-test-secret"

        message = f"v0:{timestamp}:{body}"
        signature = "v0=" + hmac.new(
            secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        with baseline_app.test_request_context(
            "/zoom/webhook",
            method="POST",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-zm-signature": signature,
                "x-zm-request-timestamp": timestamp,
            }
        ):
            from flask import request
            result = _verify_zoom_request(baseline_app, request, {}, body)
            assert result is True

    def test_invalid_hmac_signature_rejected(self, baseline_app):
        """Test invalid HMAC signature fails verification."""
        from src.bot.app import _verify_zoom_request

        with baseline_app.test_request_context(
            "/zoom/webhook",
            method="POST",
            data='{"test": "data"}',
            headers={
                "x-zm-signature": "v0=invalid_signature",
                "x-zm-request-timestamp": "1234567890",
            }
        ):
            from flask import request
            result = _verify_zoom_request(baseline_app, request, {}, '{"test": "data"}')
            assert result is False

    def test_bearer_token_accepted(self, baseline_app):
        """Test Bearer token in header passes verification."""
        from src.bot.app import _verify_zoom_request

        with baseline_app.test_request_context(
            "/zoom/webhook",
            method="POST",
            headers={"Authorization": "Bearer baseline-test-token"}
        ):
            from flask import request
            result = _verify_zoom_request(baseline_app, request, {}, None)
            assert result is True

    def test_token_in_body_accepted(self, baseline_app):
        """Test token in body passes verification."""
        from src.bot.app import _verify_zoom_request

        with baseline_app.test_request_context(
            "/zoom/webhook",
            method="POST",
        ):
            from flask import request
            data = {"token": "baseline-test-token"}
            result = _verify_zoom_request(baseline_app, request, data, None)
            assert result is True

    def test_no_auth_configured_allows_all(self):
        """Test that no auth configured allows all requests (dev mode)."""
        from src.bot.app import create_app, _verify_zoom_request

        app = create_app({
            "TESTING": True,
            "ZOOM_BOT_TOKEN": "",
            "ZOOM_BOT_SECRET": "",
        })

        with app.test_request_context("/zoom/webhook", method="POST"):
            from flask import request
            result = _verify_zoom_request(app, request, {}, None)
            assert result is True


# ============================================================================
# Test _check_rate_limit_db
# ============================================================================

class TestCheckRateLimitDb:
    """Tests for database-backed rate limiting."""

    def test_first_request_allowed(self, baseline_app):
        """Test first request is allowed."""
        from src.bot.app import _check_rate_limit_db

        result = _check_rate_limit_db(baseline_app, "new-user-123")
        assert result is True

    def test_requests_within_limit_allowed(self, baseline_app):
        """Test requests within limit are allowed."""
        from src.bot.app import _check_rate_limit_db

        # App has RATE_LIMIT=10
        for i in range(5):
            result = _check_rate_limit_db(baseline_app, "moderate-user")
            assert result is True

    def test_exceeding_limit_blocked(self, baseline_app):
        """Test requests exceeding limit are blocked."""
        from src.bot.app import _check_rate_limit_db

        user_id = "heavy-user-456"

        # Make 10 requests (at the limit)
        for i in range(10):
            _check_rate_limit_db(baseline_app, user_id)

        # 11th request should be blocked
        result = _check_rate_limit_db(baseline_app, user_id)
        assert result is False

    def test_different_users_independent(self, baseline_app):
        """Test rate limits are per-user."""
        from src.bot.app import _check_rate_limit_db

        # User A hits limit
        for i in range(10):
            _check_rate_limit_db(baseline_app, "user-a")

        # User B should still be allowed
        result = _check_rate_limit_db(baseline_app, "user-b")
        assert result is True

    def test_disabled_rate_limit_allows_all(self):
        """Test rate limit of 0 or negative allows all."""
        from src.bot.app import create_app, _check_rate_limit_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            from src.bot.database import init_db
            init_db(db_path)

            app = create_app({
                "TESTING": True,
                "DB_PATH": db_path,
                "RATE_LIMIT": 0,  # Disabled
            })

            # Should allow unlimited requests
            for i in range(100):
                result = _check_rate_limit_db(app, "unlimited-user")
                assert result is True
        finally:
            os.unlink(db_path)


# ============================================================================
# Test _check_meeting_rate_limit
# ============================================================================

class TestCheckMeetingRateLimit:
    """Tests for meeting-specific rate limiting."""

    def test_first_meeting_allowed(self, baseline_app):
        """Test first meeting request is allowed."""
        from src.bot.app import _check_meeting_rate_limit

        result = _check_meeting_rate_limit(baseline_app, "meeting-user-1")
        assert result is True

    def test_meeting_limit_stricter(self, baseline_app):
        """Test meeting rate limit is stricter than general limit."""
        from src.bot.app import _check_meeting_rate_limit

        # App has MEETING_RATE_LIMIT=3
        user_id = "meeting-heavy-user"

        # First 3 should be allowed
        for i in range(3):
            result = _check_meeting_rate_limit(baseline_app, user_id)
            assert result is True, f"Request {i+1} should be allowed"

        # 4th should be blocked
        result = _check_meeting_rate_limit(baseline_app, user_id)
        assert result is False

    def test_different_users_independent(self, baseline_app):
        """Test meeting limits are per-user."""
        from src.bot.app import _check_meeting_rate_limit

        # User A hits limit
        for i in range(3):
            _check_meeting_rate_limit(baseline_app, "meeting-user-a")

        # User B should still be allowed
        result = _check_meeting_rate_limit(baseline_app, "meeting-user-b")
        assert result is True


# ============================================================================
# Test _verify_recall_webhook_signature
# ============================================================================

class TestVerifyRecallWebhookSignature:
    """Tests for Recall.ai webhook signature verification."""

    def test_no_secret_allows_all(self):
        """Test that no secret configured allows all webhooks."""
        from src.bot.app import create_app, _verify_recall_webhook_signature

        app = create_app({
            "TESTING": True,
            "RECALL_TRANSCRIPTION_SECRET": "",
        })

        with app.test_request_context(
            "/meeting/transcription",
            method="POST",
            data='{"test": "data"}',
        ):
            from flask import request
            result = _verify_recall_webhook_signature(app, request)
            assert result is True

    def test_valid_hmac_signature_accepted(self):
        """Test valid HMAC signature passes verification."""
        from src.bot.app import create_app, _verify_recall_webhook_signature

        secret = "recall-test-secret"
        app = create_app({
            "TESTING": True,
            "RECALL_TRANSCRIPTION_SECRET": secret,
        })

        body = b'{"event": "transcription"}'
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with app.test_request_context(
            "/meeting/transcription",
            method="POST",
            data=body,
            headers={"X-Recall-Signature": signature}
        ):
            from flask import request
            result = _verify_recall_webhook_signature(app, request)
            assert result is True

    def test_invalid_signature_rejected(self):
        """Test invalid signature fails verification."""
        from src.bot.app import create_app, _verify_recall_webhook_signature

        app = create_app({
            "TESTING": True,
            "RECALL_TRANSCRIPTION_SECRET": "recall-test-secret",
        })

        with app.test_request_context(
            "/meeting/transcription",
            method="POST",
            data=b'{"event": "transcription"}',
            headers={"X-Recall-Signature": "invalid-signature"}
        ):
            from flask import request
            result = _verify_recall_webhook_signature(app, request)
            assert result is False

    def test_simple_secret_header_fallback(self):
        """Test simple X-Transcription-Secret header fallback."""
        from src.bot.app import create_app, _verify_recall_webhook_signature

        secret = "simple-secret"
        app = create_app({
            "TESTING": True,
            "RECALL_TRANSCRIPTION_SECRET": secret,
        })

        with app.test_request_context(
            "/meeting/transcription",
            method="POST",
            data=b'{"event": "data"}',
            headers={"X-Transcription-Secret": secret}
        ):
            from flask import request
            result = _verify_recall_webhook_signature(app, request)
            assert result is True

    def test_missing_all_headers_with_secret_configured(self):
        """Test that missing both signature headers fails when secret is configured.

        SECURITY: This is a critical test - if secret is configured, requests
        without ANY authentication headers must be rejected.
        """
        from src.bot.app import create_app, _verify_recall_webhook_signature

        app = create_app({
            "TESTING": True,
            "RECALL_TRANSCRIPTION_SECRET": "configured-secret",
        })

        with app.test_request_context(
            "/meeting/transcription",
            method="POST",
            data=b'{"event": "unauthorized"}',
            headers={}  # No authentication headers
        ):
            from flask import request
            result = _verify_recall_webhook_signature(app, request)
            assert result is False  # Must be rejected


# ============================================================================
# Test _get_repo_stats and _format_repo_info
# ============================================================================

class TestRepoStatsAndFormatting:
    """Tests for repo statistics calculation and formatting."""

    @pytest.fixture
    def sample_issues(self):
        """Create sample Issue objects."""
        from src.github_client import Issue

        return [
            Issue(
                repo="test-repo",
                number=1,
                title="High priority bug",
                assignee="alice",
                labels=["priority/high"],
                priority="high",
                status=None,
                issue_type="bug",
                url="https://github.com/org/test-repo/issues/1",
                updated="2024-01-01",
                created="2024-01-01",
                is_stale=False,
            ),
            Issue(
                repo="test-repo",
                number=2,
                title="Unassigned task",
                assignee=None,
                labels=[],
                priority=None,
                status=None,
                issue_type=None,
                url="https://github.com/org/test-repo/issues/2",
                updated="2023-12-01",
                created="2023-12-01",
                is_stale=True,
            ),
            Issue(
                repo="test-repo",
                number=3,
                title="Normal issue",
                assignee="bob",
                labels=[],
                priority=None,
                status=None,
                issue_type=None,
                url="https://github.com/org/test-repo/issues/3",
                updated="2024-01-10",
                created="2024-01-10",
                is_stale=False,
            ),
        ]

    def test_get_repo_stats_with_issues(self, sample_issues):
        """Test stats calculation with Issue objects."""
        from src.bot.app import _get_repo_stats

        stats = _get_repo_stats(sample_issues)

        assert stats["total"] == 3
        assert stats["open"] == 3  # All issues from cache are open
        assert stats["high_priority"] == 1
        assert stats["unassigned"] == 1
        assert stats["stale"] == 1

    def test_get_repo_stats_empty_list(self):
        """Test stats calculation with empty list."""
        from src.bot.app import _get_repo_stats

        stats = _get_repo_stats([])

        assert stats["total"] == 0
        assert stats["open"] == 0
        assert stats["high_priority"] == 0
        assert stats["unassigned"] == 0
        assert stats["stale"] == 0

    def test_get_repo_stats_with_dicts(self):
        """Test stats calculation with dict objects (fallback)."""
        from src.bot.app import _get_repo_stats

        issues = [
            {"state": "open", "priority": "high", "assignee": "alice"},
            {"state": "open", "priority": "", "assignee": None},
            {"state": "closed", "priority": "low", "assignee": "bob"},
        ]

        stats = _get_repo_stats(issues)

        assert stats["total"] == 3
        assert stats["open"] == 2
        assert stats["high_priority"] == 1
        assert stats["unassigned"] == 1

    def test_format_repo_info_includes_name(self, sample_issues):
        """Test formatted output includes repo name."""
        from src.bot.app import _format_repo_info, _get_repo_stats

        stats = _get_repo_stats(sample_issues)
        result = _format_repo_info("my-repo", stats, sample_issues[:2])

        assert "**my-repo**" in result
        assert "Open issues:" in result

    def test_format_repo_info_includes_stats(self, sample_issues):
        """Test formatted output includes statistics."""
        from src.bot.app import _format_repo_info, _get_repo_stats

        stats = _get_repo_stats(sample_issues)
        result = _format_repo_info("test-repo", stats, [])

        assert "High priority: 1" in result
        assert "Unassigned: 1" in result
        assert "Stale" in result

    def test_format_repo_info_includes_recent_issues(self, sample_issues):
        """Test formatted output includes recent issues."""
        from src.bot.app import _format_repo_info, _get_repo_stats

        stats = _get_repo_stats(sample_issues)
        result = _format_repo_info("test-repo", stats, sample_issues)

        assert "Recent issues:" in result
        assert "#1" in result
        assert "#2" in result

    def test_format_repo_info_limits_to_5_issues(self, sample_issues):
        """Test only 5 recent issues are shown."""
        from src.bot.app import _format_repo_info, _get_repo_stats
        from src.github_client import Issue

        # Create 10 issues
        many_issues = []
        for i in range(10):
            many_issues.append(Issue(
                repo="test", number=i, title=f"Issue {i}",
                assignee=None, labels=[], priority=None, status=None,
                issue_type=None, url=f"http://test/{i}", updated="2024-01-01",
                created="2024-01-01", is_stale=False
            ))

        stats = _get_repo_stats(many_issues)
        result = _format_repo_info("test", stats, many_issues)

        # Count issue numbers in output
        issue_count = result.count("#")
        assert issue_count <= 5


# ============================================================================
# Test _handle_onboarding_request
# ============================================================================

class TestHandleOnboardingRequest:
    """Tests for onboarding request handler."""

    def test_missing_name_prompts_user(self, baseline_app):
        """Test missing person name returns prompt."""
        from src.bot.app import _handle_onboarding_request

        with baseline_app.app_context():
            result = _handle_onboarding_request(
                baseline_app, {}, "TestUser", "req-123"
            )

            assert "need a name" in result.lower()
            assert "onboard" in result.lower()

    def test_no_n8n_returns_not_configured(self, baseline_app):
        """Test no n8n client returns not configured message."""
        from src.bot.app import _handle_onboarding_request

        baseline_app.n8n_client = None

        with baseline_app.app_context():
            result = _handle_onboarding_request(
                baseline_app, {"person_name": "Alice"}, "TestUser", "req-124"
            )

            assert "Alice" in result
            assert "n8n" in result.lower() or "configured" in result.lower()

    def test_successful_onboarding_trigger(self, baseline_app):
        """Test successful onboarding workflow trigger."""
        from src.bot.app import _handle_onboarding_request

        mock_n8n = Mock()
        mock_n8n.trigger_onboarding.return_value = {"execution_id": "exec-123"}
        baseline_app.n8n_client = mock_n8n

        with baseline_app.app_context():
            result = _handle_onboarding_request(
                baseline_app, {"person_name": "Bob"}, "TestUser", "req-125"
            )

            assert "Bob" in result
            assert "Starting" in result or "Workflow" in result
            mock_n8n.trigger_onboarding.assert_called_once()


# ============================================================================
# Test _handle_offboarding_request
# ============================================================================

class TestHandleOffboardingRequest:
    """Tests for offboarding request handler."""

    def test_missing_name_prompts_user(self, baseline_app):
        """Test missing person name returns prompt."""
        from src.bot.app import _handle_offboarding_request

        with baseline_app.app_context():
            result = _handle_offboarding_request(
                baseline_app, {}, "TestUser", "req-126"
            )

            assert "need a name" in result.lower()
            assert "offboard" in result.lower()

    def test_successful_offboarding_trigger(self, baseline_app):
        """Test successful offboarding workflow trigger."""
        from src.bot.app import _handle_offboarding_request

        mock_n8n = Mock()
        mock_n8n.trigger_offboarding.return_value = {"execution_id": "exec-456"}
        baseline_app.n8n_client = mock_n8n

        with baseline_app.app_context():
            result = _handle_offboarding_request(
                baseline_app, {"person_name": "Charlie"}, "TestUser", "req-127"
            )

            assert "Charlie" in result
            mock_n8n.trigger_offboarding.assert_called_once()


# ============================================================================
# Test _handle_intern_status_request
# ============================================================================

class TestHandleInternStatusRequest:
    """Tests for intern status request handler."""

    def test_specific_intern_lookup(self, baseline_app):
        """Test looking up specific intern by name."""
        from src.bot.app import _handle_intern_status_request

        # Mock the response_builder
        baseline_app.response_builder = Mock()
        baseline_app.response_builder.format_intern_status.return_value = "Intern: Alice - Active"

        with baseline_app.app_context():
            result = _handle_intern_status_request(
                baseline_app, {"person_name": "Alice"}, "req-128"
            )

            assert "Alice" in result or baseline_app.response_builder.format_intern_status.called

    def test_no_interns_found(self, baseline_app):
        """Test response when no interns found."""
        from src.bot.app import _handle_intern_status_request

        with baseline_app.app_context():
            # Patch at the import location inside the function
            with patch("src.bot.database.get_all_interns", return_value=[]):
                result = _handle_intern_status_request(
                    baseline_app, {}, "req-129"
                )

                assert "No active interns" in result or "no" in result.lower()


# ============================================================================
# Test _handle_meeting_join_request
# ============================================================================

class TestHandleMeetingJoinRequest:
    """Tests for meeting join request handler."""

    def test_no_meeting_handler_returns_not_configured(self, baseline_app):
        """Test response when meeting handler not configured."""
        from src.bot.app import _handle_meeting_join_request

        baseline_app.meeting_handler = None

        with baseline_app.app_context():
            result = _handle_meeting_join_request(
                baseline_app, {}, "TestUser", "req-130"
            )

            assert "configured" in result.lower() or "Recall" in result

    def test_no_meeting_name_returns_instructions(self, baseline_app):
        """Test response when no meeting name provided."""
        from src.bot.app import _handle_meeting_join_request

        baseline_app.meeting_handler = Mock()

        with baseline_app.app_context():
            result = _handle_meeting_join_request(
                baseline_app, {}, "TestUser", "req-131"
            )

            assert "URL" in result or "join" in result.lower()

    def test_meeting_name_prompts_for_url(self, baseline_app):
        """Test named meeting prompts user for URL."""
        from src.bot.app import _handle_meeting_join_request

        baseline_app.meeting_handler = Mock()

        with baseline_app.app_context():
            result = _handle_meeting_join_request(
                baseline_app, {"meeting_name": "standup"}, "TestUser", "req-132"
            )

            assert "standup" in result
            assert "URL" in result


# ============================================================================
# Test _handle_weekly_report_request
# ============================================================================

class TestHandleWeeklyReportRequest:
    """Tests for weekly report request handler."""

    def test_no_orchestrator_returns_not_configured(self, baseline_app):
        """Test response when workflow orchestrator not configured."""
        from src.bot.app import _handle_weekly_report_request

        baseline_app.workflow_orchestrator = None

        with baseline_app.app_context():
            result = _handle_weekly_report_request(
                baseline_app, "channel-123", "req-133"
            )

            assert "configured" in result.lower()

    def test_no_channel_returns_error(self, baseline_app):
        """Test response when channel ID missing."""
        from src.bot.app import _handle_weekly_report_request

        baseline_app.workflow_orchestrator = Mock()

        with baseline_app.app_context():
            result = _handle_weekly_report_request(
                baseline_app, "", "req-134"
            )

            assert "channel" in result.lower()


# ============================================================================
# Test _process_query integration
# ============================================================================

class TestProcessQuery:
    """Integration tests for the main query processor."""

    def test_process_query_with_brain(self, baseline_app):
        """Test query processing delegates to brain when available."""
        from src.bot.app import _process_query
        from src.bot.llm_brain import ChatResponse, Capability

        mock_brain = Mock()
        mock_brain.chat_query.return_value = ChatResponse(
            capability=Capability.HELP,
            response="Here's how I can help...",
            filters=None,
            confidence=0.95,
            latency_ms=100,
        )
        baseline_app.qa_brain = mock_brain

        with baseline_app.app_context():
            g.request_id = "test-query-1"
            result = _process_query(
                baseline_app, "help", "user1", "Test User", "channel1", "req-135"
            )

            assert "help" in result.lower() or mock_brain.chat_query.called

    def test_process_query_legacy_fallback(self, baseline_app):
        """Test query processing falls back to legacy when no brain."""
        from src.bot.app import _process_query

        baseline_app.qa_brain = None
        baseline_app.escalation_manager = Mock()
        baseline_app.escalation_manager.should_escalate.return_value = False

        with baseline_app.app_context():
            g.request_id = "test-query-2"
            result = _process_query(
                baseline_app, "help", "user1", "Test User", "channel1", "req-136"
            )

            # Should get help response from legacy parser
            assert result is not None


# ============================================================================
# Test duplicate message detection integration
# ============================================================================

class TestDuplicateMessageDetection:
    """Integration tests for message deduplication."""

    def test_first_message_not_duplicate(self, baseline_app):
        """Test first occurrence of message is not duplicate."""
        from src.bot.app import _message_dedup_cache, _is_duplicate_message

        _message_dedup_cache.clear()

        result = _is_duplicate_message("baseline-test-msg-1")
        assert result is False

    def test_second_message_is_duplicate(self, baseline_app):
        """Test second occurrence is marked as duplicate."""
        from src.bot.app import _message_dedup_cache, _is_duplicate_message

        _message_dedup_cache.clear()

        _is_duplicate_message("baseline-test-msg-2")
        result = _is_duplicate_message("baseline-test-msg-2")
        assert result is True

    def test_different_messages_not_duplicates(self, baseline_app):
        """Test different messages are not marked as duplicates."""
        from src.bot.app import _message_dedup_cache, _is_duplicate_message

        _message_dedup_cache.clear()

        _is_duplicate_message("baseline-unique-1")
        result = _is_duplicate_message("baseline-unique-2")
        assert result is False


# ============================================================================
# Test end-to-end webhook processing
# ============================================================================

class TestWebhookEndToEnd:
    """End-to-end tests for webhook processing flow."""

    def test_full_help_request_flow(self, baseline_client):
        """Test complete flow for help request via webhook."""
        response = baseline_client.post(
            "/zoom/webhook",
            json={
                "token": "baseline-test-token",
                "payload": {
                    "text": "help",
                    "userId": "e2e-user-1",
                    "userName": "E2E Test User",
                }
            }
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "text" in data

    def test_full_summary_request_flow(self, baseline_client):
        """Test complete flow for summary request via webhook."""
        response = baseline_client.post(
            "/zoom/webhook",
            json={
                "token": "baseline-test-token",
                "payload": {
                    "text": "summary",
                    "userId": "e2e-user-2",
                    "userName": "E2E Test User",
                }
            }
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "text" in data

    def test_url_validation_challenge_flow(self, baseline_client):
        """Test complete URL validation challenge flow."""
        response = baseline_client.post(
            "/zoom/webhook",
            json={
                "event": "endpoint.url_validation",
                "payload": {"plainToken": "e2e-challenge-token"}
            }
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["plainToken"] == "e2e-challenge-token"
        assert "encryptedToken" in data
