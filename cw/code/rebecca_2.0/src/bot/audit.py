"""
Audit logging for compliance and security tracking.

Provides a centralized system for logging sensitive operations such as:
- User onboarding/offboarding
- GitHub organization invitations
- Permission changes
- Data access events
- Authentication events

Audit logs are stored in a dedicated SQLite table and can be exported
for compliance reporting.

Usage:
    from .audit import AuditLogger, AuditEvent

    audit = AuditLogger(db_path="qa_bot.db")

    # Log an onboarding event
    audit.log(
        event_type=AuditEvent.INTERN_ONBOARDED,
        actor_id="manager123",
        target_id="intern456",
        details={"github_username": "intern456", "start_date": "2024-01-15"}
    )

    # Query audit logs
    logs = audit.get_logs(event_type=AuditEvent.INTERN_ONBOARDED, limit=100)
"""
import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any


class AuditEvent(str, Enum):
    """
    Audit event types for compliance tracking.

    Naming convention: RESOURCE_ACTION
    """
    # User management
    INTERN_ONBOARDED = "intern.onboarded"
    INTERN_OFFBOARDED = "intern.offboarded"
    INTERN_STATUS_CHANGED = "intern.status_changed"
    INTERN_DATA_ACCESSED = "intern.data_accessed"

    # GitHub operations
    GITHUB_INVITE_SENT = "github.invite_sent"
    GITHUB_INVITE_ACCEPTED = "github.invite_accepted"
    GITHUB_INVITE_FAILED = "github.invite_failed"
    GITHUB_USER_REMOVED = "github.user_removed"
    GITHUB_REPO_ACCESSED = "github.repo_accessed"

    # Authentication
    AUTH_LOGIN_SUCCESS = "auth.login_success"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_PERMISSION_DENIED = "auth.permission_denied"
    AUTH_WEBHOOK_REJECTED = "auth.webhook_rejected"

    # Workflow operations
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"

    # Meeting operations
    MEETING_BOT_JOINED = "meeting.bot_joined"
    MEETING_BOT_LEFT = "meeting.bot_left"
    MEETING_TRANSCRIPT_ACCESSED = "meeting.transcript_accessed"

    # Data operations
    DATA_EXPORTED = "data.exported"
    DATA_DELETED = "data.deleted"
    CONFIG_CHANGED = "config.changed"

    # Rate limiting
    RATE_LIMIT_EXCEEDED = "rate_limit.exceeded"


@dataclass
class AuditRecord:
    """A single audit log record."""
    id: str
    timestamp: str
    event_type: str
    actor_id: str
    target_id: Optional[str]
    details: Dict[str, Any]
    ip_address: Optional[str]
    user_agent: Optional[str]
    request_id: Optional[str]
    outcome: str  # "success" or "failure"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "request_id": self.request_id,
            "outcome": self.outcome,
        }


class AuditLogger:
    """
    Audit logging service for compliance tracking.

    Thread-safe and designed for high-volume logging.
    """

    # SQL for creating audit table
    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            target_id TEXT,
            details TEXT,
            ip_address TEXT,
            user_agent TEXT,
            request_id TEXT,
            outcome TEXT NOT NULL DEFAULT 'success',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """

    CREATE_INDEX_SQL = [
        "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log(event_type)",
        "CREATE INDEX IF NOT EXISTS idx_audit_actor_id ON audit_log(actor_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_target_id ON audit_log(target_id)",
    ]

    def __init__(
        self,
        db_path: str,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the audit logger.

        Args:
            db_path: Path to SQLite database
            logger: Logger instance for operational logging
        """
        self.db_path = db_path
        self.logger = logger or logging.getLogger(__name__)
        self._lock = threading.Lock()

        # Initialize database
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the audit database table."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(self.CREATE_TABLE_SQL)
            for index_sql in self.CREATE_INDEX_SQL:
                cursor.execute(index_sql)

            conn.commit()
            conn.close()

            self.logger.debug("Audit table initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize audit table: {e}")
            raise

    def log(
        self,
        event_type: AuditEvent,
        actor_id: str,
        target_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        outcome: str = "success"
    ) -> str:
        """
        Log an audit event.

        Args:
            event_type: Type of audit event
            actor_id: ID of the user/system performing the action
            target_id: ID of the affected resource/user (optional)
            details: Additional event details (stored as JSON)
            ip_address: Client IP address
            user_agent: Client user agent
            request_id: Request correlation ID
            outcome: "success" or "failure"

        Returns:
            Audit record ID
        """
        audit_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        # Sanitize details
        safe_details = self._sanitize_details(details or {})

        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO audit_log (
                        id, timestamp, event_type, actor_id, target_id,
                        details, ip_address, user_agent, request_id, outcome
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    audit_id,
                    timestamp,
                    event_type.value if isinstance(event_type, AuditEvent) else event_type,
                    actor_id,
                    target_id,
                    json.dumps(safe_details),
                    ip_address,
                    user_agent,
                    request_id,
                    outcome
                ))

                conn.commit()
                conn.close()

            self.logger.debug(
                f"Audit event logged: {event_type} by {actor_id} "
                f"(outcome={outcome}, id={audit_id[:8]})"
            )

            return audit_id

        except Exception as e:
            self.logger.error(f"Failed to log audit event: {e}")
            raise

    def _sanitize_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize audit details to remove sensitive information.

        Redacts:
        - Passwords and secrets
        - API keys
        - Tokens
        """
        safe = {}
        sensitive_keys = {
            "password", "secret", "token", "api_key", "apikey",
            "credential", "private_key", "access_token"
        }

        for key, value in details.items():
            key_lower = key.lower()

            # Check if key contains sensitive indicator
            if any(s in key_lower for s in sensitive_keys):
                safe[key] = "[REDACTED]"
            elif isinstance(value, dict):
                safe[key] = self._sanitize_details(value)
            elif isinstance(value, str) and len(value) > 500:
                # Truncate long strings
                safe[key] = value[:500] + "...[truncated]"
            else:
                safe[key] = value

        return safe

    def get_logs(
        self,
        event_type: Optional[AuditEvent] = None,
        actor_id: Optional[str] = None,
        target_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        outcome: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[AuditRecord]:
        """
        Query audit logs with filters.

        Args:
            event_type: Filter by event type
            actor_id: Filter by actor
            target_id: Filter by target
            start_time: Filter by start time (ISO format)
            end_time: Filter by end time (ISO format)
            outcome: Filter by outcome ("success" or "failure")
            limit: Max records to return
            offset: Pagination offset

        Returns:
            List of AuditRecord objects
        """
        conditions = []
        params = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type.value if isinstance(event_type, AuditEvent) else event_type)

        if actor_id:
            conditions.append("actor_id = ?")
            params.append(actor_id)

        if target_id:
            conditions.append("target_id = ?")
            params.append(target_id)

        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)

        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time)

        if outcome:
            conditions.append("outcome = ?")
            params.append(outcome)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT id, timestamp, event_type, actor_id, target_id,
                   details, ip_address, user_agent, request_id, outcome
            FROM audit_log
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(query, params)

            records = []
            for row in cursor.fetchall():
                records.append(AuditRecord(
                    id=row[0],
                    timestamp=row[1],
                    event_type=row[2],
                    actor_id=row[3],
                    target_id=row[4],
                    details=json.loads(row[5]) if row[5] else {},
                    ip_address=row[6],
                    user_agent=row[7],
                    request_id=row[8],
                    outcome=row[9]
                ))

            conn.close()
            return records

        except Exception as e:
            self.logger.error(f"Failed to query audit logs: {e}")
            raise

    def get_actor_activity(
        self,
        actor_id: str,
        days: int = 30,
        limit: int = 100
    ) -> List[AuditRecord]:
        """
        Get recent activity for a specific actor.

        Args:
            actor_id: Actor ID to query
            days: Number of days to look back
            limit: Max records to return

        Returns:
            List of AuditRecord objects
        """
        from datetime import timedelta
        start_time = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return self.get_logs(actor_id=actor_id, start_time=start_time, limit=limit)

    def get_target_history(
        self,
        target_id: str,
        limit: int = 100
    ) -> List[AuditRecord]:
        """
        Get all audit events for a specific target.

        Args:
            target_id: Target ID to query
            limit: Max records to return

        Returns:
            List of AuditRecord objects
        """
        return self.get_logs(target_id=target_id, limit=limit)

    def count_events(
        self,
        event_type: Optional[AuditEvent] = None,
        outcome: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> int:
        """
        Count audit events matching criteria.

        Args:
            event_type: Filter by event type
            outcome: Filter by outcome
            start_time: Filter by start time
            end_time: Filter by end time

        Returns:
            Count of matching events
        """
        conditions = []
        params = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type.value if isinstance(event_type, AuditEvent) else event_type)

        if outcome:
            conditions.append("outcome = ?")
            params.append(outcome)

        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)

        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"SELECT COUNT(*) FROM audit_log WHERE {where_clause}"

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(query, params)
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            self.logger.error(f"Failed to count audit events: {e}")
            raise

    def export_logs(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        format: str = "json"
    ) -> str:
        """
        Export audit logs for compliance reporting.

        Args:
            start_time: Start of export period
            end_time: End of export period
            format: Export format ("json" or "csv")

        Returns:
            Exported data as string
        """
        logs = self.get_logs(
            start_time=start_time,
            end_time=end_time,
            limit=10000  # Reasonable limit for export
        )

        if format == "json":
            return json.dumps([log.to_dict() for log in logs], indent=2)
        elif format == "csv":
            import csv
            import io

            output = io.StringIO()
            writer = csv.writer(output)

            # Header
            writer.writerow([
                "id", "timestamp", "event_type", "actor_id", "target_id",
                "outcome", "ip_address", "request_id", "details"
            ])

            # Data
            for log in logs:
                writer.writerow([
                    log.id, log.timestamp, log.event_type, log.actor_id,
                    log.target_id, log.outcome, log.ip_address, log.request_id,
                    json.dumps(log.details)
                ])

            return output.getvalue()
        else:
            raise ValueError(f"Unsupported export format: {format}")


# Convenience functions for common audit operations

def log_onboarding(
    audit: AuditLogger,
    actor_id: str,
    intern_id: str,
    github_username: str,
    **extra_details
) -> str:
    """Log intern onboarding event."""
    return audit.log(
        event_type=AuditEvent.INTERN_ONBOARDED,
        actor_id=actor_id,
        target_id=intern_id,
        details={
            "github_username": github_username,
            **extra_details
        }
    )


def log_offboarding(
    audit: AuditLogger,
    actor_id: str,
    intern_id: str,
    reason: Optional[str] = None,
    **extra_details
) -> str:
    """Log intern offboarding event."""
    return audit.log(
        event_type=AuditEvent.INTERN_OFFBOARDED,
        actor_id=actor_id,
        target_id=intern_id,
        details={
            "reason": reason,
            **extra_details
        }
    )


def log_github_invite(
    audit: AuditLogger,
    actor_id: str,
    github_username: str,
    success: bool,
    error: Optional[str] = None,
    **extra_details
) -> str:
    """Log GitHub invitation event."""
    event_type = AuditEvent.GITHUB_INVITE_SENT if success else AuditEvent.GITHUB_INVITE_FAILED
    return audit.log(
        event_type=event_type,
        actor_id=actor_id,
        target_id=github_username,
        details={
            "error": error,
            **extra_details
        },
        outcome="success" if success else "failure"
    )


def log_permission_denied(
    audit: AuditLogger,
    actor_id: str,
    action: str,
    resource: Optional[str] = None,
    ip_address: Optional[str] = None,
    **extra_details
) -> str:
    """Log permission denied event."""
    return audit.log(
        event_type=AuditEvent.AUTH_PERMISSION_DENIED,
        actor_id=actor_id,
        target_id=resource,
        details={
            "action_attempted": action,
            **extra_details
        },
        ip_address=ip_address,
        outcome="failure"
    )
