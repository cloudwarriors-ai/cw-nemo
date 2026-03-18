"""
Intern repository.

Handles all database operations related to interns.
"""

import sqlite3
from datetime import datetime
from typing import Optional
import logging


class InternRepository:
    """
    Repository for intern data access.

    Provides CRUD operations for interns and their tasks.
    """

    def __init__(
        self,
        db_path: str,
        logger: Optional[logging.Logger] = None
    ):
        self.db_path = db_path
        self.logger = logger or logging.getLogger(__name__)

    def get_by_id(self, intern_id: str) -> Optional[dict]:
        """
        Get intern by ID.

        Args:
            intern_id: The intern's unique identifier

        Returns:
            Intern dict or None if not found
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM interns WHERE id = ?",
                (intern_id,)
            )
            row = cursor.fetchone()
            conn.close()

            return dict(row) if row else None

        except Exception as e:
            self.logger.warning(f"Failed to get intern by id: {e}")
            return None

    def get_by_name(self, name: str) -> Optional[dict]:
        """
        Get intern by name (case-insensitive partial match).

        Args:
            name: Name to search for

        Returns:
            Intern dict or None if not found
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM interns WHERE LOWER(name) LIKE LOWER(?)",
                (f"%{name}%",)
            )
            row = cursor.fetchone()
            conn.close()

            return dict(row) if row else None

        except Exception as e:
            self.logger.warning(f"Failed to get intern by name: {e}")
            return None

    def get_all(
        self,
        status: Optional[str] = None,
        include_tasks: bool = False
    ) -> list[dict]:
        """
        Get all interns with optional filters.

        Args:
            status: Filter by status
            include_tasks: Include task counts

        Returns:
            List of intern dicts
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if status:
                cursor.execute(
                    "SELECT * FROM interns WHERE status = ? ORDER BY start_date DESC",
                    (status,)
                )
            else:
                cursor.execute("SELECT * FROM interns ORDER BY start_date DESC")

            rows = cursor.fetchall()
            interns = [dict(row) for row in rows]

            if include_tasks:
                for intern in interns:
                    cursor.execute(
                        "SELECT COUNT(*) FROM tasks WHERE intern_id = ?",
                        (intern["id"],)
                    )
                    intern["task_count"] = cursor.fetchone()[0]

            conn.close()
            return interns

        except Exception as e:
            self.logger.warning(f"Failed to get all interns: {e}")
            return []

    def check_duplicate(self, name: str, email: str) -> list[dict]:
        """
        Check for existing interns with matching name or email.

        Used before onboarding to prevent duplicates.

        Args:
            name: Intern name to check
            email: Email address to check

        Returns:
            List of potential duplicate intern records
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM interns
                WHERE LOWER(name) = LOWER(?)
                   OR LOWER(email) = LOWER(?)
                ORDER BY created_at DESC
            """, (name, email))

            duplicates = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return duplicates

        except Exception as e:
            self.logger.warning(f"Failed to check for duplicate intern: {e}")
            return []

    def create(
        self,
        intern_id: str,
        name: str,
        program: str = "other",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        supervisor: Optional[str] = None,
        email: Optional[str] = None,
        notes: Optional[str] = None
    ) -> bool:
        """
        Create a new intern.

        Args:
            intern_id: Unique identifier
            name: Full name
            program: Program type (skillbridge, vanderbilt, other)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            supervisor: Supervisor name
            email: Email address
            notes: Additional notes

        Returns:
            True if created successfully
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO interns
                (id, name, email, status, program, supervisor, start_date, end_date, created_at, notes)
                VALUES (?, ?, ?, 'onboarding', ?, ?, ?, ?, ?, ?)
            """, (
                intern_id,
                name,
                email,
                program,
                supervisor,
                start_date,
                end_date,
                datetime.now().isoformat(),
                notes
            ))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            self.logger.error(f"Failed to create intern: {e}")
            return False

    def update_status(
        self,
        intern_id: str,
        status: str,
        notes: Optional[str] = None
    ) -> bool:
        """
        Update intern status.

        Args:
            intern_id: Intern identifier
            status: New status
            notes: Optional notes to append

        Returns:
            True if updated successfully
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if notes:
                cursor.execute("""
                    UPDATE interns
                    SET status = ?, updated_at = ?, notes = COALESCE(notes || '\n', '') || ?
                    WHERE id = ?
                """, (status, datetime.now().isoformat(), notes, intern_id))
            else:
                cursor.execute("""
                    UPDATE interns
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                """, (status, datetime.now().isoformat(), intern_id))

            updated = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return updated

        except Exception as e:
            self.logger.error(f"Failed to update intern status: {e}")
            return False

    def get_ending_soon(self, days: int = 7) -> list[dict]:
        """
        Get interns whose end date is within the specified days.

        Args:
            days: Number of days to look ahead

        Returns:
            List of intern dicts
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM interns
                WHERE end_date IS NOT NULL
                AND date(end_date) <= date('now', ?)
                AND date(end_date) >= date('now')
                AND status NOT IN ('completed', 'graduated')
                ORDER BY end_date ASC
            """, (f"+{days} days",))

            rows = cursor.fetchall()
            conn.close()

            return [dict(row) for row in rows]

        except Exception as e:
            self.logger.warning(f"Failed to get interns ending soon: {e}")
            return []

    def get_tasks(
        self,
        intern_id: str,
        status: Optional[str] = None,
        since: Optional[str] = None
    ) -> list[dict]:
        """
        Get tasks for an intern.

        Args:
            intern_id: Intern identifier
            status: Filter by task status
            since: Filter by creation date (YYYY-MM-DD)

        Returns:
            List of task dicts
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT * FROM tasks WHERE intern_id = ?"
            params = [intern_id]

            if status:
                query += " AND status = ?"
                params.append(status)

            if since:
                query += " AND assigned_at >= ?"
                params.append(since)

            query += " ORDER BY assigned_at DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()

            return [dict(row) for row in rows]

        except Exception as e:
            self.logger.warning(f"Failed to get intern tasks: {e}")
            return []

    def add_task(
        self,
        intern_id: str,
        title: str,
        github_issue: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[str]:
        """
        Add a task for an intern.

        Args:
            intern_id: Intern identifier
            title: Task title
            github_issue: GitHub issue reference (e.g., "repo#123")
            description: Task description

        Returns:
            Task ID if created, None otherwise
        """
        import uuid

        try:
            task_id = str(uuid.uuid4())[:8]
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO tasks
                (id, intern_id, title, github_issue, description)
                VALUES (?, ?, ?, ?, ?)
            """, (
                task_id,
                intern_id,
                title,
                github_issue,
                description
            ))

            conn.commit()
            conn.close()
            return task_id

        except Exception as e:
            self.logger.error(f"Failed to add task: {e}")
            return None

    def update_task_status(
        self,
        task_id: str,
        status: str,
        notes: Optional[str] = None
    ) -> bool:
        """
        Update task status.

        Args:
            task_id: Task identifier
            status: New status (assigned, in_progress, completed, blocked)
            notes: Optional notes

        Returns:
            True if updated successfully
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            completed_at = datetime.now().isoformat() if status == "completed" else None

            cursor.execute("""
                UPDATE tasks
                SET status = ?, completed_at = ?, notes = COALESCE(?, notes)
                WHERE id = ?
            """, (status, completed_at, notes, task_id))

            updated = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return updated

        except Exception as e:
            self.logger.error(f"Failed to update task status: {e}")
            return False
