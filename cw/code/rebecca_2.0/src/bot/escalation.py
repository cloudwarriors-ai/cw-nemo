"""
Escalation manager for routing requests to humans.

Handles cases where the bot can't help or judgment is required.
"""
import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

from ..zoom_notifier import ZoomNotifier


class EscalationManager:
    """
    Manage escalations from bot to human contacts.

    Tracks escalation history and notifies appropriate contacts.

    Note: Sensitive topic detection is handled by QueryParser with proper
    word boundaries. This class handles explicit escalation requests and
    frustrated user detection only.
    """

    def __init__(
        self,
        zoom_notifier: Optional[ZoomNotifier] = None,
        default_contact: str = "@team",
        db_path: str = "data/state.db",
        logger: logging.Logger = None
    ):
        """
        Initialize the escalation manager.

        Args:
            zoom_notifier: ZoomNotifier for sending escalation messages
            default_contact: Default Zoom mention for escalations
            db_path: Path to SQLite database for tracking
            logger: Logger instance
        """
        self.zoom_notifier = zoom_notifier
        self.default_contact = default_contact
        self.db_path = db_path
        self.logger = logger or logging.getLogger("qa_agent")

    def should_escalate(
        self,
        query: str,
        confidence: float = 1.0,
        failed_attempts: int = 0
    ) -> bool:
        """
        Determine if a query should be escalated to a human.

        Args:
            query: The user's query text
            confidence: Parser confidence (0-1)
            failed_attempts: Number of failed query attempts by this user

        Returns:
            True if should escalate, False otherwise
        """
        query_lower = query.lower()

        # Explicit escalation request
        if any(word in query_lower for word in ["escalate", "human", "person", "help me"]):
            return True

        # User is frustrated (multiple failed attempts)
        if failed_attempts >= 3:
            return True

        # Note: Sensitive topic detection is handled by QueryParser with proper
        # word boundaries, which returns QueryType.ESCALATE. Don't duplicate
        # that logic here to avoid inconsistency.

        return False

    def escalate(
        self,
        user_id: str,
        user_name: str,
        topic: str,
        channel_id: str = None,
        context: dict = None
    ) -> str:
        """
        Create an escalation and notify the appropriate human.

        Args:
            user_id: ID of the user requesting escalation
            user_name: Display name of the user
            topic: What they need help with
            channel_id: Zoom channel where request originated
            context: Additional context (recent queries, etc.)

        Returns:
            Acknowledgment message to show the user
        """
        escalation_id = str(uuid.uuid4())[:8]

        # Log the escalation
        self.logger.info(
            f"Escalation {escalation_id}: user={user_name}, topic={topic[:50]}..."
        )

        # Store in database
        self._store_escalation(
            escalation_id=escalation_id,
            user_id=user_id,
            user_name=user_name,
            topic=topic,
            channel_id=channel_id,
            context=context
        )

        # Notify human contact
        if self.zoom_notifier:
            notification = self._format_notification(
                escalation_id=escalation_id,
                user_name=user_name,
                topic=topic,
                context=context
            )
            self.zoom_notifier.send(notification)

        # Return acknowledgment for user
        return self._format_acknowledgment(escalation_id)

    def _format_notification(
        self,
        escalation_id: str,
        user_name: str,
        topic: str,
        context: dict = None
    ) -> str:
        """Format escalation notification for human contact."""
        lines = [
            f"{self.default_contact} Escalation Request",
            "",
            f"**ID:** {escalation_id}",
            f"**From:** {user_name}",
            f"**Topic:** {topic}",
        ]

        if context:
            if context.get("recent_queries"):
                lines.append("")
                lines.append("**Recent queries:**")
                for q in context["recent_queries"][-3:]:
                    lines.append(f"- {q}")

        lines.append("")
        lines.append("Please follow up with this user.")

        return "\n".join(lines)

    def _format_acknowledgment(self, escalation_id: str) -> str:
        """Format acknowledgment message for user."""
        return (
            f"I've escalated your request to {self.default_contact}. "
            f"They'll follow up with you shortly.\n\n"
            f"Reference ID: {escalation_id}"
        )

    def _store_escalation(
        self,
        escalation_id: str,
        user_id: str,
        user_name: str,
        topic: str,
        channel_id: str = None,
        context: dict = None
    ) -> None:
        """Store escalation in database for tracking."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO escalations (id, user_id, user_name, topic, channel_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """, (
                escalation_id,
                user_id,
                user_name,
                topic,
                channel_id,
                datetime.now().isoformat()
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            self.logger.warning(f"Failed to store escalation: {e}")
            # Don't fail the escalation if DB write fails

    def get_pending_escalations(self) -> list[dict]:
        """Get all pending escalations for dashboard/review."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM escalations
                WHERE status = 'pending'
                ORDER BY created_at DESC
            """)

            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results

        except Exception as e:
            self.logger.warning(f"Failed to get pending escalations: {e}")
            return []

    def resolve_escalation(self, escalation_id: str, resolved_by: str) -> bool:
        """
        Mark an escalation as resolved.

        Args:
            escalation_id: ID of the escalation
            resolved_by: Who resolved it

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE escalations
                SET status = 'resolved',
                    resolved_by = ?,
                    resolved_at = ?
                WHERE id = ?
            """, (resolved_by, datetime.now().isoformat(), escalation_id))

            success = cursor.rowcount > 0
            conn.commit()
            conn.close()

            if success:
                self.logger.info(f"Escalation {escalation_id} resolved by {resolved_by}")

            return success

        except Exception as e:
            self.logger.error(f"Failed to resolve escalation: {e}")
            return False
