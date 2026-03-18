"""
Tests for FeedbackService.

Tests intern feedback reminder generation and formatting for Zoom.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from src.bot.services.feedback_service import FeedbackService, FeedbackReminder, InternFeedbackItem


class TestFeedbackReminder:
    """Tests for FeedbackReminder dataclass."""

    def test_to_dict_with_interns(self):
        """Test FeedbackReminder serialization with interns."""
        reminder = FeedbackReminder(
            generated_at=datetime(2024, 1, 19, 14, 0, 0),
            total_interns=2,
            interns=[
                InternFeedbackItem(
                    intern_id="intern-1",
                    name="Alice Smith",
                    supervisor="Chad",
                    program="SkillBridge",
                    days_active=30,
                    tasks_in_progress=2,
                    tasks_completed=5,
                ),
                InternFeedbackItem(
                    intern_id="intern-2",
                    name="Bob Jones",
                    supervisor="Chad",
                    program="Vanderbilt",
                    days_active=15,
                    tasks_in_progress=1,
                    tasks_completed=2,
                ),
            ],
            has_valid_data=True,
        )

        result = reminder.to_dict()

        assert result["generated_at"] == "2024-01-19T14:00:00"
        assert result["total_interns"] == 2
        assert len(result["interns"]) == 2
        assert result["interns"][0]["name"] == "Alice Smith"
        assert result["interns"][0]["days_active"] == 30
        assert result["has_valid_data"] is True

    def test_to_dict_with_error(self):
        """Test FeedbackReminder serialization with error state."""
        reminder = FeedbackReminder(
            generated_at=datetime(2024, 1, 19, 14, 0, 0),
            total_interns=0,
            has_valid_data=False,
            error="Database unavailable",
        )

        result = reminder.to_dict()

        assert result["has_valid_data"] is False
        assert result["error"] == "Database unavailable"
        assert result["interns"] == []


class TestFeedbackService:
    """Tests for FeedbackService."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database with test data."""
        db_path = str(tmp_path / "test.db")

        from src.bot.database import init_db, add_intern, assign_task, update_task_status

        init_db(db_path)

        # Add active intern with tasks
        add_intern(
            db_path=db_path,
            intern_id="intern-1",
            name="Alice Smith",
            program="SkillBridge",
            supervisor="Chad",
            start_date=(datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
        )

        # Update status to active
        from src.bot.database import update_intern_status
        update_intern_status(db_path, "intern-1", "active")

        # Add some tasks
        assign_task(db_path, "task-1", "intern-1", "Task 1")
        assign_task(db_path, "task-2", "intern-1", "Task 2")
        update_task_status(db_path, "task-1", "completed")
        update_task_status(db_path, "task-2", "in_progress")

        # Add onboarding intern
        add_intern(
            db_path=db_path,
            intern_id="intern-2",
            name="Bob Jones",
            program="Vanderbilt",
            supervisor="Trent",
            start_date=(datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
        )
        # Status defaults to 'onboarding'

        return db_path

    @pytest.fixture
    def feedback_service(self, temp_db):
        """Create a FeedbackService instance."""
        return FeedbackService(db_path=temp_db)

    def test_generate_feedback_reminder_success(self, feedback_service):
        """Test successful feedback reminder generation."""
        reminder = feedback_service.generate_feedback_reminder()

        assert reminder.has_valid_data is True
        assert reminder.total_interns == 2
        assert len(reminder.interns) == 2

        # Check Alice (active)
        alice = next(i for i in reminder.interns if i.name == "Alice Smith")
        assert alice.supervisor == "Chad"
        assert alice.program == "SkillBridge"
        assert alice.days_active >= 29  # Approximately 30 days
        assert alice.tasks_completed == 1
        assert alice.tasks_in_progress == 1

        # Check Bob (onboarding)
        bob = next(i for i in reminder.interns if i.name == "Bob Jones")
        assert bob.supervisor == "Trent"
        assert bob.days_active >= 6  # Approximately 7 days

    def test_generate_feedback_reminder_no_interns(self, tmp_path):
        """Test reminder generation when no active interns exist."""
        db_path = str(tmp_path / "empty.db")
        from src.bot.database import init_db
        init_db(db_path)

        service = FeedbackService(db_path=db_path)
        reminder = service.generate_feedback_reminder()

        assert reminder.has_valid_data is True
        assert reminder.total_interns == 0
        assert len(reminder.interns) == 0

    def test_generate_feedback_reminder_exception(self, feedback_service):
        """Test reminder generation handles exceptions gracefully."""
        with patch('src.bot.services.feedback_service.get_all_interns') as mock:
            mock.side_effect = Exception("Database error")

            reminder = feedback_service.generate_feedback_reminder()

            assert reminder.has_valid_data is False
            assert "Database error" in reminder.error

    def test_format_for_zoom_with_interns(self, feedback_service):
        """Test formatting a reminder with interns for Zoom."""
        reminder = FeedbackReminder(
            generated_at=datetime(2024, 1, 19, 14, 0, 0),
            total_interns=2,
            interns=[
                InternFeedbackItem(
                    intern_id="intern-1",
                    name="Alice Smith",
                    supervisor="Chad",
                    program="SkillBridge",
                    days_active=30,
                    tasks_in_progress=2,
                    tasks_completed=5,
                ),
                InternFeedbackItem(
                    intern_id="intern-2",
                    name="Bob Jones",
                    supervisor="Trent",
                    program="Vanderbilt",
                    days_active=15,
                    tasks_in_progress=1,
                    tasks_completed=2,
                ),
            ],
            has_valid_data=True,
        )

        formatted = feedback_service.format_for_zoom(reminder)

        assert "Weekly Feedback Reminder - January 19, 2024" in formatted
        assert "2 intern(s)" in formatted
        assert "Chad's Team:" in formatted
        assert "Alice Smith (SkillBridge)" in formatted
        assert "Day 30" in formatted
        assert "5 completed, 2 in progress" in formatted
        assert "Trent's Team:" in formatted
        assert "Bob Jones (Vanderbilt)" in formatted

    def test_format_for_zoom_no_interns(self, feedback_service):
        """Test formatting when no interns need feedback."""
        reminder = FeedbackReminder(
            generated_at=datetime(2024, 1, 19, 14, 0, 0),
            total_interns=0,
            interns=[],
            has_valid_data=True,
        )

        formatted = feedback_service.format_for_zoom(reminder)

        assert "No active interns require feedback this week" in formatted

    def test_format_for_zoom_invalid_reminder(self, feedback_service):
        """Test formatting an invalid reminder shows error message."""
        reminder = FeedbackReminder(
            generated_at=datetime(2024, 1, 19, 14, 0, 0),
            total_interns=0,
            has_valid_data=False,
            error="Database unavailable",
        )

        formatted = feedback_service.format_for_zoom(reminder)

        assert "Unable to generate reminder: Database unavailable" in formatted

    def test_format_for_zoom_unassigned_supervisor(self, feedback_service):
        """Test formatting when intern has no supervisor."""
        reminder = FeedbackReminder(
            generated_at=datetime(2024, 1, 19, 14, 0, 0),
            total_interns=1,
            interns=[
                InternFeedbackItem(
                    intern_id="intern-1",
                    name="Jane Doe",
                    supervisor=None,
                    program="SkillBridge",
                    days_active=10,
                    tasks_in_progress=1,
                    tasks_completed=0,
                ),
            ],
            has_valid_data=True,
        )

        formatted = feedback_service.format_for_zoom(reminder)

        assert "Unassigned (need supervisor):" in formatted
        assert "Jane Doe (SkillBridge)" in formatted
