"""
Tests for FlowCompletionHandler.

Tests onboarding and offboarding flow completion logic.
"""
import pytest
from unittest.mock import MagicMock, patch
import logging

from src.bot.services.flow_completion_handler import (
    FlowCompletionHandler,
    CompletionResult
)


class TestCompletionResult:
    """Tests for CompletionResult dataclass."""

    def test_success_result(self):
        """Test successful completion result."""
        result = CompletionResult(
            success=True,
            message="Intern onboarded successfully",
            intern_id="abc123",
            intern_name="John Doe"
        )

        assert result.success is True
        assert result.intern_id == "abc123"
        assert result.intern_name == "John Doe"
        assert result.error is None

    def test_failure_result(self):
        """Test failed completion result."""
        result = CompletionResult(
            success=False,
            message="Failed to create intern",
            error="database_error"
        )

        assert result.success is False
        assert result.error == "database_error"
        assert result.intern_id is None


class TestFlowCompletionHandler:
    """Tests for FlowCompletionHandler."""

    @pytest.fixture
    def mock_intern_repo(self):
        """Create a mock intern repository."""
        repo = MagicMock()
        repo.create.return_value = True
        repo.update_status.return_value = True
        return repo

    @pytest.fixture
    def mock_audit_repo(self):
        """Create a mock audit repository."""
        repo = MagicMock()
        repo.log_event.return_value = True
        return repo

    @pytest.fixture
    def mock_n8n_client(self):
        """Create a mock n8n client."""
        client = MagicMock()
        client.trigger_onboarding.return_value = {"success": True}
        client.trigger_offboarding.return_value = {"success": True}
        return client

    @pytest.fixture
    def mock_github_client(self):
        """Create a mock GitHub client."""
        client = MagicMock()
        client.invite_to_org.return_value = {"success": True, "state": "pending"}
        client.remove_from_org.return_value = {"success": True}
        return client

    @pytest.fixture
    def handler(self, mock_intern_repo, mock_audit_repo, mock_n8n_client, mock_github_client):
        """Create a FlowCompletionHandler with mocks."""
        return FlowCompletionHandler(
            intern_repo=mock_intern_repo,
            audit_repo=mock_audit_repo,
            n8n_client=mock_n8n_client,
            github_client=mock_github_client,
            zoom_meetings_client=None,
            meeting_ids=[],
            logger=logging.getLogger("test")
        )

    def test_complete_onboarding_success(self, handler, mock_intern_repo, mock_audit_repo):
        """Test successful onboarding completion."""
        flow = {"id": "flow123", "user_id": "user456"}
        collected = {
            "name": "John Doe",
            "email": "john@example.com",
            "program": "skillbridge",
            "supervisor": "Jane Smith",
            "start_date": "2024-02-01",
            "github_username": "johndoe"
        }

        result = handler.complete_onboarding(flow, collected, actor_name="Admin User")

        assert result.success is True
        assert result.intern_name == "John Doe"
        assert result.intern_id is not None

        # Verify intern was created
        mock_intern_repo.create.assert_called_once()
        call_kwargs = mock_intern_repo.create.call_args.kwargs
        assert call_kwargs["name"] == "John Doe"
        assert call_kwargs["email"] == "john@example.com"

        # Verify audit was logged
        mock_audit_repo.log_event.assert_called_once()

    def test_complete_onboarding_db_failure(self, handler, mock_intern_repo):
        """Test onboarding when database creation fails."""
        mock_intern_repo.create.return_value = False

        flow = {"id": "flow123", "user_id": "user456"}
        collected = {"name": "John Doe"}

        result = handler.complete_onboarding(flow, collected)

        assert result.success is False
        assert result.error == "database_error"

    def test_complete_onboarding_triggers_n8n(self, handler, mock_n8n_client):
        """Test that onboarding triggers n8n workflow."""
        flow = {"id": "flow123", "user_id": "user456"}
        collected = {
            "name": "John Doe",
            "email": "john@example.com",
            "program": "skillbridge"
        }

        result = handler.complete_onboarding(flow, collected)

        assert result.success is True
        mock_n8n_client.trigger_onboarding.assert_called_once()

    def test_complete_onboarding_invites_to_github(self, handler, mock_github_client):
        """Test that onboarding invites user to GitHub org."""
        flow = {"id": "flow123", "user_id": "user456"}
        collected = {
            "name": "John Doe",
            "github_username": "johndoe"
        }

        result = handler.complete_onboarding(flow, collected)

        assert result.success is True
        mock_github_client.invite_to_org.assert_called_once_with("johndoe")

    def test_complete_onboarding_no_github_username(self, handler, mock_github_client):
        """Test onboarding without GitHub username doesn't call invite."""
        flow = {"id": "flow123", "user_id": "user456"}
        collected = {"name": "John Doe"}

        result = handler.complete_onboarding(flow, collected)

        assert result.success is True
        mock_github_client.invite_to_org.assert_not_called()

    def test_complete_offboarding_success(self, handler, mock_intern_repo, mock_audit_repo):
        """Test successful offboarding completion."""
        flow = {"id": "flow123", "user_id": "user456"}
        collected = {
            "intern_id": "intern789",
            "name": "John Doe",
            "email": "john@example.com",
            "github_username": "johndoe"
        }

        result = handler.complete_offboarding(flow, collected, actor_name="Admin User")

        assert result.success is True
        assert result.intern_name == "John Doe"
        assert result.intern_id == "intern789"

        # Verify status was updated
        mock_intern_repo.update_status.assert_called_once()

        # Verify audit was logged
        mock_audit_repo.log_event.assert_called_once()

    def test_complete_offboarding_removes_from_github(self, handler, mock_github_client):
        """Test that offboarding removes user from GitHub org."""
        flow = {"id": "flow123", "user_id": "user456"}
        collected = {
            "intern_id": "intern789",
            "name": "John Doe",
            "github_username": "johndoe"
        }

        result = handler.complete_offboarding(flow, collected)

        assert result.success is True
        mock_github_client.remove_from_org.assert_called_once_with("johndoe")

    def test_complete_offboarding_triggers_n8n(self, handler, mock_n8n_client):
        """Test that offboarding triggers n8n workflow."""
        flow = {"id": "flow123", "user_id": "user456"}
        collected = {
            "intern_id": "intern789",
            "name": "John Doe",
            "email": "john@example.com"
        }

        result = handler.complete_offboarding(flow, collected)

        assert result.success is True
        mock_n8n_client.trigger_offboarding.assert_called_once()

    def test_onboarding_message_includes_github_invite(self, handler, mock_github_client):
        """Test onboarding success message mentions GitHub invite."""
        mock_github_client.invite_to_org.return_value = {"success": True, "state": "pending"}

        flow = {"id": "flow123", "user_id": "user456"}
        collected = {
            "name": "John Doe",
            "github_username": "johndoe"
        }

        result = handler.complete_onboarding(flow, collected)

        assert "GitHub" in result.message
        assert "johndoe" in result.message

    def test_offboarding_message_includes_github_removal(self, handler, mock_github_client):
        """Test offboarding success message mentions GitHub removal."""
        flow = {"id": "flow123", "user_id": "user456"}
        collected = {
            "intern_id": "intern789",
            "name": "John Doe",
            "github_username": "johndoe"
        }

        result = handler.complete_offboarding(flow, collected)

        assert "GitHub" in result.message

    def test_handler_without_optional_clients(self, mock_intern_repo, mock_audit_repo):
        """Test handler works without optional clients."""
        handler = FlowCompletionHandler(
            intern_repo=mock_intern_repo,
            audit_repo=mock_audit_repo,
            n8n_client=None,
            github_client=None,
            zoom_meetings_client=None,
            meeting_ids=[],
            logger=logging.getLogger("test")
        )

        flow = {"id": "flow123", "user_id": "user456"}
        collected = {"name": "John Doe"}

        result = handler.complete_onboarding(flow, collected)

        assert result.success is True

    def test_onboarding_exception_handling(self, handler, mock_intern_repo):
        """Test that exceptions are caught and returned as errors."""
        mock_intern_repo.create.side_effect = Exception("Database connection failed")

        flow = {"id": "flow123", "user_id": "user456"}
        collected = {"name": "John Doe"}

        result = handler.complete_onboarding(flow, collected)

        assert result.success is False
        assert "Database connection failed" in result.message

    def test_offboarding_exception_handling(self, handler, mock_intern_repo):
        """Test that exceptions during offboarding are handled."""
        mock_intern_repo.update_status.side_effect = Exception("Update failed")

        flow = {"id": "flow123", "user_id": "user456"}
        collected = {"intern_id": "intern789", "name": "John Doe"}

        result = handler.complete_offboarding(flow, collected)

        assert result.success is False
        assert "Update failed" in result.message
