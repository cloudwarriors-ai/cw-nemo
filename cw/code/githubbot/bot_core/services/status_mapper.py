"""
Status mapping between GitHub and Project Pulse.

Maps GitHub issue state and labels to Project Pulse ticket status.

Status Mapping:
| GitHub State/Label      | Project Pulse Status |
|------------------------|---------------------|
| Open issue, no labels  | Open                |
| `in-progress` label    | In Progress         |
| `waiting-review` label | In Progress         |
| Issue closed           | Closed              |
"""
from enum import Enum
from typing import List, Dict, Any, Optional


class ProjectPulseStatus(str, Enum):
    """Project Pulse ticket status values."""
    OPEN = 'Open'
    IN_PROGRESS = 'In Progress'
    CLOSED = 'Closed'


# GitHub labels that indicate "In Progress" status
IN_PROGRESS_LABELS = {
    'in-progress',
    'in progress',
    'wip',
    'work-in-progress',
    'working',
}

# GitHub labels that indicate "In Progress" but waiting for review
WAITING_REVIEW_LABELS = {
    'waiting-review',
    'waiting-for-review',
    'needs-review',
    'review-needed',
    'pending-review',
}


def github_to_project_pulse_status(
    labels: List[Dict[str, Any]],
    state: str,
    action: Optional[str] = None
) -> ProjectPulseStatus:
    """
    Map GitHub issue state/labels to Project Pulse status.

    Args:
        labels: List of GitHub label objects (each with 'name' key)
        state: GitHub issue state ('open' or 'closed')
        action: Optional GitHub action (e.g., 'closed', 'reopened')

    Returns:
        ProjectPulseStatus enum value

    Examples:
        >>> github_to_project_pulse_status([], 'open')
        ProjectPulseStatus.OPEN

        >>> github_to_project_pulse_status([{'name': 'in-progress'}], 'open')
        ProjectPulseStatus.IN_PROGRESS

        >>> github_to_project_pulse_status([], 'closed')
        ProjectPulseStatus.CLOSED
    """
    # If issue is closed, status is always Closed
    if state == 'closed':
        return ProjectPulseStatus.CLOSED

    # If action is 'reopened', treat as Open (unless labels indicate otherwise)
    # This handles the case where a closed issue is reopened

    # Extract label names (lowercase for case-insensitive matching)
    label_names = set()
    for label in labels:
        if isinstance(label, dict):
            name = label.get('name', '').lower().strip()
        else:
            name = str(label).lower().strip()
        if name:
            label_names.add(name)

    # Check for in-progress labels
    if label_names & IN_PROGRESS_LABELS:
        return ProjectPulseStatus.IN_PROGRESS

    # Check for waiting-review labels (also maps to In Progress)
    if label_names & WAITING_REVIEW_LABELS:
        return ProjectPulseStatus.IN_PROGRESS

    # Default: Open
    return ProjectPulseStatus.OPEN


def should_notify_project_pulse(
    event_type: str,
    action: str,
    labels: List[Dict[str, Any]] = None
) -> bool:
    """
    Determine if a GitHub event should trigger a Project Pulse update.

    Args:
        event_type: GitHub event type ('issues')
        action: GitHub action (e.g., 'opened', 'closed', 'labeled', 'assigned')
        labels: Optional list of labels involved

    Returns:
        True if this event should trigger a Project Pulse update
    """
    if event_type != 'issues':
        return False

    # Actions that should trigger updates
    trigger_actions = {
        'opened',
        'closed',
        'reopened',
        'labeled',
        'unlabeled',
        'assigned',
        'unassigned',
    }

    return action in trigger_actions


def extract_assignees(issue_data: Dict[str, Any]) -> List[str]:
    """
    Extract assignee usernames from GitHub issue data.

    Args:
        issue_data: GitHub issue object

    Returns:
        List of assignee login names
    """
    assignees = issue_data.get('assignees', [])
    return [a.get('login', '') for a in assignees if a.get('login')]


def format_status_update_message(
    old_status: Optional[ProjectPulseStatus],
    new_status: ProjectPulseStatus,
    action: str,
    actor: str
) -> str:
    """
    Format a human-readable status update message.

    Args:
        old_status: Previous status (or None if new)
        new_status: New status
        action: GitHub action that triggered the update
        actor: GitHub username who performed the action

    Returns:
        Formatted message string
    """
    action_messages = {
        'opened': f"Issue opened by {actor}",
        'closed': f"Issue closed by {actor}",
        'reopened': f"Issue reopened by {actor}",
        'labeled': f"Label added by {actor}",
        'unlabeled': f"Label removed by {actor}",
        'assigned': f"Assigned by {actor}",
        'unassigned': f"Unassigned by {actor}",
    }

    base_message = action_messages.get(action, f"Updated by {actor}")

    if old_status and old_status != new_status:
        return f"{base_message} - Status changed from {old_status.value} to {new_status.value}"

    return base_message
