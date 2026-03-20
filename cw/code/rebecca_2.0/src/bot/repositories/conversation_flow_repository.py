"""
Conversation flow repository.

Handles database operations for multi-turn conversation flows
(onboarding, offboarding, etc.).

Security Note:
    Uses explicit UPDATE statements to avoid dynamic SQL construction.
    All values use parameterized queries for SQL injection protection.
"""
import json
import sqlite3
from datetime import datetime
from typing import Optional
import logging


class ConversationFlowRepository:
    """
    Repository for conversation flow data access.

    Provides operations for multi-turn conversation flows with
    proper SQL injection protection.
    """

    def __init__(
        self,
        db_path: str,
        logger: Optional[logging.Logger] = None
    ):
        self.db_path = db_path
        self.logger = logger or logging.getLogger(__name__)

    def create(
        self,
        flow_id: str,
        user_id: str,
        flow_type: str,
        channel_id: Optional[str] = None,
        expires_minutes: int = 10
    ) -> bool:
        """
        Create a new conversation flow.

        Args:
            flow_id: Unique flow identifier
            user_id: User who started the flow
            flow_type: Type of flow (onboarding, offboarding)
            channel_id: Channel where flow was started
            expires_minutes: Minutes until flow expires

        Returns:
            True if created successfully
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO conversation_flows (id, user_id, channel_id, flow_type, collected_data, expires_at)
                VALUES (?, ?, ?, ?, '{}', datetime('now', ?))
            """, (flow_id, user_id, channel_id, flow_type, f"+{expires_minutes} minutes"))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            self.logger.error(f"Failed to create conversation flow: {e}")
            return False

    def get_active(self, user_id: str) -> Optional[dict]:
        """
        Get active conversation flow for a user.

        Args:
            user_id: User ID

        Returns:
            Flow record or None if no active flow
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM conversation_flows
                WHERE user_id = ?
                AND expires_at > datetime('now')
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id,))

            row = cursor.fetchone()
            conn.close()

            if row:
                flow = dict(row)
                # Parse collected_data JSON
                try:
                    flow["collected_data"] = json.loads(flow["collected_data"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    flow["collected_data"] = {}
                return flow
            return None

        except Exception as e:
            self.logger.warning(f"Failed to get active flow: {e}")
            return None

    def get_by_id(self, flow_id: str) -> Optional[dict]:
        """
        Get a flow by ID.

        Args:
            flow_id: Flow identifier

        Returns:
            Flow record or None
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM conversation_flows WHERE id = ?",
                (flow_id,)
            )

            row = cursor.fetchone()
            conn.close()

            if row:
                flow = dict(row)
                try:
                    flow["collected_data"] = json.loads(flow["collected_data"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    flow["collected_data"] = {}
                return flow
            return None

        except Exception as e:
            self.logger.warning(f"Failed to get flow by id: {e}")
            return None

    def update(
        self,
        flow_id: str,
        current_step: Optional[int] = None,
        collected_data: Optional[dict] = None
    ) -> bool:
        """
        Update a conversation flow's progress.

        Args:
            flow_id: Flow identifier
            current_step: New step number
            collected_data: Updated collected data dict

        Returns:
            True if successful

        Security:
            Uses explicit UPDATE statements to avoid dynamic SQL construction.
            All values use parameterized queries for SQL injection protection.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # SECURITY: Use explicit statements - no dynamic SQL construction
            if current_step is not None and collected_data is not None:
                cursor.execute(
                    "UPDATE conversation_flows SET current_step = ?, collected_data = ? WHERE id = ?",
                    (current_step, json.dumps(collected_data), flow_id)
                )
            elif current_step is not None:
                cursor.execute(
                    "UPDATE conversation_flows SET current_step = ? WHERE id = ?",
                    (current_step, flow_id)
                )
            elif collected_data is not None:
                cursor.execute(
                    "UPDATE conversation_flows SET collected_data = ? WHERE id = ?",
                    (json.dumps(collected_data), flow_id)
                )
            else:
                conn.close()
                return True

            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return success

        except Exception as e:
            self.logger.error(f"Failed to update conversation flow: {e}")
            return False

    def delete(self, flow_id: str) -> bool:
        """
        Delete a conversation flow (on completion or cancellation).

        Args:
            flow_id: Flow identifier

        Returns:
            True if deleted successfully
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM conversation_flows WHERE id = ?", (flow_id,))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            self.logger.error(f"Failed to delete conversation flow: {e}")
            return False

    def cleanup_expired(self) -> int:
        """
        Delete expired conversation flows.

        Should be called periodically to clean up stale flows.

        Returns:
            Number of flows deleted
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM conversation_flows
                WHERE expires_at < datetime('now')
            """)

            deleted = cursor.rowcount
            conn.commit()
            conn.close()

            if deleted > 0:
                self.logger.debug(f"Cleaned up {deleted} expired conversation flows")

            return deleted

        except Exception as e:
            self.logger.error(f"Failed to cleanup expired flows: {e}")
            return 0

    def extend_expiry(self, flow_id: str, minutes: int = 10) -> bool:
        """
        Extend the expiry time of a flow.

        Args:
            flow_id: Flow identifier
            minutes: Minutes to extend by

        Returns:
            True if extended successfully
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE conversation_flows
                SET expires_at = datetime('now', ?)
                WHERE id = ?
            """, (f"+{minutes} minutes", flow_id))

            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return success

        except Exception as e:
            self.logger.warning(f"Failed to extend flow expiry: {e}")
            return False
