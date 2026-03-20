"""
Intern feedback reminder service.

Generates weekly feedback reminders for active interns
to be sent to supervisors via Zoom Team Chat.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..repositories import InternRepository


@dataclass
class InternFeedbackItem:
    """Feedback reminder for a single intern."""

    intern_id: str
    name: str
    supervisor: Optional[str]
    program: Optional[str]
    days_active: int
    tasks_in_progress: int
    tasks_completed: int


@dataclass
class FeedbackReminder:
    """Weekly feedback reminder report."""

    generated_at: datetime
    total_interns: int
    interns: list[InternFeedbackItem] = field(default_factory=list)
    has_valid_data: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "total_interns": self.total_interns,
            "interns": [
                {
                    "intern_id": i.intern_id,
                    "name": i.name,
                    "supervisor": i.supervisor,
                    "program": i.program,
                    "days_active": i.days_active,
                    "tasks_in_progress": i.tasks_in_progress,
                    "tasks_completed": i.tasks_completed,
                }
                for i in self.interns
            ],
            "has_valid_data": self.has_valid_data,
            "error": self.error,
        }


class FeedbackService:
    """
    Service for generating intern feedback reminders.

    Creates weekly reminders for supervisors to provide
    feedback to their active interns.
    """

    def __init__(
        self,
        db_path: str,
        logger: logging.Logger = None
    ):
        """
        Initialize feedback service.

        Args:
            db_path: Path to SQLite database
            logger: Logger instance
        """
        self.db_path = db_path
        self.logger = logger or logging.getLogger("qa_agent")
        self.intern_repo = InternRepository(db_path=db_path, logger=self.logger)

    def generate_feedback_reminder(self) -> FeedbackReminder:
        """
        Generate weekly feedback reminder for active interns.

        Returns:
            FeedbackReminder with list of interns needing feedback
        """
        try:
            # Get all active interns with their tasks
            interns = self.intern_repo.get_all(
                status="active",
                include_tasks=True
            )

            # Also include onboarding interns (they need feedback too)
            onboarding = self.intern_repo.get_all(
                status="onboarding",
                include_tasks=True
            )
            interns.extend(onboarding)

            if not interns:
                return FeedbackReminder(
                    generated_at=datetime.now(),
                    total_interns=0,
                    has_valid_data=True,
                )

            feedback_items = []
            for intern in interns:
                # Calculate days since start
                days_active = 0
                if intern.get("start_date"):
                    try:
                        start = datetime.strptime(intern["start_date"], "%Y-%m-%d")
                        days_active = (datetime.now() - start).days
                    except ValueError:
                        pass

                tasks = intern.get("tasks", {})
                item = InternFeedbackItem(
                    intern_id=intern["id"],
                    name=intern["name"],
                    supervisor=intern.get("supervisor"),
                    program=intern.get("program"),
                    days_active=days_active,
                    tasks_in_progress=tasks.get("in_progress") or 0,
                    tasks_completed=tasks.get("completed") or 0,
                )
                feedback_items.append(item)

            reminder = FeedbackReminder(
                generated_at=datetime.now(),
                total_interns=len(feedback_items),
                interns=feedback_items,
                has_valid_data=True,
            )

            self.logger.info(f"Generated feedback reminder for {len(feedback_items)} interns")
            return reminder

        except Exception as e:
            self.logger.error(f"Failed to generate feedback reminder: {e}")
            return FeedbackReminder(
                generated_at=datetime.now(),
                total_interns=0,
                has_valid_data=False,
                error=str(e)
            )

    def format_for_zoom(self, reminder: FeedbackReminder) -> str:
        """
        Format feedback reminder for Zoom Team Chat.

        Args:
            reminder: FeedbackReminder to format

        Returns:
            Formatted markdown string for Zoom
        """
        if not reminder.has_valid_data:
            return (
                f"Weekly Feedback Reminder - {reminder.generated_at.strftime('%B %d, %Y')}\n\n"
                f"Unable to generate reminder: {reminder.error or 'Data unavailable'}\n\n"
                "Please check database connectivity."
            )

        if not reminder.interns:
            return (
                f"Weekly Feedback Reminder - {reminder.generated_at.strftime('%B %d, %Y')}\n\n"
                "No active interns require feedback this week."
            )

        lines = [
            f"Weekly Feedback Reminder - {reminder.generated_at.strftime('%B %d, %Y')}",
            "",
            f"Please provide feedback for the following {reminder.total_interns} intern(s):",
            "",
        ]

        # Group by supervisor if possible
        by_supervisor: dict[str, list[InternFeedbackItem]] = {}
        for intern in reminder.interns:
            supervisor = intern.supervisor or "Unassigned"
            if supervisor not in by_supervisor:
                by_supervisor[supervisor] = []
            by_supervisor[supervisor].append(intern)

        for supervisor, interns in sorted(by_supervisor.items()):
            if supervisor != "Unassigned":
                lines.append(f"**{supervisor}'s Team:**")
            else:
                lines.append("**Unassigned (need supervisor):**")

            for intern in interns:
                program_str = f" ({intern.program})" if intern.program else ""
                progress_str = f"{intern.tasks_completed} completed, {intern.tasks_in_progress} in progress"
                lines.append(f"  - {intern.name}{program_str}")
                lines.append(f"    Day {intern.days_active} | {progress_str}")

            lines.append("")

        lines.append("Feedback helps interns grow and ensures program success!")
        lines.append("")
        lines.append("For intern details: 'status [name]' or 'show intern tasks'")

        return "\n".join(lines)
