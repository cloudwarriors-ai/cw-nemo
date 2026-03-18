"""
Report generator for QA issue reports.
"""
from collections import defaultdict
from datetime import datetime
from typing import Optional

from .github_client import Issue


class ReportGenerator:
    """Generate formatted QA reports from GitHub issues."""

    def generate_weekly_report(self, issues: list[Issue], title: Optional[str] = None) -> str:
        """
        Generate a weekly issue report.

        Args:
            issues: List of Issue objects
            title: Optional custom title

        Returns:
            Formatted markdown report
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        title = title or f"QA Issue Report - {date_str}"

        lines = [f"# {title}", ""]

        # Summary statistics
        total = len(issues)
        unassigned = sum(1 for i in issues if not i.assignee)
        stale = sum(1 for i in issues if i.is_stale)
        no_priority = sum(1 for i in issues if not i.priority)

        lines.append(f"**Total Open Issues: {total}**")
        if unassigned > 0:
            lines.append(f"- Unassigned: {unassigned}")
        if stale > 0:
            lines.append(f"- Stale (>14 days): {stale}")
        if no_priority > 0:
            lines.append(f"- Missing priority: {no_priority}")
        lines.append("")

        # Group by repository
        by_repo = defaultdict(list)
        for issue in issues:
            by_repo[issue.repo].append(issue)

        # Sort repos alphabetically
        for repo in sorted(by_repo.keys()):
            repo_issues = by_repo[repo]
            lines.append(f"## {repo} ({len(repo_issues)} issues)")
            lines.append("")

            # Sort by priority (high first), then by issue number
            priority_order = {"high": 0, "medium": 1, "low": 2, None: 3}
            sorted_issues = sorted(
                repo_issues,
                key=lambda i: (priority_order.get(i.priority.lower() if i.priority else None, 3), i.number)
            )

            for issue in sorted_issues:
                status_icon = self._get_status_icon(issue)
                assignee_str = issue.assignee or "UNASSIGNED"
                priority_str = f"[{issue.priority}]" if issue.priority else ""

                line = f"- {status_icon} [#{issue.number}]({issue.url}) {issue.title}"
                if priority_str:
                    line += f" {priority_str}"
                line += f" ({assignee_str})"

                if issue.is_stale:
                    line += " - STALE"

                lines.append(line)

            lines.append("")

        return "\n".join(lines)

    def generate_hygiene_report(self, issues: list[Issue]) -> str:
        """
        Generate a report focused on issue hygiene problems.

        Args:
            issues: List of Issue objects

        Returns:
            Formatted markdown report highlighting hygiene issues
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        lines = [f"# Issue Hygiene Report - {date_str}", ""]

        # Find issues with problems
        unassigned = [i for i in issues if not i.assignee]
        no_priority = [i for i in issues if not i.priority]
        stale = [i for i in issues if i.is_stale]

        if not unassigned and not no_priority and not stale:
            lines.append("All issues pass hygiene checks.")
            return "\n".join(lines)

        if unassigned:
            lines.append(f"## Unassigned Issues ({len(unassigned)})")
            lines.append("")
            for issue in unassigned:
                lines.append(f"- [{issue.repo}#{issue.number}]({issue.url}) {issue.title}")
            lines.append("")

        if no_priority:
            lines.append(f"## Missing Priority Label ({len(no_priority)})")
            lines.append("")
            for issue in no_priority:
                assignee = issue.assignee or "unassigned"
                lines.append(f"- [{issue.repo}#{issue.number}]({issue.url}) {issue.title} ({assignee})")
            lines.append("")

        if stale:
            lines.append(f"## Stale Issues - No Update in 14+ Days ({len(stale)})")
            lines.append("")
            for issue in stale:
                assignee = issue.assignee or "unassigned"
                lines.append(f"- [{issue.repo}#{issue.number}]({issue.url}) {issue.title} ({assignee}) - last update: {issue.updated}")
            lines.append("")

        return "\n".join(lines)

    def _get_status_icon(self, issue: Issue) -> str:
        """Get status icon for an issue."""
        if not issue.assignee:
            return "🔴"  # Unassigned
        if issue.is_stale:
            return "🟡"  # Stale
        if issue.priority and issue.priority.lower() == "high":
            return "🔥"  # High priority
        return "🟢"  # OK
