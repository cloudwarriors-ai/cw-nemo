"""
Query and workflow handler functions.

Extracted from app.py during Phase 3 refactoring.
These handlers process user queries and trigger workflows.
"""
from typing import Optional

from flask import Flask

from .llm_brain import Capability
from .query_parser import QueryType
from .database import get_intern_status


def process_query(
    app: Flask,
    text: str,
    user_id: str,
    user_name: str,
    channel_id: str,
    request_id: str,
    conversation_history: list = None
) -> str:
    """
    Process a user query and return the response text.

    Uses QA Brain (LLM) if configured, falls back to keyword matching.

    Args:
        app: Flask application with components
        text: User's query text (already sanitized)
        user_id: User identifier
        user_name: User display name
        channel_id: Zoom channel ID
        request_id: Request ID for logging
        conversation_history: Optional list of previous messages for context

    Returns:
        Response text to send back
    """
    # Use LLM Brain if available
    if app.qa_brain:
        return process_query_with_brain(
            app, text, user_id, user_name, channel_id, request_id,
            conversation_history=conversation_history
        )

    # Fall back to legacy keyword matching
    return process_query_legacy(
        app, text, user_id, user_name, channel_id, request_id
    )


def process_query_with_brain(
    app: Flask,
    text: str,
    user_id: str,
    user_name: str,
    channel_id: str,
    request_id: str,
    conversation_history: list = None
) -> str:
    """
    Process query using LLM Brain.

    The brain understands natural language and returns structured
    responses with capability and filter information.
    """
    from .utils.formatters import get_repo_stats, format_repo_info

    # Get brain response
    brain_result = app.qa_brain.chat_query(
        user_query=text,
        user_name=user_name,
        conversation_history=conversation_history,
    )

    app.logger.info(
        f"[{request_id}] Brain: capability={brain_result.capability.value}, "
        f"confidence={brain_result.confidence}, latency={brain_result.latency_ms}ms"
    )

    # Handle escalation
    if brain_result.capability == Capability.ESCALATE:
        return app.escalation_manager.escalate(
            user_id=user_id,
            user_name=user_name,
            topic=text,
            channel_id=channel_id
        )

    # Handle help
    if brain_result.capability == Capability.HELP:
        return brain_result.response

    # Handle general questions (direct LLM response)
    if brain_result.capability == Capability.GENERAL:
        return brain_result.response

    # Handle unknown/low confidence
    if brain_result.capability == Capability.UNKNOWN or brain_result.confidence < 0.5:
        # Include help text with the response
        return (
            f"{brain_result.response}\n\n"
            "Type `help` to see what I can do."
        )

    # Handle onboarding requests
    if brain_result.capability == Capability.ONBOARDING:
        return handle_onboarding_request(
            app, brain_result.filters, user_name, request_id
        )

    # Handle offboarding requests
    if brain_result.capability == Capability.OFFBOARDING:
        return handle_offboarding_request(
            app, brain_result.filters, user_name, request_id
        )

    # Handle intern status queries
    if brain_result.capability == Capability.INTERN_STATUS:
        return handle_intern_status_request(
            app, brain_result.filters, request_id
        )

    # Handle meeting join requests
    if brain_result.capability == Capability.MEETING_JOIN:
        return handle_meeting_join_request(
            app, brain_result.filters, user_name, request_id
        )

    # Handle weekly report requests
    if brain_result.capability == Capability.WEEKLY_REPORT:
        return handle_weekly_report_request(
            app, channel_id, request_id
        )

    # Issue-related queries require cache
    if not app.issue_cache:
        return (
            "GitHub integration not configured. "
            "Please contact an administrator to set up the bot."
        )

    # Extract filters from brain response
    filters = brain_result.filters or {}
    repo = filters.get("repo")
    assignee = filters.get("assignee")
    priority = filters.get("priority")
    status = filters.get("status")

    app.logger.info(f"[{request_id}] Filters: repo={repo}, assignee={assignee}, priority={priority}, status={status}")

    # Handle repo info queries
    if brain_result.capability == Capability.REPO_INFO:
        if repo:
            # Check if repo is in monitored list
            monitored_repos = app.config.get("REPOS", [])
            repo_lower = repo.lower()
            matched_repo = None

            # Exact match first
            for r in monitored_repos:
                if r.lower() == repo_lower:
                    matched_repo = r
                    break

            # If no exact match, try prefix/suffix match
            if not matched_repo:
                for r in monitored_repos:
                    r_lower = r.lower()
                    segments = r_lower.replace("_", "-").split("-")
                    if repo_lower in segments or r_lower.startswith(repo_lower + "-"):
                        matched_repo = r
                        break

            if matched_repo:
                # Use single-repo fetch - much faster than refreshing all repos
                issues = app.issue_cache.get_repo_issues(matched_repo)
                stats = get_repo_stats(issues)
                return format_repo_info(matched_repo, stats, issues[:5])
            else:
                return (
                    f"I don't monitor a repo called '{repo}'.\n"
                    f"I'm watching {len(monitored_repos)} repos. "
                    "Try `summary` to see them all."
                )
        else:
            stats = app.issue_cache.get_stats()
            return app.response_builder.format_summary(stats)

    # Handle issue queries
    if brain_result.capability == Capability.ISSUE_QUERY:
        # Build filter based on brain's understanding
        if priority == "high":
            issues = app.issue_cache.get_filtered(
                repo=repo,
                assignee=assignee,
                priority="high"
            )
            return app.response_builder.format_issue_list(
                issues, "High Priority Issues"
            )

        if assignee == "unassigned":
            issues = app.issue_cache.get_filtered(
                repo=repo,
                unassigned_only=True
            )
            return app.response_builder.format_issue_list(
                issues, "Unassigned Issues"
            )

        if assignee == "assigned":
            issues = app.issue_cache.get_filtered(
                repo=repo,
                assigned_only=True
            )
            app.logger.info(f"[{request_id}] Found {len(issues)} assigned issues for repo={repo}")
            title = "Assigned Issues" if not repo else f"Assigned Issues in {repo}"
            result = app.response_builder.format_issue_list(issues, title)
            app.logger.info(f"[{request_id}] Formatted response: {result[:200]}...")
            return result

        if status == "stale":
            issues = app.issue_cache.get_filtered(
                repo=repo,
                assignee=assignee,
                stale_only=True
            )
            return app.response_builder.format_issue_list(
                issues, "Stale Issues (14+ days)"
            )

        # Default: get all issues with filters
        issues = app.issue_cache.get_filtered(
            repo=repo,
            assignee=assignee if assignee != "unassigned" else None
        )
        title = "Issues"
        if repo:
            title = f"Issues in {repo}"
        if assignee and assignee != "unassigned":
            title = f"Issues assigned to {assignee}"
        return app.response_builder.format_issue_list(issues, title)

    # Fallback - return brain's response hint or help
    if brain_result.response:
        return brain_result.response

    return app.response_builder.format_help()


def handle_onboarding_request(
    app: Flask,
    filters: dict,
    user_name: str,
    request_id: str
) -> str:
    """
    Handle onboarding workflow request from chat.

    Triggers n8n onboarding workflow for the specified person.
    """
    person_name = filters.get("person_name") if filters else None

    if not person_name:
        return (
            "I need a name to start onboarding. Try:\n"
            "`onboard alice` or `new intern bob`"
        )

    if not app.n8n_client:
        return (
            f"I'd like to start onboarding for **{person_name}**, but n8n workflows aren't configured.\n"
            "Please contact an administrator to set up the integration."
        )

    try:
        result = app.n8n_client.trigger_onboarding({
            "intern_name": person_name,
            "requested_by": user_name,
        })

        app.logger.info(f"[{request_id}] Triggered onboarding for {person_name}")

        return (
            f"Starting onboarding for **{person_name}**!\n\n"
            f"Workflow triggered (ID: {result.get('execution_id', 'pending')})\n"
            "I'll set up their accounts and send welcome materials.\n\n"
            "To check status: `how is {person_name} doing`"
        )
    except Exception as e:
        app.logger.error(f"[{request_id}] Onboarding trigger failed: {e}")
        return (
            f"I couldn't start onboarding for {person_name}.\n"
            "Please try again or contact an administrator."
        )


def handle_offboarding_request(
    app: Flask,
    filters: dict,
    user_name: str,
    request_id: str
) -> str:
    """
    Handle offboarding workflow request from chat.

    Triggers n8n offboarding workflow for the specified person.
    """
    person_name = filters.get("person_name") if filters else None

    if not person_name:
        return (
            "I need a name to start offboarding. Try:\n"
            "`offboard alice` or `bob is leaving`"
        )

    if not app.n8n_client:
        return (
            f"I'd like to start offboarding for **{person_name}**, but n8n workflows aren't configured.\n"
            "Please contact an administrator to set up the integration."
        )

    try:
        result = app.n8n_client.trigger_offboarding({
            "intern_name": person_name,
            "requested_by": user_name,
        })

        app.logger.info(f"[{request_id}] Triggered offboarding for {person_name}")

        return (
            f"Starting offboarding for **{person_name}**.\n\n"
            f"Workflow triggered (ID: {result.get('execution_id', 'pending')})\n"
            "I'll revoke access and archive their materials."
        )
    except Exception as e:
        app.logger.error(f"[{request_id}] Offboarding trigger failed: {e}")
        return (
            f"I couldn't start offboarding for {person_name}.\n"
            "Please try again or contact an administrator."
        )


def handle_intern_status_request(
    app: Flask,
    filters: dict,
    request_id: str
) -> str:
    """
    Handle intern status query from chat.

    Looks up intern progress in the database.
    """
    person_name = filters.get("person_name") if filters else None

    try:
        if person_name:
            # Lookup specific intern
            intern_data = get_intern_status(app.config["DB_PATH"], person_name)
            return app.response_builder.format_intern_status(intern_data)
        else:
            # List all interns
            from .database import get_all_interns
            interns = get_all_interns(app.config["DB_PATH"], status="active")

            if not interns:
                return "No active interns found."

            lines = ["**Active Interns:**\n"]
            for intern in interns[:10]:
                name = intern.get("name", "Unknown")
                program = intern.get("program", "")
                status = intern.get("status", "active")
                supervisor = intern.get("supervisor", "Unassigned")
                prog_str = f" ({program})" if program else ""
                lines.append(f"- **{name}**{prog_str} - {status} - Supervisor: {supervisor}")

            if len(interns) > 10:
                lines.append(f"\n... and {len(interns) - 10} more")

            lines.append("\n\nFor details: `how is [name] doing`")
            return "\n".join(lines)

    except Exception as e:
        app.logger.error(f"[{request_id}] Intern status lookup failed: {e}")
        return "I couldn't retrieve intern information. Please try again."


def handle_meeting_join_request(
    app: Flask,
    filters: dict,
    user_name: str,
    request_id: str
) -> str:
    """
    Handle meeting join request from chat.

    Note: For actual meeting joins with URLs, the Zoom webhook handler
    auto-detects meeting URLs and joins. This handles natural language
    requests like "join the standup".
    """
    meeting_name = filters.get("meeting_name") if filters else None

    if not app.meeting_handler:
        return (
            "Meeting features aren't configured.\n"
            "Please contact an administrator to set up Recall.ai integration."
        )

    if not meeting_name:
        return (
            "I can join meetings! Just:\n"
            "1. **Paste a meeting URL** (Zoom/Teams/Google Meet) and I'll join automatically\n"
            "2. Or say `join the standup` if you have a recurring meeting set up\n\n"
            "Note: I need a meeting URL to join."
        )

    # For named meetings, we'd need a meeting URL lookup system
    # For now, prompt the user to share a URL
    return (
        f"I'd love to join **{meeting_name}**!\n\n"
        "Please paste the meeting URL (Zoom, Teams, or Google Meet) "
        "and I'll join automatically."
    )


def handle_weekly_report_request(
    app: Flask,
    channel_id: str,
    request_id: str
) -> str:
    """
    Handle weekly report request from chat.

    Uses the WorkflowOrchestrator to generate the report and post it
    to the channel where the request came from.
    """
    from .channels import ChannelType

    if not hasattr(app, 'workflow_orchestrator') or not app.workflow_orchestrator:
        return (
            "Weekly reports aren't configured.\n"
            "Please contact an administrator to set up the report service."
        )

    if not channel_id:
        return (
            "I can't determine which channel to post the report to.\n"
            "Please try again from a Zoom Team Chat channel."
        )

    try:
        app.logger.info(f"[{request_id}] Generating weekly report for channel {channel_id[:20]}...")

        # Execute the weekly report workflow
        result = app.workflow_orchestrator.execute_weekly_report(
            channel=ChannelType.ZOOM,
            destination=channel_id,
            force_refresh=False,
        )

        if result.success and result.delivery_success:
            app.logger.info(f"[{request_id}] Weekly report posted successfully")
            return "Weekly report posted to this channel."

        elif result.success and not result.delivery_success:
            # Report generated but delivery failed - return it inline
            app.logger.warning(f"[{request_id}] Report generated but delivery failed: {result.delivery_error}")
            return (
                "I generated the report but couldn't post it separately. Here it is:\n\n"
                f"{result.formatted_content[:1500]}"
            )

        else:
            # Report generation failed
            warnings = ", ".join(result.warnings) if result.warnings else "Unknown error"
            app.logger.error(f"[{request_id}] Weekly report failed: {warnings}")
            return (
                "I couldn't generate the weekly report right now.\n"
                f"Issue: {warnings}\n\n"
                "Try `summary` for a quick overview instead."
            )

    except Exception as e:
        app.logger.error(f"[{request_id}] Weekly report request failed: {e}", exc_info=True)
        return (
            "Something went wrong generating the report.\n"
            "Try `summary` for a quick overview instead."
        )


def process_query_legacy(
    app: Flask,
    text: str,
    user_id: str,
    user_name: str,
    channel_id: str,
    request_id: str
) -> str:
    """
    Process query using legacy keyword matching.

    Fallback when LLM Brain is not configured.
    """
    # Parse the query
    result = app.query_parser.parse(text)

    # Check if escalation needed
    if app.escalation_manager.should_escalate(text, result.confidence):
        return app.escalation_manager.escalate(
            user_id=user_id,
            user_name=user_name,
            topic=text,
            channel_id=channel_id
        )

    # Handle by query type
    if result.query_type == QueryType.HELP:
        return app.response_builder.format_help()

    if result.query_type == QueryType.ESCALATE:
        return app.escalation_manager.escalate(
            user_id=user_id,
            user_name=user_name,
            topic=result.topic or text,
            channel_id=channel_id
        )

    if result.query_type == QueryType.UNKNOWN:
        return app.response_builder.format_unknown_query(text)

    if result.query_type == QueryType.ONBOARDING:
        # Extract topic from query if present
        topic = None
        text_lower = text.lower()
        if "contact" in text_lower or "who" in text_lower:
            topic = "contacts"
        elif "meeting" in text_lower or "schedule" in text_lower:
            topic = "meetings"
        elif "cab" in text_lower or "change control" in text_lower:
            topic = "change control"
        return app.response_builder.format_onboarding(topic)

    # Issue-related queries require cache
    if not app.issue_cache:
        return (
            "GitHub integration not configured. "
            "Please contact an administrator to set up the bot."
        )

    if result.query_type == QueryType.SUMMARY:
        stats = app.issue_cache.get_stats()
        return app.response_builder.format_summary(stats)

    if result.query_type == QueryType.HIGH_PRIORITY:
        issues = app.issue_cache.get_filtered(
            repo=result.repo,
            assignee=result.assignee,
            priority="high"
        )
        return app.response_builder.format_issue_list(
            issues, "High Priority Issues"
        )

    if result.query_type == QueryType.UNASSIGNED:
        issues = app.issue_cache.get_filtered(
            repo=result.repo,
            unassigned_only=True
        )
        return app.response_builder.format_issue_list(
            issues, "Unassigned Issues"
        )

    if result.query_type == QueryType.ASSIGNED:
        issues = app.issue_cache.get_filtered(
            repo=result.repo,
            assigned_only=True
        )
        return app.response_builder.format_issue_list(
            issues, "Assigned Issues"
        )

    if result.query_type == QueryType.STALE:
        issues = app.issue_cache.get_filtered(
            repo=result.repo,
            assignee=result.assignee,
            stale_only=True
        )
        return app.response_builder.format_issue_list(
            issues, "Stale Issues (14+ days)"
        )

    if result.query_type == QueryType.HYGIENE:
        issues = app.issue_cache.get_filtered(
            repo=result.repo,
            hygiene_issues_only=True
        )
        return app.response_builder.format_issue_list(
            issues, "Issues with Hygiene Problems"
        )

    if result.query_type == QueryType.REPO_FILTER:
        issues = app.issue_cache.get_filtered(repo=result.repo)
        return app.response_builder.format_issue_list(
            issues, f"Issues in {result.repo}"
        )

    if result.query_type == QueryType.ASSIGNEE_FILTER:
        issues = app.issue_cache.get_filtered(assignee=result.assignee)
        return app.response_builder.format_issue_list(
            issues, f"Issues assigned to {result.assignee}"
        )

    if result.query_type == QueryType.INTERN_STATUS:
        db_path = app.config["DB_PATH"]
        intern_data = get_intern_status(db_path, result.intern_name)
        return app.response_builder.format_intern_status(intern_data)

    # Fallback
    return app.response_builder.format_unknown_query(text)


# Backwards compatibility aliases (prefixed with underscore for app.py)
_process_query = process_query
_process_query_with_brain = process_query_with_brain
_process_query_legacy = process_query_legacy
_handle_onboarding_request = handle_onboarding_request
_handle_offboarding_request = handle_offboarding_request
_handle_intern_status_request = handle_intern_status_request
_handle_meeting_join_request = handle_meeting_join_request
_handle_weekly_report_request = handle_weekly_report_request
