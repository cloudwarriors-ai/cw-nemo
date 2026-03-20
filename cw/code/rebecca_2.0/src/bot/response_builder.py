"""
Response builder for formatting bot responses.

Formats issues and data for Zoom Team Chat display.
"""
from typing import Optional

from ..github_client import Issue


class ResponseBuilder:
    """
    Build formatted responses for Zoom Team Chat.

    Respects Zoom's message length limits and formatting capabilities.
    """

    MAX_MESSAGE_LENGTH = 4000
    MAX_ISSUES_PER_RESPONSE = 15

    def __init__(self):
        """Initialize the response builder."""
        pass

    def format_issue_list(
        self,
        issues: list[Issue],
        title: str,
        show_repo: bool = True,
        max_issues: int = None
    ) -> str:
        """
        Format a list of issues for display.

        Args:
            issues: List of Issue objects
            title: Header for the list
            show_repo: Include repo name in each line
            max_issues: Maximum issues to show (default: MAX_ISSUES_PER_RESPONSE)

        Returns:
            Formatted markdown string
        """
        max_issues = max_issues or self.MAX_ISSUES_PER_RESPONSE

        lines = [f"## {title} ({len(issues)})", ""]

        if not issues:
            lines.append("No issues found.")
            return "\n".join(lines)

        # Truncate if too many
        displayed = issues[:max_issues]
        truncated = len(issues) > max_issues

        for issue in displayed:
            icon = self._get_status_icon(issue)
            assignee = issue.assignee or "UNASSIGNED"

            if show_repo:
                line = f"- {icon} [{issue.repo}#{issue.number}]({issue.url}) {issue.title} ({assignee})"
            else:
                line = f"- {icon} [#{issue.number}]({issue.url}) {issue.title} ({assignee})"

            # Truncate long titles
            if len(line) > 200:
                line = line[:197] + "..."

            lines.append(line)

        if truncated:
            lines.append("")
            lines.append(f"*...and {len(issues) - max_issues} more*")

        return "\n".join(lines)

    def format_summary(self, stats: dict) -> str:
        """
        Format issue summary statistics.

        Args:
            stats: Dictionary from IssueCache.get_stats()

        Returns:
            Formatted markdown string
        """
        lines = [
            "## Issue Summary",
            "",
            f"**Total Open Issues:** {stats['total']}",
            "",
        ]

        # Quick stats
        if stats.get("high_priority", 0) > 0:
            lines.append(f"- High Priority: {stats['high_priority']}")
        if stats.get("assigned", 0) > 0:
            lines.append(f"- Assigned: {stats['assigned']}")
        if stats.get("unassigned", 0) > 0:
            lines.append(f"- Unassigned: {stats['unassigned']}")
        if stats.get("stale", 0) > 0:
            lines.append(f"- Stale (14+ days): {stats['stale']}")
        if stats.get("missing_priority", 0) > 0:
            lines.append(f"- Missing Priority: {stats['missing_priority']}")

        # By repo table
        by_repo = stats.get("by_repo", {})
        if by_repo:
            lines.append("")
            lines.append("**By Repository:**")
            lines.append("")
            lines.append("| Repo | Issues |")
            lines.append("|------|--------|")
            for repo, count in sorted(by_repo.items()):
                lines.append(f"| {repo} | {count} |")

        # Cache info
        cache_age = stats.get("cache_age_seconds", 0)
        lines.append("")
        lines.append(f"*Data cached {cache_age:.0f} seconds ago*")

        return "\n".join(lines)

    def format_help(self) -> str:
        """
        Format help message showing available commands.

        Returns:
            Formatted markdown string
        """
        return """## QA Bot Commands

**Issue Queries:**
- `high priority` - Show high priority issues
- `assigned` - Show issues that have an assignee
- `unassigned` - Show unassigned issues
- `stale` - Show issues with no update in 14+ days
- `hygiene` - Show issues missing required fields
- `summary` - Show count breakdown by repo

**Filters (combine with above):**
- `repo:name` - Filter to specific repo (e.g., `unassigned repo:pulse`)
- `assigned to name` - Filter to specific person

**Other:**
- `intern status` - Check intern progress
- `help` - Show this message
- `escalate` - Talk to a human

**Examples:**
- `high priority`
- `unassigned repo:pulse`
- `stale assigned to alice`
- `summary`"""

    def format_unknown_query(self, query: str) -> str:
        """
        Format response for unrecognized queries.

        Args:
            query: The unrecognized query

        Returns:
            Helpful response pointing to help command
        """
        return (
            f"I'm not sure how to help with: \"{query[:50]}...\"\n\n"
            "Try one of these commands:\n"
            "- `high priority` - High priority issues\n"
            "- `unassigned` - Issues without an owner\n"
            "- `summary` - Overview of all issues\n"
            "- `help` - Full list of commands\n\n"
            "Or say `escalate` to talk to a human."
        )

    def format_intern_status(self, intern_data: dict) -> str:
        """
        Format intern status information.

        Args:
            intern_data: Dictionary with intern info from database

        Returns:
            Formatted markdown string
        """
        if not intern_data:
            return "No intern data found. Try `intern status [name]` with a specific name."

        lines = [f"## Intern Status: {intern_data.get('name', 'Unknown')}", ""]

        # Basic info
        if intern_data.get("program"):
            lines.append(f"**Program:** {intern_data['program']}")
        if intern_data.get("status"):
            lines.append(f"**Status:** {intern_data['status']}")
        if intern_data.get("supervisor"):
            lines.append(f"**Supervisor:** {intern_data['supervisor']}")

        # Task summary
        tasks = intern_data.get("tasks", {})
        if tasks:
            lines.append("")
            lines.append("**Tasks:**")
            lines.append(f"- In Progress: {tasks.get('in_progress', 0)}")
            lines.append(f"- Completed: {tasks.get('completed', 0)}")
            lines.append(f"- Blocked: {tasks.get('blocked', 0)}")

        # Recent activity
        recent = intern_data.get("recent_activity", [])
        if recent:
            lines.append("")
            lines.append("**Recent Activity:**")
            for activity in recent[:3]:
                lines.append(f"- {activity}")

        return "\n".join(lines)

    def format_error(self, message: str) -> str:
        """
        Format an error message.

        Args:
            message: Error description

        Returns:
            User-friendly error message
        """
        return (
            f"Sorry, something went wrong: {message}\n\n"
            "Please try again or say `escalate` for human help."
        )

    def format_onboarding(self, topic: str = None) -> str:
        """
        Format onboarding information with documentation links.

        Args:
            topic: Specific topic (contacts, meetings, docs, etc.) or None for all

        Returns:
            Formatted markdown string with relevant links
        """
        from .config import get_config
        config = get_config().onboarding

        if topic and topic.lower() in ["contact", "contacts", "who"]:
            return self._format_contacts(config.contacts)

        if topic and topic.lower() in ["meeting", "meetings", "schedule"]:
            return self._format_meetings(config.meetings)

        if topic and topic.lower() in ["cab", "change", "change control"]:
            link = config.links.get("change_control", {})
            return (
                f"## Change Control / CAB Review\n\n"
                f"**{link.get('title', 'Change Control')}**\n"
                f"{link.get('description', '')}\n\n"
                f"Link: {link.get('url', 'Not configured')}\n\n"
                "CAB Review is held weekly on Monday."
            )

        # Default: show all key resources
        lines = [
            "## Onboarding Resources",
            "",
            "**Key Documentation:**",
            "",
        ]

        for key, link_info in config.links.items():
            lines.append(f"- [{link_info['title']}]({link_info['url']})")
            lines.append(f"  {link_info['description']}")
            lines.append("")

        lines.append("**Key Contacts:**")
        for role, contact in config.contacts.items():
            lines.append(f"- **{contact['name']}** - {contact['role']}")

        lines.append("")
        lines.append("**Regular Meetings:**")
        for meeting in config.meetings[:4]:
            lines.append(f"- {meeting['name']}: {meeting['frequency']} ({meeting['time']})")

        lines.append("")
        lines.append("*Ask me about specific topics: 'contacts', 'meetings', 'change control'*")

        return "\n".join(lines)

    def _format_contacts(self, contacts: dict) -> str:
        """Format key contacts information."""
        lines = [
            "## Key Contacts",
            "",
        ]
        for role, contact in contacts.items():
            lines.append(f"**{contact['name']}** - {contact['role']}")
            lines.append("")

        lines.append("*For technical onboarding questions, reach out to Chad or Trent.*")
        return "\n".join(lines)

    def _format_meetings(self, meetings: list) -> str:
        """Format meeting schedule information."""
        lines = [
            "## Meeting Schedule",
            "",
            "| Meeting | Frequency | Time |",
            "|---------|-----------|------|",
        ]
        for meeting in meetings:
            lines.append(f"| {meeting['name']} | {meeting['frequency']} | {meeting['time']} |")

        lines.append("")
        lines.append("*DevOps Morning Meeting is your main daily touchpoint.*")
        return "\n".join(lines)

    def _get_status_icon(self, issue: Issue) -> str:
        """Get status emoji for an issue."""
        if not issue.assignee:
            return "🔴"  # Unassigned
        if issue.is_stale:
            return "🟡"  # Stale
        if issue.priority and issue.priority.lower() == "high":
            return "🔥"  # High priority
        return "🟢"  # OK

    def truncate_response(self, response: str) -> str:
        """
        Truncate response to fit Zoom's message limits.

        Args:
            response: Full response text

        Returns:
            Truncated response if necessary
        """
        if len(response) <= self.MAX_MESSAGE_LENGTH:
            return response

        # Find a good break point
        truncate_at = self.MAX_MESSAGE_LENGTH - 50
        last_newline = response.rfind("\n", 0, truncate_at)

        if last_newline > truncate_at // 2:
            truncate_at = last_newline

        return response[:truncate_at] + "\n\n*... response truncated*"
