"""
Tests for ConversationFlowHandler.

Tests multi-turn onboarding/offboarding flows including:
- State persistence in SQLite
- Cancel/back commands
- Field validation
- Flow completion
"""

import os
import pytest
import tempfile
from unittest.mock import Mock, patch

from src.bot.services.conversation_flow import ConversationFlowHandler, FlowResponse
from src.bot.database import (
    init_db,
    run_migrations,
    add_intern,
    get_active_flow,
    create_conversation_flow,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    init_db(db_path)
    run_migrations(db_path)

    yield db_path

    # Cleanup
    os.unlink(db_path)


@pytest.fixture
def flow_handler(temp_db):
    """Create a ConversationFlowHandler with mocked dependencies."""
    mock_n8n = Mock()
    mock_n8n.trigger_onboarding.return_value = {"status": "triggered"}
    mock_n8n.trigger_offboarding.return_value = {"status": "triggered"}

    mock_github = Mock()
    mock_github.validate_github_user.return_value = {
        "exists": True,
        "login": "testuser",
        "name": "Test User",
        "profile_url": "https://github.com/testuser",
    }
    mock_github.invite_to_org.return_value = {"success": True, "state": "pending"}
    mock_github.remove_from_org.return_value = {"success": True}

    handler = ConversationFlowHandler(
        db_path=temp_db,
        n8n_client=mock_n8n,
        github_client=mock_github,
        allowed_email_domains=["cloudwarriors.ai", "test.com"],
    )

    return handler


class TestConversationFlowStart:
    """Tests for starting conversation flows."""

    def test_start_onboarding_flow(self, flow_handler):
        """Test starting a new onboarding flow."""
        result = flow_handler.start_onboarding_flow(
            user_id="user123",
            channel_id="channel456",
            actor_name="Test Admin"
        )

        assert isinstance(result, FlowResponse)
        assert "full name" in result.message.lower()
        assert flow_handler.is_in_flow("user123")

    def test_start_onboarding_with_existing_flow(self, flow_handler, temp_db):
        """Test starting onboarding when user already has active flow."""
        # Start first flow
        flow_handler.start_onboarding_flow(user_id="user123", channel_id="ch1")

        # Try to start second flow
        result = flow_handler.start_onboarding_flow(user_id="user123", channel_id="ch2")

        assert "active" in result.message.lower()
        assert "continue" in result.message.lower() or "cancel" in result.message.lower()


class TestOnboardingFlow:
    """Tests for the onboarding flow steps."""

    def test_name_validation_valid(self, flow_handler):
        """Test valid name is accepted."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")

        result = flow_handler.handle_response(user_id="user1", text="Alice Johnson")

        # Should advance to email step
        assert "email" in result.message.lower()

    def test_name_validation_invalid(self, flow_handler):
        """Test invalid name is rejected."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")

        result = flow_handler.handle_response(user_id="user1", text="A")  # Too short

        assert "2 characters" in result.message.lower()

    def test_email_validation_valid(self, flow_handler):
        """Test valid email is accepted."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")
        flow_handler.handle_response(user_id="user1", text="Alice Johnson")

        result = flow_handler.handle_response(user_id="user1", text="alice@cloudwarriors.ai")

        # Should advance to GitHub step
        assert "github" in result.message.lower()

    def test_email_validation_invalid_format(self, flow_handler):
        """Test invalid email format is rejected."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")
        flow_handler.handle_response(user_id="user1", text="Alice Johnson")

        result = flow_handler.handle_response(user_id="user1", text="not-an-email")

        assert "invalid" in result.message.lower()

    def test_email_validation_wrong_domain(self, flow_handler):
        """Test email from non-allowed domain is rejected."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")
        flow_handler.handle_response(user_id="user1", text="Alice Johnson")

        result = flow_handler.handle_response(user_id="user1", text="alice@gmail.com")

        assert "cloudwarriors.ai" in result.message.lower() or "test.com" in result.message.lower()

    def test_github_validation(self, flow_handler):
        """Test GitHub username validation with confirmation."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")
        flow_handler.handle_response(user_id="user1", text="Alice Johnson")
        flow_handler.handle_response(user_id="user1", text="alice@cloudwarriors.ai")

        result = flow_handler.handle_response(user_id="user1", text="testuser")

        # Should ask for confirmation
        assert "testuser" in result.message
        assert "correct" in result.message.lower() or "yes" in result.message.lower()

    def test_github_confirmation_yes(self, flow_handler):
        """Test confirming GitHub username advances flow."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")
        flow_handler.handle_response(user_id="user1", text="Alice Johnson")
        flow_handler.handle_response(user_id="user1", text="alice@cloudwarriors.ai")
        flow_handler.handle_response(user_id="user1", text="testuser")

        result = flow_handler.handle_response(user_id="user1", text="yes")

        # Should advance to program step
        assert "program" in result.message.lower()

    def test_github_confirmation_no(self, flow_handler):
        """Test rejecting GitHub username goes back."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")
        flow_handler.handle_response(user_id="user1", text="Alice Johnson")
        flow_handler.handle_response(user_id="user1", text="alice@cloudwarriors.ai")
        flow_handler.handle_response(user_id="user1", text="testuser")

        result = flow_handler.handle_response(user_id="user1", text="no")

        # Should ask for GitHub again
        assert "github" in result.message.lower()


class TestFlowCommands:
    """Tests for cancel and back commands."""

    def test_cancel_flow(self, flow_handler):
        """Test cancelling an active flow."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")

        result = flow_handler.handle_response(user_id="user1", text="cancel")

        assert "cancelled" in result.message.lower()
        assert result.is_complete
        assert not flow_handler.is_in_flow("user1")

    def test_cancel_keywords(self, flow_handler):
        """Test various cancel keywords work."""
        for keyword in ["cancel", "stop", "abort", "quit", "nevermind"]:
            flow_handler.start_onboarding_flow(user_id=f"user_{keyword}", channel_id="ch1")

            result = flow_handler.handle_response(user_id=f"user_{keyword}", text=keyword)

            assert "cancelled" in result.message.lower()

    def test_back_from_second_step(self, flow_handler):
        """Test going back from second step."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")
        flow_handler.handle_response(user_id="user1", text="Alice Johnson")

        result = flow_handler.handle_response(user_id="user1", text="back")

        # Should be at name step again
        assert "name" in result.message.lower()

    def test_back_from_first_step(self, flow_handler):
        """Test can't go back from first step."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")

        result = flow_handler.handle_response(user_id="user1", text="back")

        assert "first step" in result.message.lower() or "cancel" in result.message.lower()


class TestFlowCompletion:
    """Tests for completing flows."""

    def test_complete_onboarding_flow(self, flow_handler, temp_db):
        """Test completing full onboarding flow."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1", actor_name="Admin")

        # Name
        flow_handler.handle_response(user_id="user1", text="Alice Johnson")
        # Email
        flow_handler.handle_response(user_id="user1", text="alice@cloudwarriors.ai")
        # GitHub
        flow_handler.handle_response(user_id="user1", text="testuser")
        # Confirm GitHub
        flow_handler.handle_response(user_id="user1", text="yes")
        # Program
        flow_handler.handle_response(user_id="user1", text="skillbridge")
        # Start date
        flow_handler.handle_response(user_id="user1", text="2026-02-01")
        # Supervisor
        flow_handler.handle_response(user_id="user1", text="Chad Simon")
        # Add to meetings
        result = flow_handler.handle_response(user_id="user1", text="now")

        # Should show confirmation
        assert "confirm" in result.message.lower()
        assert "Alice Johnson" in result.message
        assert "alice@cloudwarriors.ai" in result.message

        # Confirm
        result = flow_handler.handle_response(user_id="user1", text="confirm")

        assert result.is_complete
        assert "onboarded" in result.message.lower()
        assert not flow_handler.is_in_flow("user1")


class TestOffboardingFlow:
    """Tests for offboarding flow."""

    def test_start_offboarding_not_found(self, flow_handler):
        """Test offboarding non-existent intern."""
        result = flow_handler.start_offboarding_flow(
            user_id="user1",
            intern_name="Nobody",
            channel_id="ch1"
        )

        assert "not found" in result.message.lower() or "no intern" in result.message.lower()

    def test_start_offboarding_found(self, flow_handler, temp_db):
        """Test offboarding existing intern starts step-by-step flow."""
        # Add intern to database
        add_intern(
            temp_db,
            intern_id="int123",
            name="Bob Smith",
            email="bob@cloudwarriors.ai",
            program="skillbridge",
            supervisor="Chad",
        )

        result = flow_handler.start_offboarding_flow(
            user_id="user1",
            intern_name="Bob",
            channel_id="ch1"
        )

        # Should show intern info and first offboarding question (last day)
        assert "Bob Smith" in result.message
        assert "last day" in result.message.lower()

    def test_complete_offboarding(self, flow_handler, temp_db):
        """Test completing offboarding with step-by-step flow."""
        # Add intern
        add_intern(
            temp_db,
            intern_id="int123",
            name="Bob Smith",
            email="bob@cloudwarriors.ai",
            program="skillbridge",
            supervisor="Chad",
        )

        flow_handler.start_offboarding_flow(
            user_id="user1",
            intern_name="Bob",
            channel_id="ch1"
        )

        # Last day
        flow_handler.handle_response(user_id="user1", text="today")
        # Reason
        flow_handler.handle_response(user_id="user1", text="end of program")
        # Remove from meetings
        result = flow_handler.handle_response(user_id="user1", text="now")

        # Should show confirmation
        assert "confirm" in result.message.lower()
        assert "Bob Smith" in result.message

        # Confirm
        result = flow_handler.handle_response(user_id="user1", text="confirm")

        assert result.is_complete
        assert "offboarded" in result.message.lower()


class TestFieldValidation:
    """Tests for individual field validators."""

    def test_program_validation(self, flow_handler):
        """Test program field accepts valid values."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")
        flow_handler.handle_response(user_id="user1", text="Alice")
        flow_handler.handle_response(user_id="user1", text="alice@test.com")
        flow_handler.handle_response(user_id="user1", text="testuser")
        flow_handler.handle_response(user_id="user1", text="yes")

        # Valid program
        result = flow_handler.handle_response(user_id="user1", text="skillbridge")
        assert "start" in result.message.lower()  # Advances to start date step

        # Reset and test invalid
        flow_handler.start_onboarding_flow(user_id="user2", channel_id="ch1")
        flow_handler.handle_response(user_id="user2", text="Bob")
        flow_handler.handle_response(user_id="user2", text="bob@test.com")
        flow_handler.handle_response(user_id="user2", text="testuser")
        flow_handler.handle_response(user_id="user2", text="yes")

        result = flow_handler.handle_response(user_id="user2", text="invalid_program")
        assert "skillbridge" in result.message.lower()

    def test_date_validation(self, flow_handler):
        """Test date field validation."""
        flow_handler.start_onboarding_flow(user_id="user1", channel_id="ch1")
        flow_handler.handle_response(user_id="user1", text="Alice")
        flow_handler.handle_response(user_id="user1", text="alice@test.com")
        flow_handler.handle_response(user_id="user1", text="testuser")
        flow_handler.handle_response(user_id="user1", text="yes")
        flow_handler.handle_response(user_id="user1", text="vanderbilt")

        # Invalid format
        result = flow_handler.handle_response(user_id="user1", text="01/15/2026")
        assert "YYYY-MM-DD" in result.message

        # Valid format
        result = flow_handler.handle_response(user_id="user1", text="2026-02-15")
        assert "supervisor" in result.message.lower()


class TestNoActiveFlow:
    """Tests for handling responses without active flow."""

    def test_no_active_flow(self, flow_handler):
        """Test response when no flow is active."""
        result = flow_handler.handle_response(user_id="unknown_user", text="hello")

        assert "no active flow" in result.message.lower() or "onboard" in result.message.lower()
