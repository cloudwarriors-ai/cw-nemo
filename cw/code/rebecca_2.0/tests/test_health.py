"""
Tests for health check endpoints.

Tests liveness, readiness, and comprehensive health checks.
"""
import pytest
import sqlite3
import tempfile
import os
from unittest.mock import MagicMock, patch

from flask import Flask

from src.bot.routes.health import health_bp


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    @pytest.fixture
    def app(self):
        """Create a test Flask app with health blueprint."""
        app = Flask(__name__)
        app.config["TESTING"] = True

        # Create a temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        # Initialize the temp database
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER)")
        conn.close()

        app.config["DB_PATH"] = db_path

        # Mock required app attributes
        app.issue_cache = None
        app.github_client = None
        app.meeting_handler = None
        app.voice_pipeline = None
        app.avatar_session_manager = None
        app.qa_brain = None
        app.n8n_client = None
        app.auth_service = MagicMock()

        app.register_blueprint(health_bp)

        yield app

        # Cleanup
        if os.path.exists(db_path):
            os.unlink(db_path)

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return app.test_client()


class TestLivenessEndpoint(TestHealthEndpoints):
    """Tests for /health/live endpoint."""

    def test_liveness_returns_200(self, client):
        """Test that liveness probe returns 200 OK."""
        response = client.get("/health/live")
        assert response.status_code == 200

    def test_liveness_returns_ok_status(self, client):
        """Test that liveness probe returns ok status."""
        response = client.get("/health/live")
        data = response.get_json()
        assert data["status"] == "ok"

    def test_liveness_includes_timestamp(self, client):
        """Test that liveness probe includes timestamp."""
        response = client.get("/health/live")
        data = response.get_json()
        assert "timestamp" in data
        assert isinstance(data["timestamp"], (int, float))


class TestReadinessEndpoint(TestHealthEndpoints):
    """Tests for /health/ready endpoint."""

    def test_readiness_returns_200_when_healthy(self, client):
        """Test that readiness probe returns 200 when all checks pass."""
        response = client.get("/health/ready")
        assert response.status_code == 200

    def test_readiness_returns_ready_status(self, client):
        """Test that readiness probe returns ready status."""
        response = client.get("/health/ready")
        data = response.get_json()
        assert data["status"] == "ready"

    def test_readiness_includes_checks(self, client):
        """Test that readiness probe includes check details."""
        response = client.get("/health/ready")
        data = response.get_json()
        assert "checks" in data
        assert "database" in data["checks"]
        assert "circuit_breakers" in data["checks"]
        assert "auth_service" in data["checks"]

    def test_readiness_database_check_ok(self, client):
        """Test that database check returns ok when database is accessible."""
        response = client.get("/health/ready")
        data = response.get_json()
        assert data["checks"]["database"]["status"] == "ok"

    def test_readiness_returns_503_when_database_fails(self, app, client):
        """Test that readiness probe returns 503 when database is inaccessible."""
        # Point to non-existent database with a path that will fail
        app.config["DB_PATH"] = "/nonexistent/path/to/db.sqlite"

        response = client.get("/health/ready")
        assert response.status_code == 503
        data = response.get_json()
        assert data["status"] == "not_ready"
        assert data["checks"]["database"]["status"] == "error"

    def test_readiness_auth_service_check(self, app, client):
        """Test that auth service check is included."""
        response = client.get("/health/ready")
        data = response.get_json()
        assert data["checks"]["auth_service"]["status"] == "ok"

    def test_readiness_without_auth_service(self, app, client):
        """Test readiness when auth service is not configured."""
        app.auth_service = None

        response = client.get("/health/ready")
        data = response.get_json()
        assert data["checks"]["auth_service"]["status"] == "not_configured"

    def test_readiness_cache_initializing(self, app, client):
        """Test readiness when cache is initializing."""
        mock_cache = MagicMock()
        mock_cache.has_data = False
        app.issue_cache = mock_cache

        response = client.get("/health/ready")
        data = response.get_json()
        assert data["checks"]["cache"]["status"] == "initializing"
        # Should still be ready - cache warming up is not a failure
        assert response.status_code == 200

    def test_readiness_cache_ready(self, app, client):
        """Test readiness when cache is ready."""
        mock_cache = MagicMock()
        mock_cache.has_data = True
        app.issue_cache = mock_cache

        response = client.get("/health/ready")
        data = response.get_json()
        assert data["checks"]["cache"]["status"] == "ok"


class TestComprehensiveHealthEndpoint(TestHealthEndpoints):
    """Tests for /health endpoint."""

    def test_health_returns_200(self, client):
        """Test that health endpoint returns 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self, client):
        """Test that health endpoint returns ok status."""
        response = client.get("/health")
        data = response.get_json()
        assert data["status"] == "ok"

    def test_health_includes_config(self, client):
        """Test that health endpoint includes config summary."""
        response = client.get("/health")
        data = response.get_json()
        assert "config" in data

    def test_health_detailed_includes_dependencies(self, client):
        """Test that detailed=true includes dependency checks."""
        response = client.get("/health?detailed=true")
        data = response.get_json()
        assert "dependencies" in data

    def test_health_detailed_includes_circuit_breakers(self, client):
        """Test that detailed=true includes circuit breaker status."""
        response = client.get("/health?detailed=true")
        data = response.get_json()
        assert "circuit_breakers" in data


class TestCircuitBreakerIntegration(TestHealthEndpoints):
    """Tests for circuit breaker integration in health checks."""

    def test_readiness_with_open_circuit_still_ready(self, app, client):
        """Test that open circuits result in degraded but still ready status."""
        with patch('src.bot.routes.health.get_all_circuit_statuses') as mock_circuits:
            mock_circuits.return_value = [
                {"name": "openrouter", "state": "open"},
                {"name": "github", "state": "closed"}
            ]

            response = client.get("/health/ready")
            data = response.get_json()

            # Should still be ready (200) even with open circuit
            assert response.status_code == 200
            assert data["checks"]["circuit_breakers"]["status"] == "degraded"
            assert "openrouter" in data["checks"]["circuit_breakers"]["open_circuits"]

    def test_readiness_with_all_circuits_closed(self, app, client):
        """Test that closed circuits result in ok status."""
        with patch('src.bot.routes.health.get_all_circuit_statuses') as mock_circuits:
            mock_circuits.return_value = [
                {"name": "openrouter", "state": "closed"},
                {"name": "github", "state": "closed"}
            ]

            response = client.get("/health/ready")
            data = response.get_json()

            assert data["checks"]["circuit_breakers"]["status"] == "ok"
