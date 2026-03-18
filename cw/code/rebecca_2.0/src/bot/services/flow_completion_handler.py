"""
Flow Completion Handler for onboarding/offboarding workflows.

Handles the actual completion of flows including:
- Database record creation/updates
- Audit logging
- n8n workflow triggering
- GitHub org management
- Zoom meeting registration
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from ..n8n_client import N8nClient
    from ...github_client import GitHubClient

from ..repositories import InternRepository, AuditRepository


@dataclass
class CompletionResult:
    """Result of a flow completion operation."""
    success: bool
    message: str
    intern_id: Optional[str] = None
    intern_name: Optional[str] = None
    error: Optional[str] = None


class FlowCompletionHandler:
    """
    Handles completion of onboarding and offboarding flows.

    Responsible for:
    - Creating/updating intern database records
    - Logging audit events
    - Triggering n8n workflows
    - Managing GitHub org membership
    - Managing Zoom meeting registrations
    """

    def __init__(
        self,
        intern_repo: InternRepository,
        audit_repo: AuditRepository,
        n8n_client: Optional["N8nClient"] = None,
        github_client: Optional["GitHubClient"] = None,
        zoom_meetings_client: Optional[any] = None,
        meeting_ids: Optional[list[str]] = None,
        logger: Optional[logging.Logger] = None
    ):
        self.intern_repo = intern_repo
        self.audit_repo = audit_repo
        self.n8n_client = n8n_client
        self.github_client = github_client
        self.zoom_meetings_client = zoom_meetings_client
        self.meeting_ids = meeting_ids or []
        self.logger = logger or logging.getLogger("qa_agent")

    def complete_onboarding(
        self,
        flow: dict,
        collected: dict,
        actor_name: str = None
    ) -> CompletionResult:
        """
        Complete the onboarding flow.

        Args:
            flow: Flow record with user_id, etc.
            collected: Collected data from flow steps
            actor_name: Name of user completing the flow

        Returns:
            CompletionResult with success status and message
        """
        try:
            # Generate intern ID
            intern_id = str(uuid.uuid4())[:8]

            # Create intern record
            success = self.intern_repo.create(
                intern_id=intern_id,
                name=collected["name"],
                email=collected.get("email"),
                program=collected.get("program", "other"),
                supervisor=collected.get("supervisor"),
                start_date=collected.get("start_date"),
            )

            if not success:
                return CompletionResult(
                    success=False,
                    message="Failed to create intern record. Please try again.",
                    error="database_error"
                )

            # Log audit event
            self.audit_repo.log_event(
                action="onboard",
                actor_user_id=flow["user_id"],
                target_id=intern_id,
                target_name=collected["name"],
                actor_name=actor_name,
                details=json.dumps(collected)
            )

            # Execute external integrations
            n8n_result = self._trigger_onboarding_workflow(collected)
            github_result = self._invite_to_github(collected)
            meetings_result = self._add_to_meetings(collected)

            # Build success message
            message = self._build_onboarding_message(
                collected, n8n_result, github_result, meetings_result
            )

            return CompletionResult(
                success=True,
                message=message,
                intern_id=intern_id,
                intern_name=collected["name"]
            )

        except Exception as e:
            self.logger.error(f"Onboarding completion failed: {e}")
            return CompletionResult(
                success=False,
                message=f"Onboarding failed: {e}",
                error=str(e)
            )

    def complete_offboarding(
        self,
        flow: dict,
        collected: dict,
        actor_name: str = None
    ) -> CompletionResult:
        """
        Complete the offboarding flow.

        Args:
            flow: Flow record with user_id, etc.
            collected: Collected data from flow steps
            actor_name: Name of user completing the flow

        Returns:
            CompletionResult with success status and message
        """
        try:
            intern_id = collected.get("intern_id")
            intern_name = collected.get("name")

            # Update intern status
            self.intern_repo.update_status(
                intern_id=intern_id,
                status="completed",
                notes=f"Offboarded on {datetime.now().strftime('%Y-%m-%d')}"
            )

            # Log audit event
            self.audit_repo.log_event(
                action="offboard",
                actor_user_id=flow["user_id"],
                target_id=intern_id,
                target_name=intern_name,
                actor_name=actor_name,
                details=json.dumps(collected)
            )

            # Execute external integrations
            n8n_result = self._trigger_offboarding_workflow(collected, intern_name)
            github_result = self._remove_from_github(collected)
            meetings_result = self._remove_from_meetings(collected, intern_name)

            # Build success message
            message = self._build_offboarding_message(
                intern_name, collected, n8n_result, github_result, meetings_result
            )

            return CompletionResult(
                success=True,
                message=message,
                intern_id=intern_id,
                intern_name=intern_name
            )

        except Exception as e:
            self.logger.error(f"Offboarding completion failed: {e}")
            return CompletionResult(
                success=False,
                message=f"Offboarding failed: {e}",
                error=str(e)
            )

    def _trigger_onboarding_workflow(self, collected: dict) -> Optional[dict]:
        """Trigger n8n onboarding workflow."""
        if not self.n8n_client:
            return None

        try:
            result = self.n8n_client.trigger_onboarding(
                intern_name=collected["name"],
                intern_email=collected.get("email"),
                github_username=collected.get("github_username"),
                program=collected.get("program"),
                start_date=collected.get("start_date"),
                supervisor=collected.get("supervisor"),
            )
            self.logger.info(f"Triggered onboarding workflow for {collected['name']}")
            return result
        except Exception as e:
            self.logger.error(f"Failed to trigger onboarding workflow: {e}")
            return None

    def _trigger_offboarding_workflow(
        self, collected: dict, intern_name: str
    ) -> Optional[dict]:
        """Trigger n8n offboarding workflow."""
        if not self.n8n_client:
            return None

        try:
            result = self.n8n_client.trigger_offboarding(
                intern_name=intern_name,
                intern_email=collected.get("email"),
                github_username=collected.get("github_username"),
            )
            self.logger.info(f"Triggered offboarding workflow for {intern_name}")
            return result
        except Exception as e:
            self.logger.error(f"Failed to trigger offboarding workflow: {e}")
            return None

    def _invite_to_github(self, collected: dict) -> Optional[dict]:
        """Invite user to GitHub org."""
        if not self.github_client or not collected.get("github_username"):
            return None

        result = self.github_client.invite_to_org(collected["github_username"])
        if result.get("success"):
            self.logger.info(f"Invited {collected['github_username']} to GitHub org")
        else:
            self.logger.warning(f"GitHub invite failed: {result.get('error')}")
        return result

    def _remove_from_github(self, collected: dict) -> Optional[dict]:
        """Remove user from GitHub org."""
        if not self.github_client or not collected.get("github_username"):
            return None

        result = self.github_client.remove_from_org(collected["github_username"])
        if result.get("success"):
            self.logger.info(f"Removed {collected['github_username']} from GitHub org")
        else:
            self.logger.warning(f"GitHub removal failed: {result.get('error')}")
        return result

    def _add_to_meetings(self, collected: dict) -> Optional[dict]:
        """Add user to Zoom meetings."""
        add_to_meetings = collected.get("add_to_meetings", "later")
        if add_to_meetings != "now":
            return None
        if not self.zoom_meetings_client or not self.meeting_ids:
            return None

        try:
            name_parts = collected["name"].split()
            first_name = name_parts[0] if name_parts else collected["name"]
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            result = self.zoom_meetings_client.add_to_multiple_meetings(
                meeting_ids=self.meeting_ids,
                email=collected.get("email"),
                first_name=first_name,
                last_name=last_name
            )
            if result.get("success"):
                self.logger.info(
                    f"Added {collected['name']} to {len(self.meeting_ids)} meetings"
                )
            else:
                self.logger.warning(
                    f"Some meeting registrations failed: {result.get('errors')}"
                )
            return result
        except Exception as e:
            self.logger.error(f"Failed to add to meetings: {e}")
            return {"success": False, "error": str(e)}

    def _remove_from_meetings(
        self, collected: dict, intern_name: str
    ) -> Optional[dict]:
        """Remove user from Zoom meetings."""
        remove_from_meetings = collected.get("remove_from_meetings", "later")
        if remove_from_meetings != "now":
            return None
        if not self.zoom_meetings_client or not self.meeting_ids:
            return None

        try:
            result = self.zoom_meetings_client.remove_from_multiple_meetings(
                meeting_ids=self.meeting_ids,
                email=collected.get("email")
            )
            if result.get("success"):
                self.logger.info(
                    f"Removed {intern_name} from {len(self.meeting_ids)} meetings"
                )
            else:
                self.logger.warning(
                    f"Some meeting removals failed: {result.get('errors')}"
                )
            return result
        except Exception as e:
            self.logger.error(f"Failed to remove from meetings: {e}")
            return {"success": False, "error": str(e)}

    def _build_onboarding_message(
        self,
        collected: dict,
        n8n_result: Optional[dict],
        github_result: Optional[dict],
        meetings_result: Optional[dict]
    ) -> str:
        """Build success message for onboarding completion."""
        message = f"**{collected['name']} has been onboarded!**\n\n"

        if n8n_result:
            message += "- Welcome email queued\n"
            message += "- Orientation checklist scheduled\n"

        add_to_meetings = collected.get("add_to_meetings", "later")
        if add_to_meetings == "now":
            if meetings_result and meetings_result.get("success"):
                num_meetings = len(meetings_result.get("meetings", []))
                message += f"- Added to {num_meetings} Zoom meeting(s)\n"
            elif meetings_result and meetings_result.get("errors"):
                message += "- Some meeting registrations failed\n"
            elif not self.zoom_meetings_client:
                message += "- Zoom meetings client not configured\n"
        else:
            message += "- Zoom meetings: will be added on start date\n"

        if github_result and github_result.get("success"):
            if github_result.get("state") == "pending":
                message += f"- GitHub org invite sent to {collected['github_username']}\n"
            else:
                message += f"- {collected['github_username']} already in GitHub org\n"
        elif github_result:
            message += f"- GitHub invite issue: {github_result.get('error', 'unknown')}\n"

        return message

    def _build_offboarding_message(
        self,
        intern_name: str,
        collected: dict,
        n8n_result: Optional[dict],
        github_result: Optional[dict],
        meetings_result: Optional[dict]
    ) -> str:
        """Build success message for offboarding completion."""
        message = f"**{intern_name} has been offboarded.**\n\n"

        if n8n_result:
            message += "- Farewell email sent\n"
            message += "- Exit survey shared\n"

        if github_result and github_result.get("success"):
            message += "- Removed from GitHub org\n"
        elif github_result:
            message += f"- GitHub removal issue: {github_result.get('error', 'unknown')}\n"

        remove_from_meetings = collected.get("remove_from_meetings", "later")
        if remove_from_meetings == "now":
            if meetings_result and meetings_result.get("success"):
                num_meetings = len(meetings_result.get("meetings", []))
                message += f"- Removed from {num_meetings} Zoom meeting(s)\n"
            elif meetings_result and meetings_result.get("errors"):
                message += "- Some meeting removals failed\n"
            elif not self.zoom_meetings_client:
                message += "- Zoom meetings client not configured\n"
        else:
            message += "- Zoom meetings: will keep access until last day\n"

        return message
