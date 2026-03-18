"""
Issue hygiene monitoring service.

Identifies issues that need attention:
- Missing labels
- Missing priority
- Missing assignee
- Stale issues (no activity in 14+ days)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..cache import IssueCache


@dataclass
class HygieneIssue:
    """An issue with hygiene problems."""

    repo: str
    number: int
    title: str
    url: str
    problems: list[str] = field(default_factory=list)


@dataclass
class HygieneReport:
    """Daily hygiene check report."""

    generated_at: datetime
    total_issues_checked: int
    issues_needing_attention: int
    missing_labels: list[HygieneIssue] = field(default_factory=list)
    missing_priority: list[HygieneIssue] = field(default_factory=list)
    missing_assignee: list[HygieneIssue] = field(default_factory=list)
    stale_issues: list[HygieneIssue] = field(default_factory=list)
    has_valid_data: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "total_issues_checked": self.total_issues_checked,
            "issues_needing_attention": self.issues_needing_attention,
            "missing_labels_count": len(self.missing_labels),
            "missing_priority_count": len(self.missing_priority),
            "missing_assignee_count": len(self.missing_assignee),
            "stale_issues_count": len(self.stale_issues),
            "has_valid_data": self.has_valid_data,
            "error": self.error,
        }


class HygieneService:
    """
    Service for checking issue hygiene.

    Identifies issues that need attention and generates
    daily alerts for distribution via Zoom Team Chat.
    """

    def __init__(
        self,
        issue_cache: IssueCache,
        logger: logging.Logger = None
    ):
        """
        Initialize hygiene service.

        Args:
            issue_cache: IssueCache instance for GitHub data
            logger: Logger instance
        """
        self.issue_cache = issue_cache
        self.logger = logger or logging.getLogger("qa_agent")

    def check_hygiene(self) -> HygieneReport:
        """
        Run hygiene check on all cached issues.

        Returns:
            HygieneReport with issues needing attention
        """
        try:
            if not self.issue_cache.has_data:
                self.logger.warning("Cache empty for hygiene check")
                return HygieneReport(
                    generated_at=datetime.now(),
                    total_issues_checked=0,
                    issues_needing_attention=0,
                    has_valid_data=False,
                    error="GitHub data unavailable - cache empty"
                )

            # Get all issues from cache
            issues = self.issue_cache.get_issues()

            missing_labels = []
            missing_priority = []
            missing_assignee = []
            stale_issues = []

            for issue in issues:
                problems = []

                # Check for missing labels
                if not issue.labels or len(issue.labels) == 0:
                    problems.append("no labels")
                    missing_labels.append(self._create_hygiene_issue(issue, ["no labels"]))

                # Check for missing priority
                if not issue.priority:
                    problems.append("no priority")
                    missing_priority.append(self._create_hygiene_issue(issue, ["no priority"]))

                # Check for missing assignee
                if not issue.assignee:
                    problems.append("unassigned")
                    missing_assignee.append(self._create_hygiene_issue(issue, ["unassigned"]))

                # Check for stale issues
                if issue.is_stale:
                    problems.append("stale (14+ days)")
                    stale_issues.append(self._create_hygiene_issue(issue, ["stale (14+ days)"]))

            # Count unique issues needing attention
            issues_with_problems = set()
            for issue_list in [missing_labels, missing_priority, missing_assignee, stale_issues]:
                for hi in issue_list:
                    issues_with_problems.add(f"{hi.repo}#{hi.number}")

            report = HygieneReport(
                generated_at=datetime.now(),
                total_issues_checked=len(issues),
                issues_needing_attention=len(issues_with_problems),
                missing_labels=missing_labels,
                missing_priority=missing_priority,
                missing_assignee=missing_assignee,
                stale_issues=stale_issues,
                has_valid_data=True,
            )

            self.logger.info(
                f"Hygiene check: {report.issues_needing_attention}/{report.total_issues_checked} "
                f"issues need attention"
            )

            return report

        except Exception as e:
            self.logger.error(f"Failed to run hygiene check: {e}")
            return HygieneReport(
                generated_at=datetime.now(),
                total_issues_checked=0,
                issues_needing_attention=0,
                has_valid_data=False,
                error=str(e)
            )

    def _create_hygiene_issue(self, issue, problems: list[str]) -> HygieneIssue:
        """Create a HygieneIssue from a cache Issue."""
        return HygieneIssue(
            repo=issue.repo,
            number=issue.number,
            title=issue.title[:80] if issue.title else "Untitled",
            url=issue.url or f"https://github.com/cloudwarriors-ai/{issue.repo}/issues/{issue.number}",
            problems=problems,
        )

    def format_for_zoom(self, report: HygieneReport, max_per_category: int = 5) -> str:
        """
        Format hygiene report for Zoom Team Chat.

        Args:
            report: HygieneReport to format
            max_per_category: Max issues to list per category

        Returns:
            Formatted markdown string for Zoom
        """
        if not report.has_valid_data:
            return (
                f"Issue Hygiene Report - {report.generated_at.strftime('%B %d, %Y')}\n\n"
                f"Unable to generate report: {report.error or 'Data unavailable'}\n\n"
                "Please check GitHub connectivity and try again."
            )

        lines = [
            f"Issue Hygiene Report - {report.generated_at.strftime('%B %d, %Y')}",
            "",
            f"Checked {report.total_issues_checked} issues, "
            f"{report.issues_needing_attention} need attention",
            "",
        ]

        # Only add sections that have issues
        if report.missing_priority:
            lines.append(f"Missing Priority ({len(report.missing_priority)}):")
            for issue in report.missing_priority[:max_per_category]:
                lines.append(f"  - {issue.repo}#{issue.number}: {issue.title}")
            if len(report.missing_priority) > max_per_category:
                lines.append(f"  ... and {len(report.missing_priority) - max_per_category} more")
            lines.append("")

        if report.missing_assignee:
            lines.append(f"Unassigned ({len(report.missing_assignee)}):")
            for issue in report.missing_assignee[:max_per_category]:
                lines.append(f"  - {issue.repo}#{issue.number}: {issue.title}")
            if len(report.missing_assignee) > max_per_category:
                lines.append(f"  ... and {len(report.missing_assignee) - max_per_category} more")
            lines.append("")

        if report.stale_issues:
            lines.append(f"Stale Issues ({len(report.stale_issues)}):")
            for issue in report.stale_issues[:max_per_category]:
                lines.append(f"  - {issue.repo}#{issue.number}: {issue.title}")
            if len(report.stale_issues) > max_per_category:
                lines.append(f"  ... and {len(report.stale_issues) - max_per_category} more")
            lines.append("")

        if report.missing_labels:
            lines.append(f"Missing Labels ({len(report.missing_labels)}):")
            for issue in report.missing_labels[:max_per_category]:
                lines.append(f"  - {issue.repo}#{issue.number}: {issue.title}")
            if len(report.missing_labels) > max_per_category:
                lines.append(f"  ... and {len(report.missing_labels) - max_per_category} more")
            lines.append("")

        if report.issues_needing_attention == 0:
            lines.append("All issues are properly labeled and assigned!")
            lines.append("")

        lines.append("For details: 'show hygiene issues' or 'show unassigned'")

        return "\n".join(lines)
