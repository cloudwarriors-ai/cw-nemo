"""
Tests for the new chat-based workflow capabilities.

Tests onboarding, offboarding, intern_status, and meeting_join
intent detection and handling.
"""

import pytest
from unittest.mock import Mock, patch


class TestCapabilityEnum:
    """Test that new capabilities are defined."""

    def test_new_capabilities_exist(self):
        """Verify new capabilities are in the enum."""
        from src.bot.llm_brain import Capability

        assert Capability.ONBOARDING.value == "onboarding"
        assert Capability.OFFBOARDING.value == "offboarding"
        assert Capability.MEETING_JOIN.value == "meeting_join"
        assert Capability.INTERN_STATUS.value == "intern_status"


class TestIntentMapping:
    """Test intent string to capability mapping."""

    def test_maps_onboarding_intent(self):
        """Test onboarding intent mapping."""
        from src.bot.llm_brain import QABrain, Capability

        brain = QABrain(api_key="test-key", repos=["test-repo"])
        assert brain._map_intent_to_capability("onboarding") == Capability.ONBOARDING

    def test_maps_offboarding_intent(self):
        """Test offboarding intent mapping."""
        from src.bot.llm_brain import QABrain, Capability

        brain = QABrain(api_key="test-key", repos=["test-repo"])
        assert brain._map_intent_to_capability("offboarding") == Capability.OFFBOARDING

    def test_maps_meeting_join_intent(self):
        """Test meeting_join intent mapping."""
        from src.bot.llm_brain import QABrain, Capability

        brain = QABrain(api_key="test-key", repos=["test-repo"])
        assert brain._map_intent_to_capability("meeting_join") == Capability.MEETING_JOIN

    def test_maps_intern_status_intent(self):
        """Test intern_status intent mapping."""
        from src.bot.llm_brain import QABrain, Capability

        brain = QABrain(api_key="test-key", repos=["test-repo"])
        assert brain._map_intent_to_capability("intern_status") == Capability.INTERN_STATUS


class TestHelpResponse:
    """Test that help response includes new capabilities."""

    def test_help_includes_onboarding(self):
        """Help should mention onboarding."""
        from src.bot.prompts import HELP_RESPONSE

        assert "onboard" in HELP_RESPONSE.lower()

    def test_help_includes_offboarding(self):
        """Help should mention offboarding."""
        from src.bot.prompts import HELP_RESPONSE

        assert "offboard" in HELP_RESPONSE.lower()

    def test_help_includes_intern_status(self):
        """Help should mention intern status."""
        from src.bot.prompts import HELP_RESPONSE

        assert "intern" in HELP_RESPONSE.lower()

    def test_help_includes_meeting(self):
        """Help should mention meeting join."""
        from src.bot.prompts import HELP_RESPONSE

        assert "join" in HELP_RESPONSE.lower() and "meeting" in HELP_RESPONSE.lower()


class TestQueryPrompt:
    """Test that query prompt includes new intent types."""

    def test_prompt_includes_onboarding_intent(self):
        """Prompt should list onboarding intent."""
        from src.bot.prompts import ISSUE_QUERY_PROMPT

        assert "onboarding" in ISSUE_QUERY_PROMPT.lower()

    def test_prompt_includes_offboarding_intent(self):
        """Prompt should list offboarding intent."""
        from src.bot.prompts import ISSUE_QUERY_PROMPT

        assert "offboarding" in ISSUE_QUERY_PROMPT.lower()

    def test_prompt_includes_person_name_field(self):
        """Prompt should define person_name extraction."""
        from src.bot.prompts import ISSUE_QUERY_PROMPT

        assert "person_name" in ISSUE_QUERY_PROMPT

    def test_prompt_includes_meeting_name_field(self):
        """Prompt should define meeting_name extraction."""
        from src.bot.prompts import ISSUE_QUERY_PROMPT

        assert "meeting_name" in ISSUE_QUERY_PROMPT


class TestOnboardingHandler:
    """Test onboarding request handler."""

    def test_handles_missing_name(self):
        """Handler should prompt for name if missing."""
        from src.bot.app import _handle_onboarding_request
        from flask import Flask

        app = Flask(__name__)
        app.n8n_client = Mock()

        result = _handle_onboarding_request(app, {}, "user", "req-1")
        assert "need a name" in result.lower()

    def test_handles_missing_n8n_client(self):
        """Handler should explain when n8n not configured."""
        from src.bot.app import _handle_onboarding_request
        from flask import Flask

        app = Flask(__name__)
        app.n8n_client = None

        result = _handle_onboarding_request(
            app, {"person_name": "alice"}, "user", "req-1"
        )
        assert "workflow" in result.lower()
        assert "configured" in result.lower()


class TestOffboardingHandler:
    """Test offboarding request handler."""

    def test_handles_missing_name(self):
        """Handler should prompt for name if missing."""
        from src.bot.app import _handle_offboarding_request
        from flask import Flask

        app = Flask(__name__)
        app.n8n_client = Mock()

        result = _handle_offboarding_request(app, {}, "user", "req-1")
        assert "need a name" in result.lower()


class TestMeetingJoinHandler:
    """Test meeting join request handler."""

    def test_handles_missing_handler(self):
        """Handler should explain when meeting not configured."""
        from src.bot.app import _handle_meeting_join_request
        from flask import Flask

        app = Flask(__name__)
        app.meeting_handler = None

        result = _handle_meeting_join_request(
            app, {"meeting_name": "standup"}, "user", "req-1"
        )
        assert "configured" in result.lower()

    def test_prompts_for_url(self):
        """Handler should ask for meeting URL."""
        from src.bot.app import _handle_meeting_join_request
        from flask import Flask

        app = Flask(__name__)
        app.meeting_handler = Mock()

        result = _handle_meeting_join_request(
            app, {"meeting_name": "standup"}, "user", "req-1"
        )
        assert "url" in result.lower()


class TestInternStatusHandler:
    """Test intern status request handler."""

    def test_handles_no_interns(self):
        """Handler should report when no interns found."""
        from src.bot.app import _handle_intern_status_request
        from flask import Flask

        app = Flask(__name__)
        app.config = {"DB_PATH": ":memory:"}
        app.response_builder = Mock()

        # Patch at the database module level since it's imported inline
        with patch("src.bot.database.get_all_interns") as mock_get:
            mock_get.return_value = []
            result = _handle_intern_status_request(app, {}, "req-1")
            assert "no active interns" in result.lower()


class TestWeeklyReportCapability:
    """Test weekly report capability."""

    def test_weekly_report_capability_exists(self):
        """Verify WEEKLY_REPORT capability is defined."""
        from src.bot.llm_brain import Capability

        assert Capability.WEEKLY_REPORT.value == "weekly_report"

    def test_maps_weekly_report_intent(self):
        """Test weekly_report intent mapping."""
        from src.bot.llm_brain import QABrain, Capability

        brain = QABrain(api_key="test-key", repos=["test-repo"])
        assert brain._map_intent_to_capability("weekly_report") == Capability.WEEKLY_REPORT

    def test_help_includes_weekly_report(self):
        """Help should mention weekly report."""
        from src.bot.prompts import HELP_RESPONSE

        assert "weekly report" in HELP_RESPONSE.lower()

    def test_prompt_includes_weekly_report_intent(self):
        """Prompt should list weekly_report intent."""
        from src.bot.prompts import ISSUE_QUERY_PROMPT

        assert "weekly_report" in ISSUE_QUERY_PROMPT.lower()


class TestWeeklyReportHandler:
    """Test weekly report request handler."""

    def test_handles_missing_orchestrator(self):
        """Handler should explain when orchestrator not configured."""
        from src.bot.app import _handle_weekly_report_request
        from flask import Flask

        app = Flask(__name__)
        app.workflow_orchestrator = None
        app.logger = Mock()

        result = _handle_weekly_report_request(app, "channel-123", "req-1")
        assert "configured" in result.lower()

    def test_handles_missing_channel(self):
        """Handler should explain when channel not provided."""
        from src.bot.app import _handle_weekly_report_request
        from flask import Flask

        app = Flask(__name__)
        app.workflow_orchestrator = Mock()
        app.logger = Mock()

        result = _handle_weekly_report_request(app, None, "req-1")
        assert "channel" in result.lower()

    def test_successful_report_posts(self):
        """Handler should confirm when report posts successfully."""
        from src.bot.app import _handle_weekly_report_request
        from src.bot.services import WorkflowResult
        from flask import Flask

        app = Flask(__name__)
        mock_orchestrator = Mock()
        mock_orchestrator.execute_weekly_report.return_value = WorkflowResult(
            success=True,
            workflow_name="weekly_report",
            delivery_success=True
        )
        app.workflow_orchestrator = mock_orchestrator
        app.logger = Mock()

        result = _handle_weekly_report_request(app, "channel-123", "req-1")
        assert "posted" in result.lower()
