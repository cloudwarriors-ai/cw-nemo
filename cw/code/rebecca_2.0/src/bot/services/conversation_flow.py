"""
Conversation Flow Handler for multi-turn onboarding/offboarding workflows.

Uses SQLite for state persistence to support multi-worker deployments.
Provides step-by-step data collection with validation, cancel/back commands,
and confirmation before submission.
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..n8n_client import N8nClient
    from ...github_client import GitHubClient

from ..repositories import (
    ConversationFlowRepository,
    InternRepository,
    AuditRepository,
)
from .flow_validator import FlowValidatorService
from .bulk_parser import BulkSubmissionParser
from .flow_completion_handler import FlowCompletionHandler, CompletionResult


@dataclass
class FlowStep:
    """Definition of a conversation flow step."""
    field: str
    prompt: str
    validator: str
    required: bool = True
    options: list[str] = field(default_factory=list)


@dataclass
class FlowResponse:
    """Response from processing a conversation flow step."""
    message: str
    is_complete: bool = False
    data: Optional[dict] = None
    error: Optional[str] = None


class ConversationFlowHandler:
    """
    Handles multi-turn conversation flows for onboarding and offboarding.

    Features:
    - SQLite-backed state for multi-worker support
    - Step-by-step data collection with validation
    - Cancel/back commands
    - Duplicate detection
    - Confirmation before submission
    - GitHub username validation
    - Audit logging
    """

    # Flow timeout constants (minutes)
    ONBOARDING_TIMEOUT_MINUTES = 15
    OFFBOARDING_TIMEOUT_MINUTES = 10
    BULK_FLOW_TIMEOUT_MINUTES = 10

    # Note: Validation constants moved to FlowValidatorService
    # Note: Bulk submission thresholds moved to BulkSubmissionParser

    ONBOARDING_STEPS = [
        FlowStep(
            field="name",
            prompt="What's the intern's full name?",
            validator="name"
        ),
        FlowStep(
            field="email",
            prompt="What's their email address?",
            validator="email"
        ),
        FlowStep(
            field="github_username",
            prompt="What's their GitHub username?",
            validator="github"
        ),
        FlowStep(
            field="program",
            prompt="Which program? (skillbridge / vanderbilt / other)",
            validator="program",
            options=["skillbridge", "vanderbilt", "other"]
        ),
        FlowStep(
            field="start_date",
            prompt="When do they start? (YYYY-MM-DD)",
            validator="date"
        ),
        FlowStep(
            field="supervisor",
            prompt="Who is their supervisor?",
            validator="name"
        ),
        FlowStep(
            field="add_to_meetings",
            prompt="Add to Zoom meetings now or on start date? (now / later)",
            validator="meetings_timing",
            options=["now", "later"]
        ),
    ]

    OFFBOARDING_STEPS = [
        FlowStep(
            field="last_day",
            prompt="What is their last day? (YYYY-MM-DD or 'today')",
            validator="last_day"
        ),
        FlowStep(
            field="reason",
            prompt="Reason for leaving? (end of program / voluntary / other)",
            validator="offboard_reason",
            options=["end of program", "voluntary", "other"]
        ),
        FlowStep(
            field="remove_from_meetings",
            prompt="Remove from Zoom meetings now or keep until last day? (now / later)",
            validator="meetings_timing",
            options=["now", "later"]
        ),
    ]

    # Special step indices
    STEP_GITHUB_CONFIRM = -1  # GitHub validation confirmation
    STEP_FINAL_CONFIRM = -2  # Final confirmation before submit
    STEP_OFFBOARD_QUESTIONS = -3  # Offboarding additional questions

    CANCEL_KEYWORDS = {"cancel", "stop", "nevermind", "abort", "quit", "exit"}
    BACK_KEYWORDS = {"back", "previous", "go back", "undo"}
    CONFIRM_KEYWORDS = {"confirm", "yes", "y", "proceed", "submit"}
    REJECT_KEYWORDS = {"no", "n", "edit", "change", "wrong"}

    def __init__(
        self,
        db_path: str,
        n8n_client: Optional["N8nClient"] = None,
        github_client: Optional["GitHubClient"] = None,
        zoom_meetings_client: Optional[any] = None,
        meeting_ids: Optional[list[str]] = None,
        allowed_email_domains: Optional[list[str]] = None,
        logger: Optional[logging.Logger] = None,
        validator: Optional[FlowValidatorService] = None,
        parser: Optional[BulkSubmissionParser] = None
    ):
        """
        Initialize the conversation flow handler.

        Args:
            db_path: Path to SQLite database
            n8n_client: N8nClient for triggering workflows
            github_client: GitHubClient for username validation
            zoom_meetings_client: ZoomMeetingsClient for meeting registration
            meeting_ids: List of Zoom meeting IDs for recurring meetings
            allowed_email_domains: List of allowed email domains
            logger: Logger instance
            validator: FlowValidatorService for field validation
            parser: BulkSubmissionParser for parsing bulk submissions
        """
        self.db_path = db_path
        self.n8n_client = n8n_client
        self.github_client = github_client
        self.zoom_meetings_client = zoom_meetings_client
        self.meeting_ids = meeting_ids or []
        self.allowed_email_domains = allowed_email_domains or []
        self.logger = logger or logging.getLogger("qa_agent")

        # Initialize repositories
        self.flow_repo = ConversationFlowRepository(db_path=db_path, logger=self.logger)
        self.intern_repo = InternRepository(db_path=db_path, logger=self.logger)
        self.audit_repo = AuditRepository(db_path=db_path, logger=self.logger)

        # Initialize services (with defaults for backward compatibility)
        self.validator = validator or FlowValidatorService(
            allowed_email_domains=self.allowed_email_domains,
            logger=self.logger
        )
        self.parser = parser or BulkSubmissionParser(logger=self.logger)

        # Initialize completion handler
        self.completion_handler = FlowCompletionHandler(
            intern_repo=self.intern_repo,
            audit_repo=self.audit_repo,
            n8n_client=self.n8n_client,
            github_client=self.github_client,
            zoom_meetings_client=self.zoom_meetings_client,
            meeting_ids=self.meeting_ids,
            logger=self.logger
        )

    def is_in_flow(self, user_id: str) -> bool:
        """
        Check if user has an active conversation flow.

        Args:
            user_id: User ID to check

        Returns:
            True if user has an active (non-expired) flow
        """
        flow = self.flow_repo.get_active(user_id)
        return flow is not None

    def start_onboarding_flow(
        self,
        user_id: str,
        channel_id: str = None,
        actor_name: str = None
    ) -> FlowResponse:
        """
        Start a new onboarding flow.

        Args:
            user_id: User starting the flow
            channel_id: Channel where flow was started
            actor_name: Name of user starting flow (for audit)

        Returns:
            FlowResponse with first prompt
        """
        # Check for existing flow
        existing = self.flow_repo.get_active(user_id)
        if existing:
            # Offer to continue or cancel
            return FlowResponse(
                message=(
                    f"You have an active {existing['flow_type']} flow in progress. "
                    f"Type 'continue' to resume or 'cancel' to start fresh."
                )
            )

        # Create new flow
        flow_id = str(uuid.uuid4())[:8]
        self.flow_repo.create(
            flow_id=flow_id,
            user_id=user_id,
            flow_type="onboarding",
            channel_id=channel_id,
            expires_minutes=self.ONBOARDING_TIMEOUT_MINUTES
        )

        self.logger.info(f"Started onboarding flow {flow_id} for user {user_id}")

        # Return first prompt
        first_step = self.ONBOARDING_STEPS[0]
        return FlowResponse(
            message=f"Starting intern onboarding.\n\n{first_step.prompt}\n\n_(Type 'cancel' at any time to abort)_"
        )

    def start_offboarding_flow(
        self,
        user_id: str,
        intern_name: str,
        channel_id: str = None
    ) -> FlowResponse:
        """
        Start an offboarding flow for a specific intern.

        Args:
            user_id: User starting the flow
            intern_name: Name of intern to offboard
            channel_id: Channel where flow was started

        Returns:
            FlowResponse with confirmation prompt
        """
        # Look up intern
        matches = self.intern_repo.get_by_name(intern_name)

        if not matches:
            return FlowResponse(
                message=f"No intern found matching '{intern_name}'. Please check the name and try again.",
                error="intern_not_found"
            )

        if len(matches) > 1:
            names = "\n".join([f"- {m['name']} ({m.get('program', 'unknown program')})" for m in matches])
            return FlowResponse(
                message=f"Multiple interns match '{intern_name}':\n{names}\n\nPlease be more specific.",
                error="multiple_matches"
            )

        intern = matches[0]

        # Check status
        if intern.get("status") == "completed":
            return FlowResponse(
                message=f"{intern['name']} has already been offboarded.",
                error="already_offboarded"
            )

        # Create flow with intern data
        flow_id = str(uuid.uuid4())[:8]
        self.flow_repo.create(
            flow_id=flow_id,
            user_id=user_id,
            flow_type="offboarding",
            channel_id=channel_id,
            expires_minutes=self.OFFBOARDING_TIMEOUT_MINUTES
        )

        # Store intern data in collected_data, start at first offboarding question
        self.flow_repo.update(
            flow_id=flow_id,
            current_step=0,  # Start at first OFFBOARDING_STEPS
            collected_data={
                "intern_id": intern["id"],
                "name": intern["name"],
                "email": intern.get("email"),
                "github_username": intern.get("github_username"),
                "program": intern.get("program"),
                "supervisor": intern.get("supervisor"),
            }
        )

        self.logger.info(f"Started offboarding flow {flow_id} for intern {intern['name']}")

        # Show intern info and first question
        first_step = self.OFFBOARDING_STEPS[0]
        return FlowResponse(
            message=(
                f"**Offboarding: {intern['name']}**\n"
                f"- Program: {intern.get('program', 'N/A')}\n"
                f"- GitHub: {intern.get('github_username', 'N/A')}\n\n"
                f"{first_step.prompt}\n\n"
                f"_(Type 'cancel' to abort)_"
            )
        )

    def handle_response(
        self,
        user_id: str,
        text: str,
        actor_name: str = None
    ) -> FlowResponse:
        """
        Handle user response in an active flow.

        Args:
            user_id: User responding
            text: User's response text
            actor_name: Name of user (for audit)

        Returns:
            FlowResponse with next prompt or completion status
        """
        flow = self.flow_repo.get_active(user_id)
        if not flow:
            return FlowResponse(
                message="No active flow. Say 'onboard new intern' to start.",
                error="no_active_flow"
            )

        text_lower = text.lower().strip()

        # Handle cancel
        if text_lower in self.CANCEL_KEYWORDS:
            return self._cancel_flow(flow, user_id)

        # Handle back
        if text_lower in self.BACK_KEYWORDS:
            return self._go_back(flow)

        # Handle continue (for resuming existing flow)
        if text_lower == "continue":
            return self._get_current_prompt(flow)

        # Route based on flow type and step
        if flow["flow_type"] == "onboarding":
            return self._handle_onboarding_response(flow, text, actor_name)
        elif flow["flow_type"] == "offboarding":
            return self._handle_offboarding_response(flow, text, actor_name)

        return FlowResponse(
            message="Unknown flow type.",
            error="unknown_flow_type"
        )

    def _handle_onboarding_response(
        self,
        flow: dict,
        text: str,
        actor_name: str = None
    ) -> FlowResponse:
        """Handle response during onboarding flow."""
        step = flow["current_step"]
        collected = flow["collected_data"]
        text_lower = text.lower().strip()

        # GitHub confirmation step
        if step == self.STEP_GITHUB_CONFIRM:
            if text_lower in self.CONFIRM_KEYWORDS:
                # Move to next regular step
                github_step_idx = next(
                    i for i, s in enumerate(self.ONBOARDING_STEPS)
                    if s.field == "github_username"
                )
                next_step = github_step_idx + 1
                self.flow_repo.update(
                    flow["id"],
                    current_step=next_step,
                    collected_data=collected
                )
                if next_step < len(self.ONBOARDING_STEPS):
                    return FlowResponse(
                        message=self.ONBOARDING_STEPS[next_step].prompt
                    )
                else:
                    return self._show_final_confirmation(flow, collected)

            elif text_lower in self.REJECT_KEYWORDS:
                # Go back to github username step
                github_step_idx = next(
                    i for i, s in enumerate(self.ONBOARDING_STEPS)
                    if s.field == "github_username"
                )
                collected.pop("github_username", None)
                collected.pop("github_profile", None)
                self.flow_repo.update(
                    flow["id"],
                    current_step=github_step_idx,
                    collected_data=collected
                )
                return FlowResponse(
                    message=self.ONBOARDING_STEPS[github_step_idx].prompt
                )
            else:
                return FlowResponse(
                    message="Please reply 'yes' to confirm or 'no' to re-enter the GitHub username."
                )

        # Final confirmation step
        if step == self.STEP_FINAL_CONFIRM:
            if text_lower in self.CONFIRM_KEYWORDS:
                return self._complete_onboarding(flow, collected, actor_name)
            elif text_lower in self.REJECT_KEYWORDS or text_lower == "back":
                # Go back to last step
                last_step = len(self.ONBOARDING_STEPS) - 1
                self.flow_repo.update(
                    flow["id"],
                    current_step=last_step,
                    collected_data=collected
                )
                return FlowResponse(
                    message=f"Let's edit. {self.ONBOARDING_STEPS[last_step].prompt}"
                )
            else:
                return FlowResponse(
                    message="Please reply 'confirm' to proceed or 'back' to edit."
                )

        # Regular step processing
        if step < 0 or step >= len(self.ONBOARDING_STEPS):
            return FlowResponse(message="Invalid flow state.", error="invalid_step")

        current_step = self.ONBOARDING_STEPS[step]

        # Validate input
        validation = self._validate_field(current_step.validator, text, collected)
        if not validation["valid"]:
            return FlowResponse(
                message=f"{validation['error']}\n\n{current_step.prompt}"
            )

        # Store validated value
        collected[current_step.field] = validation["value"]

        # Special handling for certain fields
        if current_step.field == "name":
            # Check for duplicates
            duplicates = self.intern_repo.check_duplicate(
                name=validation["value"],
                email=""
            )
            if duplicates:
                dup_names = ", ".join([d["name"] for d in duplicates[:3]])
                return FlowResponse(
                    message=(
                        f"Found existing intern(s) with similar name: {dup_names}\n\n"
                        f"Is this a different person? Reply 'yes' to continue or 'cancel' to abort."
                    )
                )

        if current_step.field == "email":
            # Check for duplicate email
            duplicates = self.intern_repo.check_duplicate(
                name="",
                email=validation["value"]
            )
            if duplicates:
                return FlowResponse(
                    message=(
                        f"An intern with email {validation['value']} already exists: {duplicates[0]['name']}\n\n"
                        f"Type 'cancel' to abort or provide a different email."
                    )
                )

        if current_step.field == "github_username":
            # Validate GitHub user exists
            if self.github_client:
                github_info = self.github_client.validate_github_user(validation["value"])
                if not github_info.get("exists"):
                    return FlowResponse(
                        message=(
                            f"GitHub user '{validation['value']}' not found.\n\n"
                            f"Please check the username and try again."
                        )
                    )
                # Store profile info and ask for confirmation
                collected["github_profile"] = github_info
                self.flow_repo.update(
                    flow["id"],
                    current_step=self.STEP_GITHUB_CONFIRM,
                    collected_data=collected
                )
                return FlowResponse(
                    message=(
                        f"Found GitHub user: **{github_info['login']}** ({github_info.get('name', 'No display name')})\n"
                        f"Profile: {github_info.get('profile_url', 'N/A')}\n\n"
                        f"Is this correct? (yes/no)"
                    )
                )

        # Move to next step
        next_step = step + 1
        self.flow_repo.update(
            flow["id"],
            current_step=next_step,
            collected_data=collected
        )

        # Check if all steps complete
        if next_step >= len(self.ONBOARDING_STEPS):
            return self._show_final_confirmation(flow, collected)

        # Return next prompt
        return FlowResponse(
            message=self.ONBOARDING_STEPS[next_step].prompt
        )

    def _handle_offboarding_response(
        self,
        flow: dict,
        text: str,
        actor_name: str = None
    ) -> FlowResponse:
        """Handle response during offboarding flow."""
        step = flow["current_step"]
        collected = flow["collected_data"]
        text_lower = text.lower().strip()

        # Final confirmation step
        if step == self.STEP_FINAL_CONFIRM:
            if text_lower in self.CONFIRM_KEYWORDS or text_lower == "confirm offboard":
                return self._complete_offboarding(flow, collected, actor_name)
            elif text_lower in self.REJECT_KEYWORDS or text_lower == "back":
                # Go back to last offboarding step
                last_step = len(self.OFFBOARDING_STEPS) - 1
                last_field = self.OFFBOARDING_STEPS[last_step].field
                collected.pop(last_field, None)
                self.flow_repo.update(
                    flow["id"],
                    current_step=last_step,
                    collected_data=collected
                )
                return FlowResponse(
                    message=f"Let's edit. {self.OFFBOARDING_STEPS[last_step].prompt}"
                )
            else:
                return FlowResponse(
                    message="Please reply 'confirm' to proceed or 'back' to edit."
                )

        # Regular offboarding step processing
        if step < 0 or step >= len(self.OFFBOARDING_STEPS):
            return FlowResponse(message="Invalid flow state.", error="invalid_step")

        current_step = self.OFFBOARDING_STEPS[step]

        # Validate input
        validation = self._validate_field(current_step.validator, text, collected)
        if not validation["valid"]:
            return FlowResponse(
                message=f"{validation['error']}\n\n{current_step.prompt}"
            )

        # Store validated value
        collected[current_step.field] = validation["value"]

        # Move to next step
        next_step = step + 1
        self.flow_repo.update(
            flow["id"],
            current_step=next_step,
            collected_data=collected
        )

        # Check if all offboarding steps complete
        if next_step >= len(self.OFFBOARDING_STEPS):
            return self._show_offboarding_confirmation(flow, collected)

        # Return next prompt
        return FlowResponse(
            message=self.OFFBOARDING_STEPS[next_step].prompt
        )

    def _validate_field(self, validator: str, value: str, collected: dict) -> dict:
        """
        Validate a field value.

        Delegates to FlowValidatorService for actual validation logic.

        Args:
            validator: Validator type
            value: Value to validate
            collected: Currently collected data (for context)

        Returns:
            Dict with valid flag, cleaned value, and error if invalid
        """
        return self.validator.validate_field(validator, value, collected)

    def _show_final_confirmation(self, flow: dict, collected: dict) -> FlowResponse:
        """Show final confirmation before submitting."""
        self.flow_repo.update(
            flow["id"],
            current_step=self.STEP_FINAL_CONFIRM,
            collected_data=collected
        )

        github_info = collected.get("github_profile", {})
        meetings_timing = collected.get("add_to_meetings", "later")
        meetings_display = "Now (immediately)" if meetings_timing == "now" else "On start date"

        message = (
            "**Please confirm onboarding details:**\n\n"
            f"- **Name:** {collected.get('name', 'N/A')}\n"
            f"- **Email:** {collected.get('email', 'N/A')}\n"
            f"- **GitHub:** {collected.get('github_username', 'N/A')}"
        )
        if github_info.get("name"):
            message += f" ({github_info['name']})"
        message += (
            f"\n- **Program:** {collected.get('program', 'N/A')}\n"
            f"- **Start Date:** {collected.get('start_date', 'N/A')}\n"
            f"- **Supervisor:** {collected.get('supervisor', 'N/A')}\n"
            f"- **Add to Meetings:** {meetings_display}\n\n"
            "_Reply 'confirm' to proceed or 'back' to edit._"
        )

        return FlowResponse(message=message)

    def _show_offboarding_confirmation(self, flow: dict, collected: dict) -> FlowResponse:
        """Show final confirmation before offboarding."""
        self.flow_repo.update(
            flow["id"],
            current_step=self.STEP_FINAL_CONFIRM,
            collected_data=collected
        )

        # Format reason for display
        reason_display = {
            "end_of_program": "End of program",
            "voluntary": "Voluntary departure",
            "other": "Other",
        }.get(collected.get("reason", ""), collected.get("reason", "N/A"))

        # Format meetings removal
        meetings_display = "Now (immediately)" if collected.get("remove_from_meetings") == "now" else "On last day"

        message = (
            f"**Confirm offboarding for {collected.get('name', 'N/A')}:**\n\n"
            f"- **Last Day:** {collected.get('last_day', 'N/A')}\n"
            f"- **Reason:** {reason_display}\n"
            f"- **Remove from Meetings:** {meetings_display}\n\n"
            "**This will:**\n"
            "- Send farewell email with exit survey\n"
            f"- Remove {collected.get('github_username', 'user')} from GitHub org\n"
        )
        if collected.get("remove_from_meetings") == "now":
            message += "- Remove from Zoom meetings now\n"
        else:
            message += "- Keep in Zoom meetings until last day\n"

        message += "\n_Reply 'confirm' to proceed or 'back' to edit._"

        return FlowResponse(message=message)

    def _complete_onboarding(
        self,
        flow: dict,
        collected: dict,
        actor_name: str = None
    ) -> FlowResponse:
        """Complete the onboarding flow. Delegates to FlowCompletionHandler."""
        result = self.completion_handler.complete_onboarding(flow, collected, actor_name)

        # Clean up flow
        self.flow_repo.delete(flow["id"])

        return FlowResponse(
            message=result.message,
            is_complete=result.success,
            data={"intern_id": result.intern_id, "name": result.intern_name} if result.success else None,
            error=result.error
        )

    def _complete_offboarding(
        self,
        flow: dict,
        collected: dict,
        actor_name: str = None
    ) -> FlowResponse:
        """Complete the offboarding flow. Delegates to FlowCompletionHandler."""
        result = self.completion_handler.complete_offboarding(flow, collected, actor_name)

        # Clean up flow
        self.flow_repo.delete(flow["id"])

        return FlowResponse(
            message=result.message,
            is_complete=result.success,
            data={"intern_id": result.intern_id, "name": result.intern_name} if result.success else None,
            error=result.error
        )

    def _cancel_flow(self, flow: dict, user_id: str) -> FlowResponse:
        """Cancel an active flow."""
        self.flow_repo.delete(flow["id"])
        self.logger.info(f"Cancelled {flow['flow_type']} flow for user {user_id}")
        return FlowResponse(
            message=f"{flow['flow_type'].title()} cancelled.",
            is_complete=True
        )

    def _go_back(self, flow: dict) -> FlowResponse:
        """Go back to previous step."""
        step = flow["current_step"]
        collected = flow["collected_data"]

        # Can't go back from first step
        if step <= 0 and step != self.STEP_GITHUB_CONFIRM and step != self.STEP_FINAL_CONFIRM:
            return FlowResponse(
                message="You're at the first step. Type 'cancel' to abort."
            )

        # Handle special steps
        if step == self.STEP_GITHUB_CONFIRM:
            # Go back to github username step
            github_step_idx = next(
                i for i, s in enumerate(self.ONBOARDING_STEPS)
                if s.field == "github_username"
            )
            collected.pop("github_username", None)
            collected.pop("github_profile", None)
            self.flow_repo.update(
                flow["id"],
                current_step=github_step_idx,
                collected_data=collected
            )
            return FlowResponse(
                message=self.ONBOARDING_STEPS[github_step_idx].prompt
            )

        if step == self.STEP_FINAL_CONFIRM:
            # Go back to last regular step
            last_step = len(self.ONBOARDING_STEPS) - 1
            # Remove last collected field
            last_field = self.ONBOARDING_STEPS[last_step].field
            collected.pop(last_field, None)
            self.flow_repo.update(
                flow["id"],
                current_step=last_step,
                collected_data=collected
            )
            return FlowResponse(
                message=self.ONBOARDING_STEPS[last_step].prompt
            )

        # Regular step - go back one
        prev_step = step - 1
        prev_field = self.ONBOARDING_STEPS[prev_step].field
        collected.pop(prev_field, None)
        self.flow_repo.update(
            flow["id"],
            current_step=prev_step,
            collected_data=collected
        )
        return FlowResponse(
            message=self.ONBOARDING_STEPS[prev_step].prompt
        )

    def _get_current_prompt(self, flow: dict) -> FlowResponse:
        """Get prompt for current step (for resuming)."""
        step = flow["current_step"]
        collected = flow["collected_data"]

        if step == self.STEP_GITHUB_CONFIRM:
            github_info = collected.get("github_profile", {})
            return FlowResponse(
                message=(
                    f"Resuming onboarding...\n\n"
                    f"Found GitHub user: **{collected.get('github_username')}** ({github_info.get('name', 'N/A')})\n"
                    f"Is this correct? (yes/no)"
                )
            )

        if step == self.STEP_FINAL_CONFIRM:
            return self._show_final_confirmation(flow, collected)

        if 0 <= step < len(self.ONBOARDING_STEPS):
            current = self.ONBOARDING_STEPS[step]
            return FlowResponse(
                message=f"Resuming onboarding...\n\n{current.prompt}"
            )

        return FlowResponse(message="Flow state error.", error="invalid_state")

    @staticmethod
    def get_intern_form_template() -> str:
        """
        Generate an intern onboarding form template.

        Delegates to BulkSubmissionParser.

        Returns:
            Formatted template string for bulk submission
        """
        return BulkSubmissionParser.get_intern_form_template()

    @staticmethod
    def get_offboard_form_template() -> str:
        """
        Generate an intern offboarding form template.

        Delegates to BulkSubmissionParser.

        Returns:
            Formatted template string for bulk submission
        """
        return BulkSubmissionParser.get_offboard_form_template()

    def parse_bulk_submission(self, text: str) -> Optional[dict]:
        """
        Parse a bulk onboarding submission.

        Delegates to BulkSubmissionParser.

        Args:
            text: Message text to parse

        Returns:
            Dict of parsed fields, or None if not a bulk submission
        """
        return self.parser.parse_bulk_submission(text)

    def parse_bulk_offboarding(self, text: str) -> Optional[dict]:
        """
        Parse a bulk offboarding submission.

        Delegates to BulkSubmissionParser.

        Args:
            text: Message text to parse

        Returns:
            Dict of parsed fields, or None if not a bulk offboarding submission
        """
        return self.parser.parse_bulk_offboarding(text)

    def start_offboarding_bulk(
        self,
        user_id: str,
        bulk_data: dict,
        channel_id: str = None,
        actor_name: str = None
    ) -> FlowResponse:
        """
        Start offboarding with bulk data pre-filled.

        Looks up intern by name, validates fields, goes to confirmation.

        Args:
            user_id: User starting the flow
            bulk_data: Dict with pre-filled fields
            channel_id: Channel where flow was started
            actor_name: Name of user (for audit)

        Returns:
            FlowResponse with validation errors or confirmation prompt
        """
        intern_name = bulk_data.get("name", "").strip()
        if not intern_name:
            return FlowResponse(
                message="Could not find intern name in the form.",
                error="no_name"
            )

        # Look up intern
        matches = self.intern_repo.get_by_name(intern_name)

        if not matches:
            return FlowResponse(
                message=f"No intern found matching '{intern_name}'. Please check the name and try again.",
                error="intern_not_found"
            )

        if len(matches) > 1:
            names = "\n".join([f"- {m['name']} ({m.get('program', 'unknown')})" for m in matches])
            return FlowResponse(
                message=f"Multiple interns match '{intern_name}':\n{names}\n\nPlease use 'offboard [exact name]' instead.",
                error="multiple_matches"
            )

        intern = matches[0]

        if intern.get("status") == "completed":
            return FlowResponse(
                message=f"{intern['name']} has already been offboarded.",
                error="already_offboarded"
            )

        # Validate provided fields
        collected = {
            "intern_id": intern["id"],
            "name": intern["name"],
            "email": intern.get("email"),
            "github_username": intern.get("github_username"),
            "program": intern.get("program"),
            "supervisor": intern.get("supervisor"),
        }
        errors = []

        for step in self.OFFBOARDING_STEPS:
            field = step.field
            value = bulk_data.get(field, "").strip()

            if value:
                validation = self._validate_field(step.validator, value, collected)
                if validation["valid"]:
                    collected[field] = validation["value"]
                else:
                    errors.append(f"- **{field.replace('_', ' ').title()}**: {validation['error']}")

        if errors:
            error_list = "\n".join(errors)
            return FlowResponse(
                message=f"**Validation errors:**\n\n{error_list}\n\nFix and resubmit, or use 'offboard {intern_name}' for step-by-step.",
                error="validation_errors"
            )

        # Check which fields are missing
        missing_fields = [s.field for s in self.OFFBOARDING_STEPS if s.field not in collected]

        if missing_fields:
            # Create flow and continue from first missing field
            flow_id = str(uuid.uuid4())[:8]
            self.flow_repo.create(
                flow_id=flow_id,
                user_id=user_id,
                flow_type="offboarding",
                channel_id=channel_id,
                expires_minutes=self.OFFBOARDING_TIMEOUT_MINUTES
            )

            first_missing_idx = next(
                i for i, s in enumerate(self.OFFBOARDING_STEPS)
                if s.field not in collected
            )

            self.flow_repo.update(
                flow_id=flow_id,
                current_step=first_missing_idx,
                collected_data=collected
            )

            self.logger.info(f"Started partial offboarding flow {flow_id} for {intern['name']}")

            filled = [f"- {k.replace('_', ' ').title()}: {v}" for k, v in collected.items()
                     if k in [s.field for s in self.OFFBOARDING_STEPS]]
            filled_list = "\n".join(filled) if filled else "(none yet)"
            next_prompt = self.OFFBOARDING_STEPS[first_missing_idx].prompt

            return FlowResponse(
                message=(
                    f"**Offboarding: {intern['name']}**\n\n"
                    f"Got it! I have:\n{filled_list}\n\n"
                    f"{next_prompt}\n\n"
                    f"_(Type 'cancel' to abort)_"
                )
            )

        # All fields present - go to confirmation
        flow_id = str(uuid.uuid4())[:8]
        self.flow_repo.create(
            flow_id=flow_id,
            user_id=user_id,
            flow_type="offboarding",
            channel_id=channel_id,
            expires_minutes=self.OFFBOARDING_TIMEOUT_MINUTES
        )

        self.flow_repo.update(
            flow_id=flow_id,
            current_step=self.STEP_FINAL_CONFIRM,
            collected_data=collected
        )

        self.logger.info(f"Started bulk offboarding flow {flow_id} for {intern['name']}")

        return self._show_offboarding_confirmation({"id": flow_id}, collected)

    def start_onboarding_bulk(
        self,
        user_id: str,
        bulk_data: dict,
        channel_id: str = None,
        actor_name: str = None
    ) -> FlowResponse:
        """
        Start onboarding with bulk data pre-filled.

        Validates all fields and goes directly to confirmation if valid.

        Args:
            user_id: User starting the flow
            bulk_data: Dict with pre-filled fields
            channel_id: Channel where flow was started
            actor_name: Name of user (for audit)

        Returns:
            FlowResponse with validation errors or confirmation prompt
        """
        # Check for existing flow
        existing = self.flow_repo.get_active(user_id)
        if existing:
            self.flow_repo.delete(existing["id"])

        # Validate all fields
        collected = {}
        errors = []
        missing_fields = []

        for step in self.ONBOARDING_STEPS:
            field = step.field
            value = bulk_data.get(field, "").strip()

            if not value and step.required:
                missing_fields.append(field.replace('_', ' ').title())
                continue

            if value:
                validation = self._validate_field(step.validator, value, collected)
                if validation["valid"]:
                    collected[field] = validation["value"]
                else:
                    errors.append(f"- **{field.replace('_', ' ').title()}**: {validation['error']}")

        # If there are validation errors, return them with helpful message
        if errors:
            error_list = "\n".join(errors)
            return FlowResponse(
                message=(
                    f"**Validation errors:**\n\n{error_list}\n\n"
                    f"Please fix and resubmit, or type 'onboard intern' for step-by-step."
                ),
                error="validation_errors"
            )

        # If fields are missing, offer to continue step-by-step with what we have
        if missing_fields:
            missing_list = ", ".join(missing_fields)
            filled_count = len(collected)

            if filled_count == 0:
                return FlowResponse(
                    message=(
                        f"**Could not parse form data.**\n\n"
                        f"Type 'intern form' to get a blank template, or 'onboard intern' for step-by-step."
                    ),
                    error="no_data"
                )

            # Create flow and pre-fill what we have, then continue from first missing field
            flow_id = str(uuid.uuid4())[:8]
            self.flow_repo.create(
                flow_id=flow_id,
                user_id=user_id,
                flow_type="onboarding",
                channel_id=channel_id,
                expires_minutes=15
            )

            # Find first missing required field
            first_missing_step = 0
            for i, step in enumerate(self.ONBOARDING_STEPS):
                if step.field not in collected:
                    first_missing_step = i
                    break

            self.flow_repo.update(
                flow_id=flow_id,
                current_step=first_missing_step,
                collected_data=collected
            )

            self.logger.info(f"Started partial onboarding flow {flow_id} - missing: {missing_list}")

            filled_list = "\n".join([f"- {k.replace('_', ' ').title()}: {v}" for k, v in collected.items()])
            next_prompt = self.ONBOARDING_STEPS[first_missing_step].prompt

            return FlowResponse(
                message=(
                    f"**Got it!** I have:\n{filled_list}\n\n"
                    f"**Missing:** {missing_list}\n\n"
                    f"{next_prompt}\n\n"
                    f"_(Type 'cancel' to abort or fill in remaining fields)_"
                )
            )

        # Check for duplicates
        duplicates = self.intern_repo.check_duplicate(
            name=collected.get("name", ""),
            email=collected.get("email", "")
        )
        if duplicates:
            dup_info = duplicates[0]
            return FlowResponse(
                message=(
                    f"**Possible duplicate found:**\n"
                    f"- {dup_info['name']} ({dup_info.get('email', 'N/A')})\n\n"
                    f"Type 'onboard intern' for step-by-step to confirm this is a different person."
                ),
                error="duplicate_found"
            )

        # Validate GitHub username
        if self.github_client and collected.get("github_username"):
            github_info = self.github_client.validate_github_user(collected["github_username"])
            if not github_info.get("exists"):
                return FlowResponse(
                    message=(
                        f"**GitHub user '{collected['github_username']}' not found.**\n\n"
                        f"Please check the username and resubmit."
                    ),
                    error="github_not_found"
                )
            collected["github_profile"] = github_info

        # Create flow and go directly to confirmation
        flow_id = str(uuid.uuid4())[:8]
        self.flow_repo.create(
            flow_id=flow_id,
            user_id=user_id,
            flow_type="onboarding",
            channel_id=channel_id,
            expires_minutes=self.OFFBOARDING_TIMEOUT_MINUTES
        )

        self.flow_repo.update(
            flow_id=flow_id,
            current_step=self.STEP_FINAL_CONFIRM,
            collected_data=collected
        )

        self.logger.info(f"Started bulk onboarding flow {flow_id} for user {user_id}")

        # Show confirmation
        flow = {"id": flow_id, "user_id": user_id}
        return self._show_final_confirmation(flow, collected)
