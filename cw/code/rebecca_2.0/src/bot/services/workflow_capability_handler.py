"""
Workflow capability handlers for QueryService.

Handles onboarding, offboarding, intern status, meeting join,
and weekly report capabilities.
"""

import logging
from typing import Optional, Any

from ..channels import ChannelType


class WorkflowCapabilityHandler:
    """
    Handles workflow-related capabilities.

    Responsible for:
    - Onboarding flows (single and bulk)
    - Offboarding flows (single and bulk)
    - Intern status queries
    - Meeting join requests
    - Weekly reports
    """

    def __init__(
        self,
        workflow_orchestrator: Optional[Any] = None,
        n8n_client: Optional[Any] = None,
        meeting_handler: Optional[Any] = None,
        conversation_flow_handler: Optional[Any] = None,
        auth_service: Optional[Any] = None,
        intern_repo: Optional[Any] = None,
        logger: Optional[logging.Logger] = None
    ):
        self.workflow_orchestrator = workflow_orchestrator
        self.n8n_client = n8n_client
        self.meeting_handler = meeting_handler
        self.conversation_flow_handler = conversation_flow_handler
        self.auth_service = auth_service
        self.intern_repo = intern_repo
        self.logger = logger or logging.getLogger(__name__)

    def check_intern_management_auth(
        self,
        user_id: str,
        user_email: str,
        request_id: str,
        action: str = "manage interns"
    ) -> Optional[str]:
        """
        Check if user is authorized for intern management.

        Returns:
            Error message if unauthorized, None if authorized
        """
        if self.auth_service and not self.auth_service.can_manage_interns(user_id, user_email):
            self.logger.info(f"[{request_id}] User {user_id} not authorized for {action}")
            return (
                f"Sorry, you're not authorized to {action}. "
                "Contact an admin if you need access."
            )
        return None

    def handle_weekly_report(self, channel_id: str, request_id: str) -> str:
        """Handle weekly report request."""
        if not self.workflow_orchestrator:
            return "Weekly reports aren't configured. Ask an admin to set up the workflow orchestrator."

        if not channel_id:
            return "I can't determine which channel to post the report to. Please try again from a channel."

        try:
            result = self.workflow_orchestrator.execute_weekly_report(
                channel=ChannelType.ZOOM,
                destination=channel_id,
                force_refresh=False,
            )

            if result.success and result.delivery_success:
                return "Weekly report posted to this channel."
            elif result.success and not result.delivery_success:
                content = result.formatted_content or "No data available"
                return f"Here's the weekly report:\n\n{content[:1500]}"
            else:
                warnings = ", ".join(result.warnings) if result.warnings else "Unknown error"
                return f"I couldn't generate the weekly report right now. Issue: {warnings}"
        except Exception as e:
            self.logger.error(f"[{request_id}] Weekly report error: {e}", exc_info=True)
            return "Something went wrong generating the report. Please try again later."

    def handle_onboarding(
        self,
        filters: dict,
        user_id: str,
        user_name: str,
        channel_id: str,
        request_id: str,
        user_email: str = ""
    ) -> str:
        """Handle onboarding request with multi-turn conversation flow."""
        auth_error = self.check_intern_management_auth(
            user_id, user_email, request_id, "manage intern onboarding"
        )
        if auth_error:
            return auth_error

        if self.conversation_flow_handler:
            self.logger.info(f"[{request_id}] Starting onboarding flow for user {user_id}")
            result = self.conversation_flow_handler.start_onboarding_flow(
                user_id=user_id,
                channel_id=channel_id,
                actor_name=user_name
            )
            return result.message

        # Fallback: Legacy single-shot workflow
        person_name = filters.get("person_name") if filters else None

        if not person_name:
            return "I need a name to start onboarding. Try: 'onboard Alice' or 'start onboarding for Bob'"

        if not self.n8n_client:
            return f"Workflow system isn't configured. I noted that {person_name} needs onboarding - please set this up manually or contact an admin."

        try:
            result = self.n8n_client.trigger_onboarding(
                intern_name=person_name,
                supervisor=user_name
            )
            if result.get("status") in ("triggered", "completed"):
                return f"Started onboarding workflow for {person_name}. I'll update you on progress."
            else:
                return f"I noted that {person_name} needs onboarding, but the workflow didn't start. Please follow up manually."
        except Exception as e:
            self.logger.error(f"[{request_id}] Onboarding error: {e}", exc_info=True)
            return f"I couldn't start the onboarding workflow for {person_name}. Please try again or do it manually."

    def handle_bulk_onboarding(
        self,
        text: str,
        user_id: str,
        user_name: str,
        channel_id: str,
        request_id: str,
        user_email: str = ""
    ) -> str:
        """Handle bulk onboarding submission."""
        auth_error = self.check_intern_management_auth(
            user_id, user_email, request_id, "manage intern onboarding"
        )
        if auth_error:
            return auth_error

        if not self.conversation_flow_handler:
            return "Onboarding system not configured."

        bulk_data = self.conversation_flow_handler.parse_bulk_submission(text)
        if not bulk_data:
            return "Could not parse the form. Please ensure all fields are filled in correctly."

        self.logger.info(f"[{request_id}] Processing bulk onboarding for user {user_id}")
        result = self.conversation_flow_handler.start_onboarding_bulk(
            user_id=user_id,
            bulk_data=bulk_data,
            channel_id=channel_id,
            actor_name=user_name
        )
        return result.message

    def handle_offboarding(
        self,
        filters: dict,
        user_id: str,
        user_name: str,
        channel_id: str,
        request_id: str,
        user_email: str = ""
    ) -> str:
        """Handle offboarding request with confirmation flow."""
        auth_error = self.check_intern_management_auth(
            user_id, user_email, request_id, "manage intern offboarding"
        )
        if auth_error:
            return auth_error

        person_name = filters.get("person_name") if filters else None

        if not person_name:
            return "I need a name to start offboarding. Try: 'offboard Alice' or 'Bob is leaving'"

        if self.conversation_flow_handler:
            self.logger.info(f"[{request_id}] Starting offboarding flow for {person_name}")
            result = self.conversation_flow_handler.start_offboarding_flow(
                user_id=user_id,
                intern_name=person_name,
                channel_id=channel_id
            )
            return result.message

        # Fallback: Legacy single-shot workflow
        if not self.n8n_client:
            return f"Workflow system isn't configured. I noted that {person_name} needs offboarding - please handle this manually or contact an admin."

        try:
            result = self.n8n_client.trigger_offboarding(
                intern_name=person_name,
            )
            if result.get("status") in ("triggered", "completed"):
                return f"Started offboarding workflow for {person_name}. I'll handle access removal and documentation."
            else:
                return f"I noted that {person_name} needs offboarding, but the workflow didn't start. Please follow up manually."
        except Exception as e:
            self.logger.error(f"[{request_id}] Offboarding error: {e}", exc_info=True)
            return f"I couldn't start the offboarding workflow for {person_name}. Please try again or handle manually."

    def handle_bulk_offboarding(
        self,
        text: str,
        user_id: str,
        user_name: str,
        channel_id: str,
        request_id: str,
        user_email: str = ""
    ) -> str:
        """Handle bulk offboarding submission."""
        auth_error = self.check_intern_management_auth(
            user_id, user_email, request_id, "manage intern offboarding"
        )
        if auth_error:
            return auth_error

        if not self.conversation_flow_handler:
            return "Offboarding system not configured."

        bulk_data = self.conversation_flow_handler.parse_bulk_offboarding(text)
        if not bulk_data:
            return "Could not parse the offboarding form. Please ensure all fields are filled in correctly."

        self.logger.info(f"[{request_id}] Processing bulk offboarding for user {user_id}")
        result = self.conversation_flow_handler.start_offboarding_bulk(
            user_id=user_id,
            bulk_data=bulk_data,
            channel_id=channel_id,
            actor_name=user_name
        )
        return result.message

    def handle_intern_status(self, filters: dict, request_id: str) -> str:
        """Handle intern status request."""
        person_name = filters.get("person_name") if filters else None

        try:
            if person_name:
                interns = self.intern_repo.get_by_name(person_name) if self.intern_repo else []
                if interns:
                    intern = interns[0]
                    status = intern.get("status", "unknown")
                    supervisor = intern.get("supervisor", "unassigned")
                    start_date = intern.get("start_date", "unknown")
                    name = intern.get("name", person_name)
                    return f"**{name}**\nStatus: {status}\nSupervisor: {supervisor}\nStarted: {start_date}"
                else:
                    return f"I don't have any records for '{person_name}'. They might not be registered as an intern."
            else:
                interns = self.intern_repo.get_all() if self.intern_repo else []
                if not interns:
                    return "No active interns found in the system."

                lines = [f"**Active Interns ({len(interns)})**"]
                for intern in interns[:10]:
                    name = intern.get("name", "Unknown")
                    status = intern.get("status", "unknown")
                    lines.append(f"- {name}: {status}")

                if len(interns) > 10:
                    lines.append(f"... and {len(interns) - 10} more")

                return "\n".join(lines)
        except Exception as e:
            self.logger.error(f"[{request_id}] Intern status error: {e}", exc_info=True)
            return "I couldn't retrieve intern status right now. Please try again later."

    def handle_meeting_join(self, filters: dict, user_name: str, request_id: str) -> str:
        """Handle meeting join request."""
        meeting_name = filters.get("meeting_name") if filters else None

        if not self.meeting_handler:
            return "Meeting integration isn't configured. I can't join meetings right now."

        return f"Sure, I can join {meeting_name or 'the meeting'}! Just paste the meeting URL (Zoom, Teams, or Google Meet) and I'll hop in."

    @staticmethod
    def get_intern_form_template() -> str:
        """Return the intern onboarding form template."""
        from .conversation_flow import ConversationFlowHandler
        return ConversationFlowHandler.get_intern_form_template()

    @staticmethod
    def get_offboard_form_template() -> str:
        """Return the intern offboarding form template."""
        from .conversation_flow import ConversationFlowHandler
        return ConversationFlowHandler.get_offboard_form_template()
