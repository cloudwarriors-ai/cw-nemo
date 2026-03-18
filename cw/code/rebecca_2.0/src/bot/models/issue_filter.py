"""
Issue filter dataclass for cache queries.

Encapsulates filter parameters for cleaner API.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IssueFilter:
    """
    Filter parameters for issue cache queries.

    Encapsulates all possible filter options for cleaner method signatures
    and easier extension.

    Attributes:
        repo: Filter to specific repository name
        assignee: Filter to specific assignee username
        priority: Filter to specific priority level (e.g., "high", "medium", "low")
        stale_only: Only return issues that haven't been updated in 14+ days
        unassigned_only: Only return issues without an assignee
        assigned_only: Only return issues with an assignee
        hygiene_issues_only: Only return issues missing required fields
        labels: Filter to issues with specific labels
        limit: Maximum number of issues to return
    """

    repo: Optional[str] = None
    assignee: Optional[str] = None
    priority: Optional[str] = None
    stale_only: bool = False
    unassigned_only: bool = False
    assigned_only: bool = False
    hygiene_issues_only: bool = False
    labels: Optional[list[str]] = None
    limit: Optional[int] = None

    def __post_init__(self):
        """Validate filter consistency."""
        if self.unassigned_only and self.assigned_only:
            raise ValueError("Cannot set both unassigned_only and assigned_only")

    @classmethod
    def high_priority(cls, repo: Optional[str] = None) -> "IssueFilter":
        """Create a filter for high priority issues."""
        return cls(repo=repo, priority="high")

    @classmethod
    def unassigned(cls, repo: Optional[str] = None) -> "IssueFilter":
        """Create a filter for unassigned issues."""
        return cls(repo=repo, unassigned_only=True)

    @classmethod
    def stale(cls, repo: Optional[str] = None) -> "IssueFilter":
        """Create a filter for stale issues."""
        return cls(repo=repo, stale_only=True)

    @classmethod
    def for_repo(cls, repo: str) -> "IssueFilter":
        """Create a filter for a specific repository."""
        return cls(repo=repo)

    @classmethod
    def for_assignee(cls, assignee: str) -> "IssueFilter":
        """Create a filter for a specific assignee."""
        return cls(assignee=assignee)

    @classmethod
    def hygiene(cls, repo: Optional[str] = None) -> "IssueFilter":
        """Create a filter for issues with hygiene problems."""
        return cls(repo=repo, hygiene_issues_only=True)

    @classmethod
    def none(cls) -> "IssueFilter":
        """Create an empty filter (returns all issues)."""
        return cls()

    def is_empty(self) -> bool:
        """Check if no filters are applied."""
        return (
            self.repo is None
            and self.assignee is None
            and self.priority is None
            and not self.stale_only
            and not self.unassigned_only
            and not self.assigned_only
            and not self.hygiene_issues_only
            and self.labels is None
        )

    def to_sql_conditions(self) -> tuple[str, list]:
        """
        Convert filter to SQL WHERE clause conditions.

        Returns:
            Tuple of (where_clause, params)
        """
        conditions = []
        params = []

        if self.repo:
            conditions.append("LOWER(repo) = LOWER(?)")
            params.append(self.repo)

        if self.assignee:
            conditions.append("LOWER(assignee) = LOWER(?)")
            params.append(self.assignee)

        if self.priority:
            conditions.append("LOWER(priority) = LOWER(?)")
            params.append(self.priority)

        if self.stale_only:
            conditions.append("is_stale = 1")

        if self.unassigned_only:
            conditions.append("(assignee IS NULL OR assignee = '')")

        if self.assigned_only:
            conditions.append("assignee IS NOT NULL AND assignee != ''")

        if self.hygiene_issues_only:
            conditions.append("((assignee IS NULL OR assignee = '') OR (priority IS NULL OR priority = ''))")

        if conditions:
            return " AND ".join(conditions), params
        return "1=1", []
