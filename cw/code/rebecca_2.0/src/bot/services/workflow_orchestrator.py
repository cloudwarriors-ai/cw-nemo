"""
Workflow Orchestrator - coordinates workflow execution through the brain.

Implements the Mediator pattern to coordinate:
- Workflow services (report, hygiene, feedback) for raw data
- QA Brain for intelligent formatting
- Channel Manager for delivery

All workflow outputs route through this orchestrator to ensure
consistent processing and channel-agnostic delivery.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm_brain import QABrain
    from ..channels import ChannelManager, ChannelType
    from ..n8n_client import N8nClient
    from .report_service import ReportService
    from .hygiene_service import HygieneService
    from .feedback_service import FeedbackService


@dataclass
class WorkflowResult:
    """Result of workflow execution."""

    success: bool
    workflow_name: str
    data: Optional[dict] = None
    formatted_content: str = ""
    delivery_success: bool = False
    delivery_error: Optional[str] = None
    executed_at: datetime = field(default_factory=datetime.now)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "workflow_name": self.workflow_name,
            "data": self.data,
            "formatted_content": self.formatted_content[:500] if self.formatted_content else "",
            "delivery_success": self.delivery_success,
            "delivery_error": self.delivery_error,
            "executed_at": self.executed_at.isoformat(),
            "warnings": self.warnings,
        }


class WorkflowOrchestrator:
    """
    Central coordinator for workflow execution.

    Implements the Mediator pattern to decouple workflow services
    from delivery channels. All workflows follow the same pattern:

    1. Service generates raw data
    2. Brain enhances/formats the data
    3. Channel delivers the formatted message

    This ensures consistent processing and allows:
    - Easy addition of new workflows
    - Swappable channels without service changes
    - LLM-enhanced output with fallback
    """

    def __init__(
        self,
        qa_brain: "QABrain",
        channel_manager: "ChannelManager",
        report_service: Optional["ReportService"] = None,
        hygiene_service: Optional["HygieneService"] = None,
        feedback_service: Optional["FeedbackService"] = None,
        n8n_client: Optional["N8nClient"] = None,
        logger: logging.Logger = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            qa_brain: QABrain instance for content enhancement
            channel_manager: ChannelManager for message delivery
            report_service: Optional ReportService for weekly reports
            hygiene_service: Optional HygieneService for hygiene checks
            feedback_service: Optional FeedbackService for intern reminders
            n8n_client: Optional N8nClient for workflow automation
            logger: Logger instance
        """
        self._brain = qa_brain
        self._channel_manager = channel_manager
        self._report_service = report_service
        self._hygiene_service = hygiene_service
        self._feedback_service = feedback_service
        self._n8n_client = n8n_client
        self.logger = logger or logging.getLogger("qa_agent")

    def execute_weekly_report(
        self,
        channel: "ChannelType",
        destination: str = None,
        force_refresh: bool = False,
        upload_to_drive: bool = True,
    ) -> WorkflowResult:
        """
        Execute weekly report workflow.

        1. Generate report from ReportService
        2. Format as text table
        3. Generate Excel and upload to Google Drive (if n8n configured)
        4. Deliver via specified channel with Drive link

        Args:
            channel: Target channel type
            destination: Override default destination
            force_refresh: Force cache refresh before report
            upload_to_drive: Whether to upload Excel to Google Drive

        Returns:
            WorkflowResult with execution status
        """
        from datetime import datetime
        from ..channels import Message

        result = WorkflowResult(
            success=False,
            workflow_name="weekly_report",
        )

        if not self._report_service:
            result.warnings.append("ReportService not configured")
            self.logger.warning("Weekly report requested but ReportService not configured")
            return result

        try:
            # Step 1: Generate raw data
            report = self._report_service.generate_weekly_report()
            result.data = report.to_dict()

            if not report.has_valid_data:
                result.warnings.append(report.error or "Invalid data")
                self.logger.warning(f"Weekly report has invalid data: {report.error}")

            # Step 2: Format as text table (matching QA Excel format)
            result.formatted_content = self._report_service.format_as_table()

            # Step 3: Generate Excel and upload to Google Drive
            drive_link = None
            if upload_to_drive and self._n8n_client:
                drive_link = self._upload_excel_to_drive()
                if drive_link:
                    result.formatted_content += f"\n\n**Full Report:** {drive_link}"
                else:
                    result.warnings.append("Excel upload to Google Drive failed")

            result.success = True

            # Step 4: Deliver via channel
            message = Message(
                content=result.formatted_content,
                title="Weekly Issue Report",
                priority="high" if report.high_priority > 5 else "normal",
                source_service="report",
                metadata={
                    "total_issues": report.total_issues,
                    "drive_link": drive_link
                },
            )

            delivery = self._channel_manager.send(message, channel, destination)
            result.delivery_success = delivery.success
            result.delivery_error = delivery.error

            self.logger.info(
                f"Weekly report workflow: success={result.success}, "
                f"delivered={result.delivery_success}, drive_link={bool(drive_link)}"
            )

        except Exception as e:
            self.logger.error(f"Weekly report workflow failed: {e}")
            result.warnings.append(str(e))

        return result

    def _upload_excel_to_drive(self) -> Optional[str]:
        """
        Generate Excel report and upload to Google Drive.

        Returns:
            Google Drive shareable link, or None if upload fails
        """
        from datetime import datetime

        self.logger.debug(f"_upload_excel_to_drive: n8n_client={bool(self._n8n_client)}, report_service={bool(self._report_service)}")

        if not self._n8n_client or not self._report_service:
            self.logger.warning("Skipping Excel upload: n8n_client or report_service not configured")
            return None

        try:
            # Generate Excel file
            excel_base64 = self._report_service.generate_excel_base64()
            if not excel_base64:
                self.logger.warning("Failed to generate Excel file")
                return None

            # Generate filename with date
            date_str = datetime.now().strftime("%Y%m%d")
            filename = f"Github_Issues_{date_str}.xlsx"

            # Upload via n8n
            result = self._n8n_client.trigger_report_upload(
                file_base64=excel_base64,
                filename=filename,
                report_type="weekly_issues"
            )

            if result.get("status") == "completed" and result.get("drive_link"):
                self.logger.info(f"Excel uploaded to Drive: {result['drive_link']}")
                return result["drive_link"]
            else:
                self.logger.warning(f"Excel upload failed: {result.get('error', 'Unknown error')}")
                return None

        except Exception as e:
            self.logger.error(f"Failed to upload Excel to Drive: {e}")
            return None

    def execute_hygiene_check(
        self,
        channel: "ChannelType",
        destination: str = None,
    ) -> WorkflowResult:
        """
        Execute hygiene check workflow.

        1. Run hygiene check from HygieneService
        2. Enhance via QA Brain
        3. Deliver via specified channel

        Args:
            channel: Target channel type
            destination: Override default destination

        Returns:
            WorkflowResult with execution status
        """
        from ..channels import Message

        result = WorkflowResult(
            success=False,
            workflow_name="hygiene_check",
        )

        if not self._hygiene_service:
            result.warnings.append("HygieneService not configured")
            self.logger.warning("Hygiene check requested but HygieneService not configured")
            return result

        try:
            # Step 1: Generate raw data
            report = self._hygiene_service.check_hygiene()
            result.data = report.to_dict()

            if not report.has_valid_data:
                result.warnings.append(report.error or "Invalid data")
                self.logger.warning(f"Hygiene check has invalid data: {report.error}")

            # Step 2: Enhance via brain
            result.formatted_content = self._brain.enhance_workflow_output(
                service_name="hygiene",
                raw_data=result.data,
                output_channel=channel.value,
            )
            result.success = True

            # Step 3: Deliver via channel
            needs_attention = report.issues_needing_attention
            message = Message(
                content=result.formatted_content,
                title="Issue Hygiene Report",
                priority="high" if needs_attention > 10 else "normal",
                source_service="hygiene",
                metadata={"issues_needing_attention": needs_attention},
            )

            delivery = self._channel_manager.send(message, channel, destination)
            result.delivery_success = delivery.success
            result.delivery_error = delivery.error

            self.logger.info(
                f"Hygiene check workflow: success={result.success}, "
                f"delivered={result.delivery_success}"
            )

        except Exception as e:
            self.logger.error(f"Hygiene check workflow failed: {e}")
            result.warnings.append(str(e))

        return result

    def execute_feedback_reminder(
        self,
        channel: "ChannelType",
        destination: str = None,
    ) -> WorkflowResult:
        """
        Execute feedback reminder workflow.

        1. Generate reminder from FeedbackService
        2. Enhance via QA Brain
        3. Deliver via specified channel

        Args:
            channel: Target channel type
            destination: Override default destination

        Returns:
            WorkflowResult with execution status
        """
        from ..channels import Message

        result = WorkflowResult(
            success=False,
            workflow_name="feedback_reminder",
        )

        if not self._feedback_service:
            result.warnings.append("FeedbackService not configured")
            self.logger.warning("Feedback reminder requested but FeedbackService not configured")
            return result

        try:
            # Step 1: Generate raw data
            reminder = self._feedback_service.generate_feedback_reminder()
            result.data = reminder.to_dict()

            if not reminder.has_valid_data:
                result.warnings.append(reminder.error or "Invalid data")
                self.logger.warning(f"Feedback reminder has invalid data: {reminder.error}")

            # Step 2: Enhance via brain
            result.formatted_content = self._brain.enhance_workflow_output(
                service_name="feedback",
                raw_data=result.data,
                output_channel=channel.value,
            )
            result.success = True

            # Step 3: Deliver via channel (skip if no interns)
            if reminder.total_interns == 0:
                result.warnings.append("No interns require feedback")
                result.delivery_success = True  # Not an error, just no-op
                self.logger.info("Feedback reminder skipped: no active interns")
                return result

            message = Message(
                content=result.formatted_content,
                title="Weekly Feedback Reminder",
                priority="normal",
                source_service="feedback",
                metadata={"total_interns": reminder.total_interns},
            )

            delivery = self._channel_manager.send(message, channel, destination)
            result.delivery_success = delivery.success
            result.delivery_error = delivery.error

            self.logger.info(
                f"Feedback reminder workflow: success={result.success}, "
                f"delivered={result.delivery_success}"
            )

        except Exception as e:
            self.logger.error(f"Feedback reminder workflow failed: {e}")
            result.warnings.append(str(e))

        return result

    def execute_all_scheduled(
        self,
        channel: "ChannelType",
        destination: str = None,
    ) -> dict[str, WorkflowResult]:
        """
        Execute all scheduled workflows.

        Convenience method for scheduled job execution.

        Args:
            channel: Target channel type
            destination: Override default destination

        Returns:
            Dictionary mapping workflow name to result
        """
        results = {}

        if self._report_service:
            results["weekly_report"] = self.execute_weekly_report(channel, destination)

        if self._hygiene_service:
            results["hygiene_check"] = self.execute_hygiene_check(channel, destination)

        if self._feedback_service:
            results["feedback_reminder"] = self.execute_feedback_reminder(channel, destination)

        success_count = sum(1 for r in results.values() if r.success and r.delivery_success)
        self.logger.info(
            f"Scheduled workflows complete: {success_count}/{len(results)} succeeded"
        )

        return results
