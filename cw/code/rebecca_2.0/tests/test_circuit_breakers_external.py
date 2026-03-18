"""
Tests for circuit breakers on external service clients.

Verifies that GitHub, n8n, Zoom, and Recall clients properly integrate
with circuit breakers for resilience.
"""
import pytest
from unittest.mock import MagicMock, patch
import requests

from src.bot.circuit_breaker import CircuitOpenError, reset_all_circuits


class TestGitHubCircuitBreaker:
    """Tests for GitHub client circuit breaker integration."""

    @pytest.fixture(autouse=True)
    def reset_circuits(self):
        """Reset circuit breakers before each test."""
        reset_all_circuits()
        yield
        reset_all_circuits()

    def test_github_client_has_circuit_breaker(self):
        """Test GitHubClient initializes with circuit breaker."""
        from src.github_client import GitHubClient

        client = GitHubClient(token="test_token", org="test_org")
        assert hasattr(client, "_circuit_breaker")
        assert client._circuit_breaker.name == "github"

    def test_github_circuit_breaker_status(self):
        """Test GitHubClient exposes circuit breaker status."""
        from src.github_client import GitHubClient

        client = GitHubClient(token="test_token", org="test_org")
        status = client.get_circuit_status()

        assert "name" in status
        assert status["name"] == "github"
        assert "state" in status
        assert status["state"] == "closed"

    @patch("github.Github")
    def test_github_fetch_issues_circuit_open(self, mock_github):
        """Test fetch_issues raises CircuitOpenError when circuit is open."""
        from src.github_client import GitHubClient

        client = GitHubClient(token="test_token", org="test_org")

        # Force circuit open
        for _ in range(5):
            client._circuit_breaker.record_failure()

        with pytest.raises(CircuitOpenError):
            client.fetch_issues(["repo1"])

    def test_github_validate_user_returns_error_when_circuit_open(self):
        """Test validate_github_user returns error dict when circuit open."""
        from src.github_client import GitHubClient

        client = GitHubClient(token="test_token", org="test_org")

        # Force circuit open
        for _ in range(5):
            client._circuit_breaker.record_failure()

        result = client.validate_github_user("testuser")
        assert result["exists"] is False
        assert "unavailable" in result["error"]

    def test_github_invite_to_org_returns_error_when_circuit_open(self):
        """Test invite_to_org returns error dict when circuit open."""
        from src.github_client import GitHubClient

        client = GitHubClient(token="test_token", org="test_org")

        # Force circuit open
        for _ in range(5):
            client._circuit_breaker.record_failure()

        result = client.invite_to_org("testuser")
        assert result["success"] is False
        assert "unavailable" in result["error"]

    def test_github_remove_from_org_returns_error_when_circuit_open(self):
        """Test remove_from_org returns error dict when circuit open."""
        from src.github_client import GitHubClient

        client = GitHubClient(token="test_token", org="test_org")

        # Force circuit open
        for _ in range(5):
            client._circuit_breaker.record_failure()

        result = client.remove_from_org("testuser")
        assert result["success"] is False
        assert "unavailable" in result["error"]


class TestN8nCircuitBreaker:
    """Tests for n8n client circuit breaker integration."""

    @pytest.fixture(autouse=True)
    def reset_circuits(self):
        """Reset circuit breakers before each test."""
        reset_all_circuits()
        yield
        reset_all_circuits()

    @pytest.fixture
    def n8n_client(self, tmp_path):
        """Create n8n client with temp database."""
        from src.bot.n8n_client import N8nClient

        db_path = str(tmp_path / "test.db")

        # Initialize database
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_executions (
                id TEXT PRIMARY KEY,
                workflow_type TEXT,
                status TEXT,
                payload TEXT,
                context TEXT,
                result TEXT,
                error TEXT,
                created_at TEXT,
                completed_at TEXT
            )
        """)
        conn.close()

        return N8nClient(
            webhook_base_url="https://n8n.example.com/webhook",
            db_path=db_path
        )

    def test_n8n_client_has_circuit_breaker(self, n8n_client):
        """Test N8nClient initializes with circuit breaker."""
        assert hasattr(n8n_client, "_circuit_breaker")
        assert n8n_client._circuit_breaker.name == "n8n"

    def test_n8n_circuit_breaker_status(self, n8n_client):
        """Test N8nClient exposes circuit breaker status."""
        status = n8n_client.get_circuit_status()

        assert "name" in status
        assert status["name"] == "n8n"
        assert "state" in status
        assert status["state"] == "closed"

    def test_n8n_trigger_workflow_returns_circuit_open_status(self, n8n_client):
        """Test _trigger_workflow returns circuit_open status when circuit open."""
        from src.bot.n8n_client import WorkflowType

        # Force circuit open
        for _ in range(5):
            n8n_client._circuit_breaker.record_failure()

        result = n8n_client._trigger_workflow(
            workflow_type=WorkflowType.ONBOARDING,
            payload={"test": "data"},
            context={"test": "context"}
        )

        assert result["status"] == "circuit_open"
        assert result["execution_id"] is None
        assert "unavailable" in result["error"]

    def test_n8n_trigger_workflow_sync_returns_circuit_open_status(self, n8n_client):
        """Test _trigger_workflow_sync returns circuit_open status when circuit open."""
        from src.bot.n8n_client import WorkflowType

        # Force circuit open
        for _ in range(5):
            n8n_client._circuit_breaker.record_failure()

        result = n8n_client._trigger_workflow_sync(
            workflow_type=WorkflowType.REPORT_UPLOAD,
            payload={"test": "data"},
            context={"test": "context"}
        )

        assert result["status"] == "circuit_open"
        assert result["execution_id"] is None


class TestZoomChatbotCircuitBreaker:
    """Tests for Zoom chatbot circuit breaker integration."""

    @pytest.fixture(autouse=True)
    def reset_circuits(self):
        """Reset circuit breakers before each test."""
        reset_all_circuits()
        yield
        reset_all_circuits()

    @pytest.fixture
    def zoom_client(self):
        """Create Zoom chatbot client."""
        from src.zoom_chatbot import ZoomChatbot

        return ZoomChatbot(
            client_id="test_client_id",
            client_secret="test_client_secret",
            bot_jid="test_bot_jid",
            account_id="test_account_id"
        )

    def test_zoom_client_has_circuit_breaker(self, zoom_client):
        """Test ZoomChatbot initializes with circuit breaker."""
        assert hasattr(zoom_client, "_circuit_breaker")
        assert zoom_client._circuit_breaker.name == "zoom"

    def test_zoom_circuit_breaker_status(self, zoom_client):
        """Test ZoomChatbot exposes circuit breaker status."""
        status = zoom_client.get_circuit_status()

        assert "name" in status
        assert status["name"] == "zoom"
        assert "state" in status
        assert status["state"] == "closed"

    def test_zoom_get_access_token_raises_circuit_open(self, zoom_client):
        """Test _get_access_token raises CircuitOpenError when circuit open."""
        # Force circuit open
        for _ in range(5):
            zoom_client._circuit_breaker.record_failure()

        # Clear cached token to force new token request
        zoom_client._access_token = None
        zoom_client._token_expiry = 0

        with pytest.raises(CircuitOpenError):
            zoom_client._get_access_token()

    def test_zoom_get_user_email_returns_none_when_circuit_open(self, zoom_client):
        """Test get_user_email returns None when circuit open."""
        # Force circuit open
        for _ in range(5):
            zoom_client._circuit_breaker.record_failure()

        result = zoom_client.get_user_email("test_user_id")
        assert result is None


class TestRecallClientCircuitBreaker:
    """Tests for Recall.ai client circuit breaker integration."""

    @pytest.fixture(autouse=True)
    def reset_circuits(self):
        """Reset circuit breakers before each test."""
        reset_all_circuits()
        yield
        reset_all_circuits()

    @pytest.fixture
    def recall_client(self):
        """Create Recall.ai client."""
        from src.meeting.recall_client import RecallClient

        return RecallClient(
            api_key="test_api_key",
            bot_name="Test Bot"
        )

    def test_recall_client_has_circuit_breaker(self, recall_client):
        """Test RecallClient initializes with circuit breaker."""
        assert hasattr(recall_client, "_circuit_breaker")
        assert recall_client._circuit_breaker.name == "recall"

    def test_recall_circuit_breaker_status(self, recall_client):
        """Test RecallClient exposes circuit breaker status."""
        status = recall_client.get_circuit_status()

        assert "name" in status
        assert status["name"] == "recall"
        assert "state" in status
        assert status["state"] == "closed"

    def test_recall_request_raises_circuit_open(self, recall_client):
        """Test _request raises CircuitOpenError when circuit open."""
        # Force circuit open
        for _ in range(5):
            recall_client._circuit_breaker.record_failure()

        with pytest.raises(CircuitOpenError):
            recall_client._request("GET", "/bot")

    @patch("requests.request")
    def test_recall_request_records_success(self, mock_request, recall_client):
        """Test _request records success on successful response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "test_bot_id"}
        mock_request.return_value = mock_response

        result = recall_client._request("GET", "/bot/123")

        assert result == {"id": "test_bot_id"}
        assert recall_client._circuit_breaker.stats.successes >= 1

    @patch("requests.request")
    def test_recall_request_records_failure_on_server_error(self, mock_request, recall_client):
        """Test _request records failure after exhausting retries."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_request.return_value = mock_response

        with pytest.raises(requests.RequestException):
            recall_client._request("GET", "/bot/123")

        # Should have recorded failures
        assert recall_client._circuit_breaker.stats.failures >= 1


class TestCircuitBreakerGlobalRegistry:
    """Tests for circuit breaker global registry with all services."""

    @pytest.fixture(autouse=True)
    def reset_circuits(self):
        """Reset circuit breakers before each test."""
        reset_all_circuits()
        yield
        reset_all_circuits()

    def test_all_services_registered_in_global_registry(self, tmp_path):
        """Test that all service circuit breakers appear in global registry."""
        from src.bot.circuit_breaker import get_all_circuit_statuses
        from src.github_client import GitHubClient
        from src.bot.n8n_client import N8nClient
        from src.zoom_chatbot import ZoomChatbot
        from src.meeting.recall_client import RecallClient

        # Initialize all clients
        GitHubClient(token="test", org="test")

        db_path = str(tmp_path / "test.db")
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_executions (
                id TEXT PRIMARY KEY, workflow_type TEXT, status TEXT, payload TEXT,
                context TEXT, result TEXT, error TEXT, created_at TEXT, completed_at TEXT
            )
        """)
        conn.close()
        N8nClient(webhook_base_url="https://n8n.example.com/webhook", db_path=db_path)

        ZoomChatbot(
            client_id="test", client_secret="test",
            bot_jid="test", account_id="test"
        )
        RecallClient(api_key="test")

        # Get all statuses
        statuses = get_all_circuit_statuses()
        names = [s["name"] for s in statuses]

        assert "github" in names
        assert "n8n" in names
        assert "zoom" in names
        assert "recall" in names
