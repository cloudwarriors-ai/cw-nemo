"""
Tests for the WorkflowOrchestrator.

Tests the Mediator pattern implementation that coordinates
services -> brain -> channels.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch


class TestWorkflowResult:
    """Tests for the WorkflowResult dataclass."""

    def test_result_creation(self):
        """Test creating a workflow result."""
        from src.bot.services import WorkflowResult

        result = WorkflowResult(
            success=True,
            workflow_name="weekly_report",
            data={"total_issues": 42},
            formatted_content="Report content",
            delivery_success=True
        )

        assert result.success is True
        assert result.workflow_name == "weekly_report"
        assert result.data["total_issues"] == 42
        assert result.delivery_success is True

    def test_result_with_warnings(self):
        """Test result with warnings."""
        from src.bot.services import WorkflowResult

        result = WorkflowResult(
            success=True,
            workflow_name="hygiene_check",
            warnings=["Cache was stale", "One repo unavailable"]
        )

        assert len(result.warnings) == 2

    def test_result_to_dict(self):
        """Test result serialization."""
        from src.bot.services import WorkflowResult

        result = WorkflowResult(
            success=True,
            workflow_name="feedback_reminder",
            formatted_content="Long content here..."
        )
        data = result.to_dict()

        assert data["success"] is True
        assert data["workflow_name"] == "feedback_reminder"
        assert "executed_at" in data


class TestWorkflowOrchestratorInit:
    """Tests for WorkflowOrchestrator initialization."""

    def test_orchestrator_initialization(self):
        """Test orchestrator initializes with all components."""
        from src.bot.services import WorkflowOrchestrator

        mock_brain = Mock()
        mock_channel_manager = Mock()
        mock_report_service = Mock()
        mock_hygiene_service = Mock()
        mock_feedback_service = Mock()

        orchestrator = WorkflowOrchestrator(
            qa_brain=mock_brain,
            channel_manager=mock_channel_manager,
            report_service=mock_report_service,
            hygiene_service=mock_hygiene_service,
            feedback_service=mock_feedback_service
        )

        assert orchestrator._brain == mock_brain
        assert orchestrator._channel_manager == mock_channel_manager
        assert orchestrator._report_service == mock_report_service

    def test_orchestrator_partial_init(self):
        """Test orchestrator with only some services."""
        from src.bot.services import WorkflowOrchestrator

        mock_brain = Mock()
        mock_channel_manager = Mock()

        orchestrator = WorkflowOrchestrator(
            qa_brain=mock_brain,
            channel_manager=mock_channel_manager,
            report_service=None,
            hygiene_service=None,
            feedback_service=None
        )

        assert orchestrator._report_service is None


class TestWeeklyReportWorkflow:
    """Tests for the weekly report workflow."""

    def test_execute_weekly_report_success(self):
        """Test successful weekly report execution."""
        from src.bot.services import WorkflowOrchestrator
        from src.bot.channels import ChannelType, Message, DeliveryResult

        # Mock services
        mock_brain = Mock()

        mock_channel_manager = Mock()
        mock_channel_manager.send.return_value = DeliveryResult(
            success=True,
            channel=ChannelType.ZOOM
        )

        mock_report = Mock()
        mock_report.to_dict.return_value = {"total_issues": 42, "high_priority": 5}
        mock_report.has_valid_data = True
        mock_report.high_priority = 5

        mock_report_service = Mock()
        mock_report_service.generate_weekly_report.return_value = mock_report
        mock_report_service.format_as_table.return_value = "**GITHUB Issues Tracker**\n..."

        orchestrator = WorkflowOrchestrator(
            qa_brain=mock_brain,
            channel_manager=mock_channel_manager,
            report_service=mock_report_service
        )

        result = orchestrator.execute_weekly_report(
            channel=ChannelType.ZOOM,
            destination="channel@zoom.us",
            upload_to_drive=False  # Disable n8n upload for this test
        )

        assert result.success is True
        assert result.delivery_success is True
        assert result.workflow_name == "weekly_report"
        mock_report_service.format_as_table.assert_called_once()
        mock_channel_manager.send.assert_called_once()

    def test_execute_weekly_report_no_service(self):
        """Test weekly report when service not configured."""
        from src.bot.services import WorkflowOrchestrator
        from src.bot.channels import ChannelType

        orchestrator = WorkflowOrchestrator(
            qa_brain=Mock(),
            channel_manager=Mock(),
            report_service=None  # Not configured
        )

        result = orchestrator.execute_weekly_report(
            channel=ChannelType.ZOOM,
            destination="channel@zoom.us"
        )

        assert result.success is False
        assert "ReportService not configured" in result.warnings

    def test_execute_weekly_report_delivery_failure(self):
        """Test weekly report with delivery failure."""
        from src.bot.services import WorkflowOrchestrator
        from src.bot.channels import ChannelType, DeliveryResult

        mock_brain = Mock()
        mock_brain.enhance_workflow_output.return_value = "Report content"

        mock_channel_manager = Mock()
        mock_channel_manager.send.return_value = DeliveryResult(
            success=False,
            channel=ChannelType.ZOOM,
            error="Connection timeout"
        )

        mock_report = Mock()
        mock_report.to_dict.return_value = {}
        mock_report.has_valid_data = True
        mock_report.high_priority = 0

        mock_report_service = Mock()
        mock_report_service.generate_weekly_report.return_value = mock_report

        orchestrator = WorkflowOrchestrator(
            qa_brain=mock_brain,
            channel_manager=mock_channel_manager,
            report_service=mock_report_service
        )

        result = orchestrator.execute_weekly_report(
            channel=ChannelType.ZOOM,
            destination="channel@zoom.us"
        )

        assert result.success is True  # Report generated
        assert result.delivery_success is False  # But delivery failed
        assert result.delivery_error == "Connection timeout"


class TestHygieneCheckWorkflow:
    """Tests for the hygiene check workflow."""

    def test_execute_hygiene_check_success(self):
        """Test successful hygiene check execution."""
        from src.bot.services import WorkflowOrchestrator
        from src.bot.channels import ChannelType, DeliveryResult

        mock_brain = Mock()
        mock_brain.enhance_workflow_output.return_value = "Hygiene report"

        mock_channel_manager = Mock()
        mock_channel_manager.send.return_value = DeliveryResult(
            success=True,
            channel=ChannelType.ZOOM
        )

        mock_report = Mock()
        mock_report.to_dict.return_value = {"issues_needing_attention": 10}
        mock_report.has_valid_data = True
        mock_report.issues_needing_attention = 10

        mock_hygiene_service = Mock()
        mock_hygiene_service.check_hygiene.return_value = mock_report

        orchestrator = WorkflowOrchestrator(
            qa_brain=mock_brain,
            channel_manager=mock_channel_manager,
            hygiene_service=mock_hygiene_service
        )

        result = orchestrator.execute_hygiene_check(
            channel=ChannelType.ZOOM,
            destination="channel@zoom.us"
        )

        assert result.success is True
        assert result.delivery_success is True

    def test_execute_hygiene_check_no_service(self):
        """Test hygiene check when service not configured."""
        from src.bot.services import WorkflowOrchestrator
        from src.bot.channels import ChannelType

        orchestrator = WorkflowOrchestrator(
            qa_brain=Mock(),
            channel_manager=Mock(),
            hygiene_service=None
        )

        result = orchestrator.execute_hygiene_check(
            channel=ChannelType.ZOOM,
            destination="channel@zoom.us"
        )

        assert result.success is False
        assert "HygieneService not configured" in result.warnings


class TestFeedbackReminderWorkflow:
    """Tests for the feedback reminder workflow."""

    def test_execute_feedback_reminder_success(self):
        """Test successful feedback reminder execution."""
        from src.bot.services import WorkflowOrchestrator
        from src.bot.channels import ChannelType, DeliveryResult

        mock_brain = Mock()
        mock_brain.enhance_workflow_output.return_value = "Feedback reminder"

        mock_channel_manager = Mock()
        mock_channel_manager.send.return_value = DeliveryResult(
            success=True,
            channel=ChannelType.ZOOM
        )

        mock_reminder = Mock()
        mock_reminder.to_dict.return_value = {"total_interns": 3}
        mock_reminder.has_valid_data = True
        mock_reminder.total_interns = 3

        mock_feedback_service = Mock()
        mock_feedback_service.generate_feedback_reminder.return_value = mock_reminder

        orchestrator = WorkflowOrchestrator(
            qa_brain=mock_brain,
            channel_manager=mock_channel_manager,
            feedback_service=mock_feedback_service
        )

        result = orchestrator.execute_feedback_reminder(
            channel=ChannelType.ZOOM,
            destination="channel@zoom.us"
        )

        assert result.success is True
        assert result.delivery_success is True

    def test_execute_feedback_reminder_no_interns(self):
        """Test feedback reminder when no interns need feedback."""
        from src.bot.services import WorkflowOrchestrator
        from src.bot.channels import ChannelType

        mock_brain = Mock()
        mock_brain.enhance_workflow_output.return_value = "No interns"

        mock_channel_manager = Mock()

        mock_reminder = Mock()
        mock_reminder.to_dict.return_value = {"total_interns": 0}
        mock_reminder.has_valid_data = True
        mock_reminder.total_interns = 0

        mock_feedback_service = Mock()
        mock_feedback_service.generate_feedback_reminder.return_value = mock_reminder

        orchestrator = WorkflowOrchestrator(
            qa_brain=mock_brain,
            channel_manager=mock_channel_manager,
            feedback_service=mock_feedback_service
        )

        result = orchestrator.execute_feedback_reminder(
            channel=ChannelType.ZOOM,
            destination="channel@zoom.us"
        )

        assert result.success is True
        assert result.delivery_success is True  # No-op is success
        assert "No interns require feedback" in result.warnings
        mock_channel_manager.send.assert_not_called()  # Should skip delivery

    def test_execute_feedback_reminder_no_service(self):
        """Test feedback reminder when service not configured."""
        from src.bot.services import WorkflowOrchestrator
        from src.bot.channels import ChannelType

        orchestrator = WorkflowOrchestrator(
            qa_brain=Mock(),
            channel_manager=Mock(),
            feedback_service=None
        )

        result = orchestrator.execute_feedback_reminder(
            channel=ChannelType.ZOOM,
            destination="channel@zoom.us"
        )

        assert result.success is False
        assert "FeedbackService not configured" in result.warnings


class TestExecuteAllScheduled:
    """Tests for the execute_all_scheduled convenience method."""

    def test_execute_all_scheduled(self):
        """Test executing all scheduled workflows."""
        from src.bot.services import WorkflowOrchestrator
        from src.bot.channels import ChannelType, DeliveryResult

        mock_brain = Mock()
        mock_brain.enhance_workflow_output.return_value = "Content"

        mock_channel_manager = Mock()
        mock_channel_manager.send.return_value = DeliveryResult(
            success=True,
            channel=ChannelType.ZOOM
        )

        # Mock all services
        mock_report = Mock()
        mock_report.to_dict.return_value = {}
        mock_report.has_valid_data = True
        mock_report.high_priority = 0

        mock_hygiene = Mock()
        mock_hygiene.to_dict.return_value = {}
        mock_hygiene.has_valid_data = True
        mock_hygiene.issues_needing_attention = 5

        mock_reminder = Mock()
        mock_reminder.to_dict.return_value = {}
        mock_reminder.has_valid_data = True
        mock_reminder.total_interns = 2

        mock_report_service = Mock()
        mock_report_service.generate_weekly_report.return_value = mock_report

        mock_hygiene_service = Mock()
        mock_hygiene_service.check_hygiene.return_value = mock_hygiene

        mock_feedback_service = Mock()
        mock_feedback_service.generate_feedback_reminder.return_value = mock_reminder

        orchestrator = WorkflowOrchestrator(
            qa_brain=mock_brain,
            channel_manager=mock_channel_manager,
            report_service=mock_report_service,
            hygiene_service=mock_hygiene_service,
            feedback_service=mock_feedback_service
        )

        results = orchestrator.execute_all_scheduled(
            channel=ChannelType.ZOOM,
            destination="channel@zoom.us"
        )

        assert "weekly_report" in results
        assert "hygiene_check" in results
        assert "feedback_reminder" in results
        assert all(r.success for r in results.values())

    def test_execute_all_scheduled_partial(self):
        """Test executing all with only some services configured."""
        from src.bot.services import WorkflowOrchestrator
        from src.bot.channels import ChannelType, DeliveryResult

        mock_brain = Mock()
        mock_brain.enhance_workflow_output.return_value = "Content"

        mock_channel_manager = Mock()
        mock_channel_manager.send.return_value = DeliveryResult(
            success=True,
            channel=ChannelType.ZOOM
        )

        mock_report = Mock()
        mock_report.to_dict.return_value = {}
        mock_report.has_valid_data = True
        mock_report.high_priority = 0

        mock_report_service = Mock()
        mock_report_service.generate_weekly_report.return_value = mock_report

        orchestrator = WorkflowOrchestrator(
            qa_brain=mock_brain,
            channel_manager=mock_channel_manager,
            report_service=mock_report_service,
            hygiene_service=None,  # Not configured
            feedback_service=None  # Not configured
        )

        results = orchestrator.execute_all_scheduled(
            channel=ChannelType.ZOOM,
            destination="channel@zoom.us"
        )

        # Should only have weekly_report
        assert "weekly_report" in results
        assert "hygiene_check" not in results
        assert "feedback_reminder" not in results
