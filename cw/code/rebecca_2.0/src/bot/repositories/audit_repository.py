"""
Audit log repository.

Handles database operations for compliance audit logging.
"""
import sqlite3
from typing import Optional
import logging


class AuditRepository:
    """
    Repository for audit log data access.

    Provides operations for compliance audit tracking.
    """

    def __init__(
        self,
        db_path: str,
        logger: Optional[logging.Logger] = None
    ):
        self.db_path = db_path
        self.logger = logger or logging.getLogger(__name__)

    def log_event(
        self,
        action: str,
        actor_user_id: str,
        target_id: Optional[str] = None,
        target_name: Optional[str] = None,
        actor_name: Optional[str] = None,
        details: Optional[str] = None
    ) -> bool:
        """
        Log an audit event for compliance tracking.

        Args:
            action: Action type (onboard, offboard, etc.)
            actor_user_id: User who performed the action
            target_id: ID of the target (e.g., intern_id)
            target_name: Name of the target (e.g., intern name)
            actor_name: Name of the actor
            details: Additional details (JSON or text)

        Returns:
            True if logged successfully
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO audit_log (action, target_id, target_name, actor_user_id, actor_name, details)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (action, target_id, target_name, actor_user_id, actor_name, details))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            self.logger.error(f"Failed to log audit event: {e}")
            return False

    def get_log(
        self,
        action: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        target_id: Optional[str] = None,
        limit: int = 50
    ) -> list[dict]:
        """
        Get audit log entries with optional filters.

        Args:
            action: Filter by action type
            actor_user_id: Filter by actor
            target_id: Filter by target
            limit: Maximum entries to return

        Returns:
            List of audit log entries
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT * FROM audit_log WHERE 1=1"
            params = []

            if action:
                query += " AND action = ?"
                params.append(action)

            if actor_user_id:
                query += " AND actor_user_id = ?"
                params.append(actor_user_id)

            if target_id:
                query += " AND target_id = ?"
                params.append(target_id)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            entries = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return entries

        except Exception as e:
            self.logger.warning(f"Failed to get audit log: {e}")
            return []

    def get_by_target(self, target_id: str, limit: int = 20) -> list[dict]:
        """
        Get audit entries for a specific target.

        Args:
            target_id: Target ID to filter by
            limit: Maximum entries to return

        Returns:
            List of audit log entries for the target
        """
        return self.get_log(target_id=target_id, limit=limit)

    def get_by_actor(self, actor_user_id: str, limit: int = 20) -> list[dict]:
        """
        Get audit entries by a specific actor.

        Args:
            actor_user_id: Actor user ID to filter by
            limit: Maximum entries to return

        Returns:
            List of audit log entries by the actor
        """
        return self.get_log(actor_user_id=actor_user_id, limit=limit)

    def get_recent(self, limit: int = 50) -> list[dict]:
        """
        Get recent audit log entries.

        Args:
            limit: Maximum entries to return

        Returns:
            List of recent audit log entries
        """
        return self.get_log(limit=limit)
