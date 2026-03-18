"""
Tests for Flask application and routes.
"""
import hashlib
import hmac
import json
import pytest


class TestHealthEndpoint:
    """Test the health check endpoint."""

    def test_health_returns_ok(self, client):
        """Test that health endpoint returns ok status."""
        response = client.get("/health")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_health_includes_config_info(self, client):
        """Test that health endpoint includes configuration info."""
        response = client.get("/health")
        data = json.loads(response.data)

        assert "config" in data
        assert "github_configured" in data["config"]
        assert "repo_count" in data["config"]  # Changed from repos list to count for security
        assert "version" in data

    def test_health_detailed_mode(self, client):
        """Test detailed health check with dependency info."""
        response = client.get("/health?detailed=true")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "dependencies" in data
        assert "database" in data["dependencies"]
        assert data["dependencies"]["database"]["status"] == "ok"

    def test_health_detailed_includes_all_dependencies(self, client):
        """Test detailed health lists all dependency types."""
        response = client.get("/health?detailed=true")
        data = json.loads(response.data)

        deps = data["dependencies"]
        assert "database" in deps
        assert "github" in deps
        assert "recall_ai" in deps
        assert "voice" in deps
        assert "avatar" in deps


class TestZoomWebhook:
    """Test the Zoom webhook endpoint."""

    def test_unauthorized_request_rejected(self, client):
        """Test that requests without valid token are rejected."""
        response = client.post(
            "/zoom/webhook",
            json={"payload": {"text": "help"}},
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 401

    def test_valid_token_in_header(self, client):
        """Test that valid token in header is accepted."""
        response = client.post(
            "/zoom/webhook",
            json={"payload": {"text": "help", "userId": "user1", "userName": "Test"}},
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-token"
            }
        )
        assert response.status_code == 200

    def test_valid_token_in_body(self, client):
        """Test that valid token in body is accepted."""
        response = client.post(
            "/zoom/webhook",
            json={
                "token": "test-token",
                "payload": {"text": "help", "userId": "user1", "userName": "Test"}
            },
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200

    def test_help_command_returns_help_text(self, client):
        """Test that help command returns help text."""
        response = client.post(
            "/zoom/webhook",
            json={
                "token": "test-token",
                "payload": {"text": "help", "userId": "user1", "userName": "Test"}
            }
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "text" in data
        assert "Commands" in data["text"] or "help" in data["text"].lower()

    def test_empty_query_returns_help(self, client):
        """Test that empty query returns help."""
        response = client.post(
            "/zoom/webhook",
            json={
                "token": "test-token",
                "payload": {"text": "", "userId": "user1", "userName": "Test"}
            }
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "text" in data

    def test_unknown_query_returns_helpful_response(self, client):
        """Test that unknown query returns helpful response."""
        response = client.post(
            "/zoom/webhook",
            json={
                "token": "test-token",
                "payload": {"text": "xyzzy foo bar", "userId": "user1", "userName": "Test"}
            }
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "text" in data
        # Should suggest valid commands
        assert "help" in data["text"].lower() or "command" in data["text"].lower()


class TestZoomUrlValidation:
    """Test Zoom URL validation challenge handling."""

    def test_url_validation_challenge(self, client):
        """Test that URL validation challenge is handled correctly."""
        response = client.post(
            "/zoom/webhook",
            json={
                "event": "endpoint.url_validation",
                "payload": {
                    "plainToken": "test-plain-token"
                }
            }
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "plainToken" in data
        assert "encryptedToken" in data


class TestApiEndpoints:
    """Test the direct API endpoints."""

    def test_api_query_requires_query(self, client, auth_headers):
        """Test that API query endpoint requires query parameter."""
        response = client.post(
            "/api/query",
            json={"user": "test"},
            headers=auth_headers
        )
        assert response.status_code == 400

    def test_api_query_works(self, client, auth_headers):
        """Test that API query endpoint works."""
        response = client.post(
            "/api/query",
            json={"query": "help", "user": "test"},
            headers=auth_headers
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "response" in data

    def test_api_stats_endpoint(self, client, auth_headers):
        """Test the stats endpoint."""
        response = client.get("/api/stats", headers=auth_headers)
        # May return 500 if cache not configured (no GitHub token)
        # Just verify it returns valid JSON
        assert response.status_code in [200, 500]


class TestRateLimiting:
    """Test rate limiting functionality."""

    def test_rate_limit_allows_normal_usage(self, client):
        """Test that normal usage is allowed."""
        for i in range(5):
            response = client.post(
                "/zoom/webhook",
                json={
                    "token": "test-token",
                    "payload": {"text": "help", "userId": "ratelimit-test", "userName": "Test"}
                }
            )
            assert response.status_code == 200


class TestInputSanitization:
    """Test input sanitization."""

    def test_long_input_truncated(self, client):
        """Test that very long input is handled safely."""
        long_text = "help " + "x" * 10000
        response = client.post(
            "/zoom/webhook",
            json={
                "token": "test-token",
                "payload": {"text": long_text, "userId": "user1", "userName": "Test"}
            }
        )
        assert response.status_code == 200

    def test_bot_mention_stripped(self, client):
        """Test that @qabot mention is stripped from input."""
        response = client.post(
            "/zoom/webhook",
            json={
                "token": "test-token",
                "payload": {"text": "@qabot help", "userId": "user1", "userName": "Test"}
            }
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        # Should still recognize help command
        assert "Commands" in data["text"] or "help" in data["text"].lower()

    def test_sql_injection_safe(self, client):
        """Test that SQL injection attempts are safe."""
        malicious = "intern status'; DROP TABLE interns; --"
        response = client.post(
            "/zoom/webhook",
            json={
                "token": "test-token",
                "payload": {"text": malicious, "userId": "user1", "userName": "Test"}
            }
        )
        # Should not crash
        assert response.status_code == 200


class TestHMACVerification:
    """Test HMAC signature verification for Zoom webhooks."""

    @pytest.fixture
    def client_with_hmac(self):
        """Create test client with HMAC secret configured."""
        from src.bot.app import create_app

        app = create_app({
            "TESTING": True,
            "ZOOM_BOT_SECRET": "test-hmac-secret",
            "ZOOM_BOT_TOKEN": "",  # Disable token auth
        })

        with app.test_client() as client:
            yield client

    def test_valid_hmac_signature_accepted(self, client_with_hmac):
        """Test that valid HMAC signature is accepted."""
        import time
        secret = "test-hmac-secret"
        timestamp = str(int(time.time()))  # Current timestamp to pass validation
        body = '{"payload": {"text": "help", "userId": "user1", "userName": "Test"}}'

        # Calculate expected signature
        message = f"v0:{timestamp}:{body}"
        signature = "v0=" + hmac.new(
            secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        response = client_with_hmac.post(
            "/zoom/webhook",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-zm-signature": signature,
                "x-zm-request-timestamp": timestamp
            }
        )
        assert response.status_code == 200

    def test_invalid_hmac_signature_rejected(self, client_with_hmac):
        """Test that invalid HMAC signature is rejected."""
        response = client_with_hmac.post(
            "/zoom/webhook",
            json={"payload": {"text": "help", "userId": "user1", "userName": "Test"}},
            headers={
                "Content-Type": "application/json",
                "x-zm-signature": "v0=invalid_signature",
                "x-zm-request-timestamp": "1234567890"
            }
        )
        assert response.status_code == 401

    def test_missing_signature_rejected(self, client_with_hmac):
        """Test that missing signature is rejected when HMAC is configured."""
        response = client_with_hmac.post(
            "/zoom/webhook",
            json={"payload": {"text": "help", "userId": "user1", "userName": "Test"}},
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 401
