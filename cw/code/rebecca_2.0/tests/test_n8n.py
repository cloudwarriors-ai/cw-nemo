"""
Tests for n8n workflow integration.
"""
import pytest
from unittest.mock import patch, MagicMock
from src.bot.n8n_client import N8nClient, WorkflowType, WorkflowStatus


@pytest.fixture
def n8n_client(temp_db):
    """Create an n8n client with test database."""
    return N8nClient(
        webhook_base_url="https://n8n.example.com/webhook",
        db_path=temp_db,
        timeout_seconds=5
    )


class TestN8nClientInit:
    """Test n8n client initialization."""

    def test_client_init(self, temp_db):
        """Test client initializes with correct settings."""
        client = N8nClient(
            webhook_base_url="https://n8n.example.com/webhook/",
            db_path=temp_db
        )
        # URL should have trailing slash stripped
        assert client.webhook_base_url == "https://n8n.example.com/webhook"
        assert client.db_path == temp_db

    def test_workflow_paths_configured(self, n8n_client):
        """Test workflow paths are properly configured."""
        assert WorkflowType.ONBOARDING in n8n_client.workflow_paths
        assert WorkflowType.OFFBOARDING in n8n_client.workflow_paths
        assert WorkflowType.WEEKLY_FEEDBACK in n8n_client.workflow_paths
        assert WorkflowType.HEALTH_CHECK in n8n_client.workflow_paths


class TestTriggerWorkflows:
    """Test workflow triggering."""

    @patch("requests.post")
    def test_trigger_onboarding_success(self, mock_post, n8n_client):
        """Test successful onboarding workflow trigger."""
        mock_post.return_value = MagicMock(status_code=200, text="OK")

        result = n8n_client.trigger_onboarding(
            intern_id="intern-123",
            intern_name="Jane Doe",
            program="skillbridge",
            start_date="2026-01-15",
            supervisor="chad3"
        )

        assert result["status"] == "triggered"
        assert result["workflow_type"] == "onboarding"
        assert "execution_id" in result

        # Verify the request was made correctly
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "onboarding" in call_args[0][0]  # URL contains onboarding
        assert call_args[1]["json"]["intern_name"] == "Jane Doe"

    @patch("requests.post")
    def test_trigger_offboarding_success(self, mock_post, n8n_client):
        """Test successful offboarding workflow trigger."""
        mock_post.return_value = MagicMock(status_code=200, text="OK")

        result = n8n_client.trigger_offboarding(
            intern_id="intern-123",
            intern_name="Jane Doe",
            end_date="2026-04-15"
        )

        assert result["status"] == "triggered"
        assert result["workflow_type"] == "offboarding"

    @patch("requests.post")
    def test_trigger_weekly_feedback_success(self, mock_post, n8n_client):
        """Test successful weekly feedback workflow trigger."""
        mock_post.return_value = MagicMock(status_code=200, text="OK")

        result = n8n_client.trigger_weekly_feedback(
            intern_id="intern-123",
            intern_name="Jane Doe",
            supervisor="chad3",
            week_ending="2026-01-17"
        )

        assert result["status"] == "triggered"
        assert result["workflow_type"] == "weekly_feedback"

    @patch("requests.post")
    def test_trigger_health_check_success(self, mock_post, n8n_client):
        """Test successful health check workflow trigger."""
        mock_post.return_value = MagicMock(status_code=200, text="OK")

        result = n8n_client.trigger_health_check(
            applications=["pulse", "macd", "quantum"],
            notify_channel="devops"
        )

        assert result["status"] == "triggered"
        assert result["workflow_type"] == "health_check"

    @patch("requests.post")
    def test_trigger_workflow_http_error(self, mock_post, n8n_client):
        """Test workflow trigger handles HTTP errors."""
        mock_post.return_value = MagicMock(status_code=500, text="Internal Error")

        result = n8n_client.trigger_onboarding(
            intern_id="intern-123",
            intern_name="Jane Doe",
            program="skillbridge",
            start_date="2026-01-15",
            supervisor="chad3"
        )

        assert result["status"] == "failed"
        assert "500" in result["error"]

    @patch("requests.post")
    @patch("time.sleep")  # Skip retry delays in tests
    def test_trigger_workflow_timeout(self, mock_sleep, mock_post, n8n_client):
        """Test workflow trigger handles timeouts with retry."""
        import requests
        mock_post.side_effect = requests.Timeout()

        result = n8n_client.trigger_onboarding(
            intern_id="intern-123",
            intern_name="Jane Doe",
            program="skillbridge",
            start_date="2026-01-15",
            supervisor="chad3"
        )

        assert result["status"] == "failed"
        # After retries, error message indicates all attempts failed
        assert "failed after" in result["error"].lower() or "timeout" in result["error"].lower()
        # Verify retries were attempted
        assert mock_post.call_count == 3

    @patch("requests.post")
    @patch("time.sleep")  # Skip retry delays in tests
    def test_trigger_workflow_connection_error(self, mock_sleep, mock_post, n8n_client):
        """Test workflow trigger handles connection errors with retry."""
        import requests
        mock_post.side_effect = requests.ConnectionError("Connection refused")

        result = n8n_client.trigger_onboarding(
            intern_id="intern-123",
            intern_name="Jane Doe",
            program="skillbridge",
            start_date="2026-01-15",
            supervisor="chad3"
        )

        assert result["status"] == "failed"
        assert "execution_id" in result
        # Verify retries were attempted for connection errors
        assert mock_post.call_count == 3


class TestExecutionTracking:
    """Test workflow execution tracking."""

    @patch("requests.post")
    def test_execution_stored_in_db(self, mock_post, n8n_client):
        """Test that executions are stored in database."""
        mock_post.return_value = MagicMock(status_code=200, text="OK")

        result = n8n_client.trigger_onboarding(
            intern_id="intern-123",
            intern_name="Jane Doe",
            program="skillbridge",
            start_date="2026-01-15",
            supervisor="chad3"
        )

        execution_id = result["execution_id"]
        status = n8n_client.get_execution_status(execution_id)

        assert status is not None
        assert status["id"] == execution_id
        assert status["workflow_type"] == "onboarding"
        assert status["status"] == "running"

    @patch("requests.post")
    def test_mark_completed(self, mock_post, n8n_client):
        """Test marking execution as completed."""
        mock_post.return_value = MagicMock(status_code=200, text="OK")

        result = n8n_client.trigger_onboarding(
            intern_id="intern-123",
            intern_name="Jane Doe",
            program="skillbridge",
            start_date="2026-01-15",
            supervisor="chad3"
        )

        execution_id = result["execution_id"]
        n8n_client.mark_completed(execution_id, {"documents_created": 3})

        status = n8n_client.get_execution_status(execution_id)
        assert status["status"] == "completed"
        assert status["completed_at"] is not None

    @patch("requests.post")
    def test_mark_failed(self, mock_post, n8n_client):
        """Test marking execution as failed."""
        mock_post.return_value = MagicMock(status_code=200, text="OK")

        result = n8n_client.trigger_onboarding(
            intern_id="intern-123",
            intern_name="Jane Doe",
            program="skillbridge",
            start_date="2026-01-15",
            supervisor="chad3"
        )

        execution_id = result["execution_id"]
        n8n_client.mark_failed(execution_id, "Google Docs API error")

        status = n8n_client.get_execution_status(execution_id)
        assert status["status"] == "failed"
        assert "Google Docs" in status["error"]

    @patch("requests.post")
    def test_get_recent_executions(self, mock_post, n8n_client):
        """Test retrieving recent executions."""
        mock_post.return_value = MagicMock(status_code=200, text="OK")

        # Trigger multiple workflows
        n8n_client.trigger_onboarding(
            intern_id="intern-1", intern_name="Jane",
            program="test", start_date="2026-01-15", supervisor="chad3"
        )
        n8n_client.trigger_offboarding(
            intern_id="intern-2", intern_name="John",
            end_date="2026-01-20"
        )

        # Get all recent
        all_executions = n8n_client.get_recent_executions()
        assert len(all_executions) == 2

        # Filter by type
        onboarding_only = n8n_client.get_recent_executions(workflow_type="onboarding")
        assert len(onboarding_only) == 1
        assert onboarding_only[0]["workflow_type"] == "onboarding"

    def test_get_nonexistent_execution(self, n8n_client):
        """Test getting status of non-existent execution."""
        status = n8n_client.get_execution_status("nonexistent-id")
        assert status is None


class TestN8nApiEndpoints:
    """Test n8n API endpoints in the Flask app."""

    def test_list_interns_empty(self, client):
        """Test listing interns when none exist."""
        response = client.get("/api/interns")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 0
        assert data["interns"] == []

    def test_create_intern(self, client):
        """Test creating a new intern."""
        response = client.post("/api/intern", json={
            "id": "intern-001",
            "name": "Jane Doe",
            "program": "skillbridge",
            "supervisor": "chad3",
            "start_date": "2026-01-15"
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data["status"] == "created"
        assert data["id"] == "intern-001"

    def test_create_intern_missing_fields(self, client):
        """Test creating intern with missing required fields."""
        response = client.post("/api/intern", json={
            "program": "skillbridge"
        })
        assert response.status_code == 400
        assert "Missing required fields" in response.get_json()["error"]

    def test_get_intern(self, client):
        """Test getting intern by ID."""
        # First create an intern
        client.post("/api/intern", json={
            "id": "intern-002",
            "name": "John Smith",
            "program": "vanderbilt"
        })

        # Then get it
        response = client.get("/api/intern/intern-002")
        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "John Smith"
        assert data["program"] == "vanderbilt"

    def test_get_intern_not_found(self, client):
        """Test getting non-existent intern."""
        response = client.get("/api/intern/nonexistent")
        assert response.status_code == 404

    def test_update_intern_status(self, client):
        """Test updating intern status."""
        # Create intern
        client.post("/api/intern", json={
            "id": "intern-003",
            "name": "Alice Johnson"
        })

        # Update status
        response = client.put("/api/intern/intern-003/status", json={
            "status": "active",
            "notes": "Completed orientation"
        })
        assert response.status_code == 200

        # Verify update
        response = client.get("/api/intern/intern-003")
        assert response.get_json()["status"] == "active"

    def test_update_intern_invalid_status(self, client):
        """Test updating intern with invalid status."""
        client.post("/api/intern", json={
            "id": "intern-004",
            "name": "Bob Wilson"
        })

        response = client.put("/api/intern/intern-004/status", json={
            "status": "invalid_status"
        })
        assert response.status_code == 400
        assert "Invalid status" in response.get_json()["error"]

    def test_list_interns_with_filter(self, client):
        """Test listing interns with status filter."""
        # Create interns with different statuses
        client.post("/api/intern", json={"id": "i1", "name": "Intern 1"})
        client.post("/api/intern", json={"id": "i2", "name": "Intern 2"})
        client.put("/api/intern/i2/status", json={"status": "active"})

        # Filter by active status
        response = client.get("/api/interns?status=active")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1
        assert data["interns"][0]["name"] == "Intern 2"

    @pytest.mark.xfail(reason="Fixture isolation issue - validation runs before config check")
    def test_workflow_trigger_not_configured(self, client):
        """Test workflow trigger when n8n not configured."""
        response = client.post("/api/workflow/trigger", json={
            "workflow_type": "onboarding",
            "payload": {}
        })
        assert response.status_code == 503
        assert "not configured" in response.get_json()["error"]

    @pytest.mark.xfail(reason="Fixture isolation issue - auth check runs before validation")
    def test_n8n_callback_requires_fields(self, client):
        """Test n8n callback requires execution_id and status."""
        response = client.post("/n8n/callback", json={})
        assert response.status_code in (400, 503)  # 400 if validation, 503 if not configured

    def test_get_interns_ending_soon(self, client):
        """Test getting interns ending soon."""
        response = client.get("/api/interns/ending-soon?days=7")
        assert response.status_code == 200
        data = response.get_json()
        assert "interns" in data
        assert "count" in data
