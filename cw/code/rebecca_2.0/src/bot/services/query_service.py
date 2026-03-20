"""
Query processing service.

Handles the core query processing logic, supporting:
- LLM Brain (natural language understanding)
- Keyword parser (legacy fallback)
- Issue cache queries
- Escalation handling
"""

from typing import Optional, Any, Union
import logging

from ..config import get_config, BOT_MENTIONS
from .workflow_capability_handler import WorkflowCapabilityHandler
from .query_context import QueryContext

_config = get_config()


class QueryService:
    """
    Service for processing user queries.

    Orchestrates:
    - Input sanitization
    - LLM brain or keyword parsing
    - Issue cache lookups
    - Response formatting
    - Workflow capabilities (delegated to WorkflowCapabilityHandler)
    - Multi-turn conversation flows
    """

    def __init__(
        self,
        qa_brain: Optional[Any] = None,
        query_parser: Optional[Any] = None,
        issue_cache: Optional[Any] = None,
        escalation_manager: Optional[Any] = None,
        response_builder: Optional[Any] = None,
        workflow_handler: Optional[WorkflowCapabilityHandler] = None,
        conversation_flow_handler: Optional[Any] = None,
        logger: Optional[logging.Logger] = None
    ):
        self.qa_brain = qa_brain
        self.query_parser = query_parser
        self.issue_cache = issue_cache
        self.escalation_manager = escalation_manager
        self.response_builder = response_builder
        self.workflow_handler = workflow_handler
        self.conversation_flow_handler = conversation_flow_handler
        self.logger = logger or logging.getLogger(__name__)

    def sanitize_input(
        self,
        text: str,
        max_length: Optional[int] = None
    ) -> str:
        """
        Sanitize user input.

        - Truncates to max length
        - Strips bot mentions
        - Removes leading/trailing whitespace

        Args:
            text: Raw input text
            max_length: Maximum allowed length

        Returns:
            Sanitized text
        """
        if not text:
            return ""

        max_length = max_length or _config.input.max_input_length
        text = text[:max_length]

        # Strip bot mentions from beginning
        text_lower = text.lower()
        for mention in BOT_MENTIONS:
            if text_lower.startswith(mention):
                text = text[len(mention):].lstrip()
                break

        # Strip leading dashes/punctuation (common in chat: "@bot - command")
        return text.strip().lstrip("- ").strip()

    def process_query(
        self,
        text: Union[str, QueryContext],
        user_id: str = "",
        user_name: str = "",
        channel_id: str = "",
        request_id: str = "",
        user_email: str = ""
    ) -> str:
        """
        Process a user query and return response text.

        Checks for active conversation flows first, then uses LLM Brain
        if available, falls back to keyword matching.

        Args:
            text: User's query text OR a QueryContext object
            user_id: User identifier (ignored if QueryContext passed)
            user_name: User display name (ignored if QueryContext passed)
            channel_id: Zoom channel ID (ignored if QueryContext passed)
            request_id: Request ID for logging (ignored if QueryContext passed)
            user_email: User email for authorization (ignored if QueryContext passed)

        Returns:
            Response text
        """
        # Support both QueryContext and legacy parameter-based calls
        if isinstance(text, QueryContext):
            ctx = text
        else:
            ctx = QueryContext(
                text=text,
                user_id=user_id,
                user_name=user_name,
                channel_id=channel_id,
                request_id=request_id,
                user_email=user_email
            )

        text_lower = ctx.text_lower.lstrip("- ")

        # Check for intern form template command FIRST
        if text_lower in ("intern form", "new intern form", "onboarding form", "intern template"):
            self.logger.info(f"{ctx.log_prefix()} Returning intern form template")
            return WorkflowCapabilityHandler.get_intern_form_template()

        # Check for offboard form template command
        if text_lower in ("offboard form", "offboarding form", "offboard template", "exit form"):
            self.logger.info(f"{ctx.log_prefix()} Returning offboard form template")
            return WorkflowCapabilityHandler.get_offboard_form_template()

        # Check for bulk offboarding submission (has offboarding field patterns)
        if self.conversation_flow_handler and self.workflow_handler:
            bulk_offboard = self.conversation_flow_handler.parse_bulk_offboarding(ctx.text)
            if bulk_offboard:
                self.logger.info(f"{ctx.log_prefix()} Detected bulk offboarding submission")
                return self.workflow_handler.handle_bulk_offboarding(
                    ctx.text, ctx.user_id, ctx.user_name, ctx.channel_id,
                    ctx.request_id, ctx.user_email
                )

        # Check for bulk onboarding submission (has multiple field patterns)
        if self.conversation_flow_handler and self.workflow_handler:
            bulk_data = self.conversation_flow_handler.parse_bulk_submission(ctx.text)
            if bulk_data:
                self.logger.info(f"{ctx.log_prefix()} Detected bulk onboarding submission")
                return self.workflow_handler.handle_bulk_onboarding(
                    ctx.text, ctx.user_id, ctx.user_name, ctx.channel_id,
                    ctx.request_id, ctx.user_email
                )

        # Check for active conversation flow
        if self.conversation_flow_handler:
            if self.conversation_flow_handler.is_in_flow(ctx.user_id):
                self.logger.debug(f"{ctx.log_prefix()} User {ctx.user_id} in active flow")
                result = self.conversation_flow_handler.handle_response(
                    user_id=ctx.user_id,
                    text=ctx.text,
                    actor_name=ctx.user_name
                )
                return result.message

        if self.qa_brain:
            return self._process_with_brain(ctx)

        return self._process_with_parser(ctx)

    def _process_with_brain(self, ctx: QueryContext) -> str:
        """Process query using LLM Brain."""
        from ..llm_brain import Capability

        brain_result = self.qa_brain.chat_query(
            user_query=ctx.text,
            user_name=ctx.user_name,
        )

        self.logger.info(
            f"{ctx.log_prefix()} Brain: capability={brain_result.capability.value}, "
            f"confidence={brain_result.confidence}, latency={brain_result.latency_ms}ms"
        )

        # Handle escalation
        if brain_result.capability == Capability.ESCALATE:
            if self.escalation_manager:
                return self.escalation_manager.escalate(
                    user_id=ctx.user_id,
                    user_name=ctx.user_name,
                    topic=ctx.text,
                    channel_id=ctx.channel_id
                )
            return "I've noted your request. A team member will follow up."

        # Handle help
        if brain_result.capability == Capability.HELP:
            return brain_result.response

        # Handle general questions
        if brain_result.capability == Capability.GENERAL:
            return brain_result.response

        # Handle unknown/low confidence
        if brain_result.capability == Capability.UNKNOWN or brain_result.confidence < 0.5:
            return f"{brain_result.response}\n\nType `help` to see what I can do."

        # Handle workflow capabilities (delegated to WorkflowCapabilityHandler)
        if self.workflow_handler:
            if brain_result.capability == Capability.WEEKLY_REPORT:
                return self.workflow_handler.handle_weekly_report(
                    ctx.channel_id, ctx.request_id
                )

            if brain_result.capability == Capability.ONBOARDING:
                return self.workflow_handler.handle_onboarding(
                    brain_result.filters, ctx.user_id, ctx.user_name,
                    ctx.channel_id, ctx.request_id, ctx.user_email
                )

            if brain_result.capability == Capability.OFFBOARDING:
                return self.workflow_handler.handle_offboarding(
                    brain_result.filters, ctx.user_id, ctx.user_name,
                    ctx.channel_id, ctx.request_id, ctx.user_email
                )

            if brain_result.capability == Capability.INTERN_STATUS:
                return self.workflow_handler.handle_intern_status(
                    brain_result.filters, ctx.request_id
                )

            if brain_result.capability == Capability.MEETING_JOIN:
                return self.workflow_handler.handle_meeting_join(
                    brain_result.filters, ctx.user_name, ctx.request_id
                )

        # Issue-related queries
        if not self.issue_cache:
            return (
                "GitHub integration not configured. "
                "Please contact an administrator to set up the bot."
            )

        return self._handle_issue_query(brain_result, ctx.request_id)

    def _handle_issue_query(self, brain_result: Any, request_id: str) -> str:
        """Handle issue-related queries from brain result."""
        from ..llm_brain import Capability

        filters = brain_result.filters or {}
        repo = filters.get("repo")
        assignee = filters.get("assignee")
        priority = filters.get("priority")
        status = filters.get("status")

        # Repo info queries
        if brain_result.capability == Capability.REPO_INFO:
            if repo:
                issues = self.issue_cache.get_repo_issues(repo)
                if issues and self.response_builder:
                    stats = self._get_repo_stats(issues)
                    return self._format_repo_info(repo, stats, issues[:5])
            if self.response_builder:
                stats = self.issue_cache.get_stats()
                return self.response_builder.format_summary(stats)

        # Issue queries
        if brain_result.capability == Capability.ISSUE_QUERY:
            if priority == "high":
                issues = self.issue_cache.get_filtered(repo=repo, assignee=assignee, priority="high")
                if self.response_builder:
                    return self.response_builder.format_issue_list(issues, "High Priority Issues")

            if assignee == "unassigned":
                issues = self.issue_cache.get_filtered(repo=repo, unassigned_only=True)
                if self.response_builder:
                    return self.response_builder.format_issue_list(issues, "Unassigned Issues")

            if status == "stale":
                issues = self.issue_cache.get_filtered(repo=repo, assignee=assignee, stale_only=True)
                if self.response_builder:
                    return self.response_builder.format_issue_list(issues, "Stale Issues (14+ days)")

            # Default: all issues with filters
            issues = self.issue_cache.get_filtered(
                repo=repo,
                assignee=assignee if assignee != "unassigned" else None
            )
            title = "Issues"
            if repo:
                title = f"Issues in {repo}"
            if assignee and assignee != "unassigned":
                title = f"Issues assigned to {assignee}"
            if self.response_builder:
                return self.response_builder.format_issue_list(issues, title)

        # Fallback
        if brain_result.response:
            return brain_result.response

        if self.response_builder:
            return self.response_builder.format_help()
        return "Type `help` to see what I can do."

    def _process_with_parser(self, ctx: QueryContext) -> str:
        """Process query using legacy keyword parser."""
        from ..query_parser import QueryType

        if not self.query_parser:
            return "Query parser not available."

        result = self.query_parser.parse(ctx.text)
        self.logger.info(f"{ctx.log_prefix()} Parser: type={result.query_type.value}")

        # Handle escalation
        if self.escalation_manager and self.escalation_manager.should_escalate(
            ctx.text, result.confidence
        ):
            return self.escalation_manager.escalate(
                user_id=ctx.user_id,
                user_name=ctx.user_name,
                topic=ctx.text,
                channel_id=ctx.channel_id
            )

        # Handle by query type
        if result.query_type == QueryType.HELP:
            if self.response_builder:
                return self.response_builder.format_help()
            return "Available commands: help, summary, high priority, unassigned, stale"

        if result.query_type == QueryType.ESCALATE:
            if self.escalation_manager:
                return self.escalation_manager.escalate(
                    user_id=ctx.user_id,
                    user_name=ctx.user_name,
                    topic=result.topic or ctx.text,
                    channel_id=ctx.channel_id
                )
            return "I've noted your request. A team member will follow up."

        if result.query_type == QueryType.UNKNOWN:
            if self.response_builder:
                return self.response_builder.format_unknown_query(ctx.text)
            return "I'm not sure how to help with that. Type `help` for commands."

        # Issue queries require cache
        if not self.issue_cache:
            return "GitHub integration not configured."

        if result.query_type == QueryType.SUMMARY:
            stats = self.issue_cache.get_stats()
            if self.response_builder:
                return self.response_builder.format_summary(stats)
            return f"Total issues: {stats.get('total', 0)}"

        # Other query types...
        if self.response_builder:
            return self.response_builder.format_unknown_query(ctx.text)
        return "Query not recognized."

    def _get_repo_stats(self, issues: list) -> dict:
        """Calculate stats for a list of issues."""
        if not issues:
            return {"total": 0, "open": 0, "high_priority": 0, "unassigned": 0, "stale": 0}

        stats = {"total": len(issues), "open": 0, "high_priority": 0, "unassigned": 0, "stale": 0}

        for issue in issues:
            if hasattr(issue, 'repo'):
                stats["open"] += 1
                if issue.priority and issue.priority.lower() == "high":
                    stats["high_priority"] += 1
                if not issue.assignee:
                    stats["unassigned"] += 1
                if issue.is_stale:
                    stats["stale"] += 1

        return stats

    def _format_repo_info(self, repo_name: str, stats: dict, recent_issues: list) -> str:
        """Format repo information response."""
        lines = [f"**{repo_name}**"]
        lines.append(f"Open issues: {stats['open']}")

        if stats["high_priority"] > 0:
            lines.append(f"High priority: {stats['high_priority']}")
        if stats["unassigned"] > 0:
            lines.append(f"Unassigned: {stats['unassigned']}")
        if stats["stale"] > 0:
            lines.append(f"Stale (14+ days): {stats['stale']}")

        if recent_issues:
            lines.append("\n**Recent issues:**")
            for issue in recent_issues[:5]:
                if hasattr(issue, 'repo'):
                    title = issue.title or "Untitled"
                    number = issue.number or "?"
                else:
                    title = issue.get("title", "Untitled")
                    number = issue.get("number", "?")
                lines.append(f"- #{number}: {title}")

        return "\n".join(lines)
