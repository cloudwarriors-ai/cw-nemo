"""
Workflow execution repository.

Handles database operations for n8n workflow execution tracking.
"""
import json
import sqlite3
from datetime import datetime
from typing import Optional
import logging


class WorkflowRepository:
    """
    Repository for workflow execution data access.

    Provides operations for tracking n8n workflow executions.
    """

    def __init__(
        self,
        db_path: str,
        logger: Optional[logging.Logger] = None
    ):
        self.db_path = db_path
        self.logger = logger or logging.getLogger(__name__)

    def get_by_id(self, execution_id: str) -> Optional[dict]:
        """
        Get a workflow execution by ID.

        Args:
            execution_id: Execution ID

        Returns:
            Execution record or None if not found
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, workflow_type, status, payload, context, result, error,
                       created_at, completed_at
                FROM workflow_executions
                WHERE id = ?
            """, (execution_id,))

            row = cursor.fetchone()
            conn.close()

            if row:
                result = dict(row)
                # Parse JSON fields
                for field in ['payload', 'context', 'result']:
                    if result.get(field):
                        try:
                            result[field] = json.loads(result[field])
                        except (json.JSONDecodeError, TypeError):
                            pass
                return result
            return None

        except Exception as e:
            self.logger.warning(f"Failed to get workflow execution: {e}")
            return None

    def get_recent(
        self,
        limit: int = 10,
        workflow_type: Optional[str] = None
    ) -> list[dict]:
        """
        Get recent workflow executions.

        Args:
            limit: Maximum number of executions to return
            workflow_type: Optional filter by workflow type

        Returns:
            List of execution records
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if workflow_type:
                cursor.execute("""
                    SELECT id, workflow_type, status, created_at, completed_at, result
                    FROM workflow_executions
                    WHERE workflow_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (workflow_type, limit))
            else:
                cursor.execute("""
                    SELECT id, workflow_type, status, created_at, completed_at, result
                    FROM workflow_executions
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))

            rows = cursor.fetchall()
            conn.close()

            return [dict(row) for row in rows]

        except Exception as e:
            self.logger.warning(f"Failed to get recent executions: {e}")
            return []

    def create(
        self,
        execution_id: str,
        workflow_type: str,
        payload: Optional[dict] = None,
        context: Optional[dict] = None
    ) -> bool:
        """
        Create a new workflow execution record.

        Args:
            execution_id: Unique execution ID
            workflow_type: Type of workflow (e.g., 'onboarding', 'feedback')
            payload: Optional payload data
            context: Optional context data

        Returns:
            True if created successfully
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            payload_json = json.dumps(payload) if payload else None
            context_json = json.dumps(context) if context else None

            cursor.execute("""
                INSERT INTO workflow_executions
                (id, workflow_type, status, payload, context)
                VALUES (?, ?, 'pending', ?, ?)
            """, (execution_id, workflow_type, payload_json, context_json))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            self.logger.error(f"Failed to create workflow execution: {e}")
            return False

    def update_status(
        self,
        execution_id: str,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None
    ) -> bool:
        """
        Update a workflow execution status.

        Args:
            execution_id: Execution ID to update
            status: New status ('pending', 'running', 'completed', 'failed')
            result: Optional result data
            error: Optional error message

        Returns:
            True if update succeeded
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            result_json = json.dumps(result) if result else None
            completed_at = datetime.now().isoformat() if status in ['completed', 'failed'] else None

            cursor.execute("""
                UPDATE workflow_executions
                SET status = ?, completed_at = ?, result = ?, error = ?
                WHERE id = ?
            """, (status, completed_at, result_json, error, execution_id))

            updated = cursor.rowcount > 0
            conn.commit()
            conn.close()

            return updated

        except Exception as e:
            self.logger.warning(f"Failed to update workflow execution: {e}")
            return False

    def cleanup_old(self, days: int = 30) -> int:
        """
        Delete old workflow executions.

        Args:
            days: Delete executions older than this many days

        Returns:
            Number of deleted records
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM workflow_executions
                WHERE created_at < datetime('now', ?)
            """, (f"-{days} days",))

            deleted = cursor.rowcount
            conn.commit()
            conn.close()

            if deleted > 0:
                self.logger.info(f"Cleaned up {deleted} old workflow executions")

            return deleted

        except Exception as e:
            self.logger.error(f"Failed to cleanup old executions: {e}")
            return 0
