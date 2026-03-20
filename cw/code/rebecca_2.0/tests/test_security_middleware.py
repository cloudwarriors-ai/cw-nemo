"""
Tests for security middleware.

Tests HSTS headers, HTTPS enforcement, and other security headers.
"""
import pytest
from flask import Flask

from src.bot.middleware.security import register_security_headers, HSTS_MAX_AGE


class TestSecurityMiddleware:
    """Tests for security middleware."""

    @pytest.fixture
    def app(self):
        """Create a test Flask app with security middleware."""
        app = Flask(__name__)
        app.config["TESTING"] = True
        register_security_headers(app)

        @app.route("/test")
        def test_route():
            return {"status": "ok"}

        @app.route("/health")
        def health_route():
            return {"status": "ok"}

        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return app.test_client()


class TestStandardSecurityHeaders(TestSecurityMiddleware):
    """Tests for standard security headers."""

    def test_x_content_type_options(self, client):
        """Test X-Content-Type-Options header is set."""
        response = client.get("/test")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        """Test X-Frame-Options header is set."""
        response = client.get("/test")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_x_xss_protection(self, client):
        """Test X-XSS-Protection header is set."""
        response = client.get("/test")
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_referrer_policy(self, client):
        """Test Referrer-Policy header is set."""
        response = client.get("/test")
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_content_security_policy_for_json(self, client):
        """Test Content-Security-Policy for JSON responses."""
        response = client.get("/test")
        assert response.headers.get("Content-Security-Policy") == "default-src 'none'"

    def test_permissions_policy(self, client):
        """Test Permissions-Policy header is set."""
        response = client.get("/test")
        policy = response.headers.get("Permissions-Policy")
        assert "geolocation=()" in policy
        assert "microphone=()" in policy
        assert "camera=()" in policy


class TestHSTSHeaders(TestSecurityMiddleware):
    """Tests for HSTS (HTTP Strict Transport Security) headers."""

    def test_no_hsts_in_test_mode(self, app):
        """Test HSTS header is not added in test mode."""
        client = app.test_client()
        response = client.get("/test")
        assert "Strict-Transport-Security" not in response.headers

    def test_no_hsts_over_http(self):
        """Test HSTS header is not added over HTTP (even in production)."""
        app = Flask(__name__)
        app.config["TESTING"] = False
        app.debug = False
        app.config["HSTS_ENABLED"] = True
        register_security_headers(app)

        @app.route("/test")
        def test_route():
            return {"status": "ok"}

        client = app.test_client()
        # Request over HTTP (no X-Forwarded-Proto)
        response = client.get("/test")
        # HSTS should not be sent over HTTP
        assert "Strict-Transport-Security" not in response.headers

    def test_hsts_over_https_in_production(self):
        """Test HSTS header is added over HTTPS in production mode."""
        app = Flask(__name__)
        app.config["TESTING"] = False
        app.debug = False
        app.config["HSTS_ENABLED"] = True
        register_security_headers(app)

        @app.route("/test")
        def test_route():
            return {"status": "ok"}

        client = app.test_client()
        # Simulate HTTPS via X-Forwarded-Proto
        response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

        assert "Strict-Transport-Security" in response.headers
        hsts = response.headers.get("Strict-Transport-Security")
        assert f"max-age={HSTS_MAX_AGE}" in hsts
        assert "includeSubDomains" in hsts
        assert "preload" in hsts

    def test_hsts_max_age_is_one_year(self):
        """Test HSTS max-age is set to 1 year (31536000 seconds)."""
        assert HSTS_MAX_AGE == 31536000


class TestHTTPSEnforcement(TestSecurityMiddleware):
    """Tests for HTTPS redirect enforcement."""

    def test_no_redirect_when_enforce_disabled(self, app):
        """Test no redirect when ENFORCE_HTTPS is False."""
        app.config["ENFORCE_HTTPS"] = False
        client = app.test_client()

        response = client.get("/test")
        assert response.status_code == 200

    def test_no_redirect_in_test_mode(self, app):
        """Test no redirect in test mode even with ENFORCE_HTTPS."""
        app.config["ENFORCE_HTTPS"] = True
        app.config["TESTING"] = True
        client = app.test_client()

        response = client.get("/test")
        assert response.status_code == 200

    def test_redirect_http_to_https_in_production(self):
        """Test HTTP requests are redirected to HTTPS in production."""
        app = Flask(__name__)
        app.config["TESTING"] = False
        app.debug = False
        app.config["ENFORCE_HTTPS"] = True
        register_security_headers(app)

        @app.route("/test")
        def test_route():
            return {"status": "ok"}

        client = app.test_client()
        # Simulate HTTP via X-Forwarded-Proto
        response = client.get(
            "/test",
            headers={"X-Forwarded-Proto": "http"},
            follow_redirects=False
        )

        assert response.status_code == 301
        assert "https://" in response.headers.get("Location", "")

    def test_no_redirect_for_https_requests(self):
        """Test HTTPS requests are not redirected."""
        app = Flask(__name__)
        app.config["TESTING"] = False
        app.debug = False
        app.config["ENFORCE_HTTPS"] = True
        register_security_headers(app)

        @app.route("/test")
        def test_route():
            return {"status": "ok"}

        client = app.test_client()
        # Simulate HTTPS via X-Forwarded-Proto
        response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

        assert response.status_code == 200

    def test_health_check_allowed_over_http(self):
        """Test health checks are allowed over HTTP (for load balancers)."""
        app = Flask(__name__)
        app.config["TESTING"] = False
        app.debug = False
        app.config["ENFORCE_HTTPS"] = True
        register_security_headers(app)

        @app.route("/health")
        def health_route():
            return {"status": "ok"}

        @app.route("/health/live")
        def live_route():
            return {"status": "ok"}

        @app.route("/health/ready")
        def ready_route():
            return {"status": "ok"}

        client = app.test_client()

        # Health endpoints should not be redirected
        for path in ["/health", "/health/live", "/health/ready"]:
            response = client.get(
                path,
                headers={"X-Forwarded-Proto": "http"},
                follow_redirects=False
            )
            assert response.status_code == 200, f"{path} should be allowed over HTTP"
