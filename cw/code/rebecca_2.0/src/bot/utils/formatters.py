"""
Data formatting utilities.

Extracted from app.py during Phase 3 refactoring.
"""
from typing import Any


def get_repo_stats(issues: list) -> dict:
    """
    Calculate statistics for a list of issues.

    Handles both Issue objects (from cache) and raw dicts.

    Args:
        issues: List of Issue objects or dicts

    Returns:
        Dictionary with stats: total, open, high_priority, unassigned, stale
    """
    if not issues:
        return {
            "total": 0,
            "open": 0,
            "high_priority": 0,
            "unassigned": 0,
            "stale": 0
        }

    stats = {
        "total": len(issues),
        "open": 0,
        "high_priority": 0,
        "unassigned": 0,
        "stale": 0
    }

    for issue in issues:
        # Handle both Issue objects and dicts
        # Issue objects have 'repo' attribute, dicts don't
        if hasattr(issue, 'repo'):
            # Issue object - all issues from cache are open
            stats["open"] += 1
            if issue.priority and issue.priority.lower() == "high":
                stats["high_priority"] += 1
            if not issue.assignee:
                stats["unassigned"] += 1
            if issue.is_stale:
                stats["stale"] += 1
        else:
            # Dict (fallback)
            if issue.get("state") == "open":
                stats["open"] += 1
            if issue.get("priority", "").lower() == "high":
                stats["high_priority"] += 1
            if not issue.get("assignee"):
                stats["unassigned"] += 1

    return stats


def format_repo_info(repo_name: str, stats: dict, recent_issues: list) -> str:
    """
    Format repository information as a response string.

    Args:
        repo_name: Name of the repository
        stats: Statistics dictionary from get_repo_stats()
        recent_issues: List of recent Issue objects or dicts

    Returns:
        Formatted string for display
    """
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
            # Handle both Issue objects and dicts
            if hasattr(issue, 'repo'):
                title = issue.title or "Untitled"
                number = issue.number or "?"
            else:
                title = issue.get("title", "Untitled")
                number = issue.get("number", "?")
            lines.append(f"- #{number}: {title}")

    return "\n".join(lines)


def format_issue_summary(issue: Any) -> str:
    """
    Format a single issue as a summary line.

    Args:
        issue: Issue object or dict

    Returns:
        Formatted string like "- #123: Issue title (repo)"
    """
    if hasattr(issue, 'repo'):
        # Issue object
        repo = issue.repo or "unknown"
        number = issue.number or "?"
        title = issue.title or "Untitled"
        assignee = issue.assignee or "unassigned"
    else:
        # Dict
        repo = issue.get("repo", "unknown")
        number = issue.get("number", "?")
        title = issue.get("title", "Untitled")
        assignee = issue.get("assignee") or "unassigned"

    return f"- #{number}: {title} ({repo}) - {assignee}"
