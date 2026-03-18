"""
Tests for audit logging module.
"""
import json
import pytest
import sqlite3
import tempfile
import os
from datetime import datetime, timezone, timedelta

from src.bot.audit import (
    AuditLogger,
    AuditEvent,
    AuditRecord,
    log_onboarding,
    log_offboarding,
    log_github_invite,
    log_permission_denied,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def audit_logger(temp_db):
    """Create an AuditLogger for testing."""
    return AuditLogger(db_path=temp_db)


class TestAuditLogger:
    """Tests for AuditLogger class."""

    def test_init_creates_table(self, temp_db):
        """Test initialization creates audit table."""
        audit = AuditLogger(db_path=temp_db)

        # Verify table exists
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
        )
        result = cursor.fetchone()
        conn.close()

        assert result is not None
        assert result[0] == "audit_log"

    def test_log_creates_record(self, audit_logger):
        """Test log() creates an audit record."""
        audit_id = audit_logger.log(
            event_type=AuditEvent.INTERN_ONBOARDED,
            actor_id="manager123",
            target_id="intern456",
            details={"github_username": "testuser"}
        )

        assert audit_id is not None
        assert len(audit_id) == 36  # UUID format

    def test_log_stores_all_fields(self, audit_logger):
        """Test log() stores all provided fields."""
        audit_id = audit_logger.log(
            event_type=AuditEvent.GITHUB_INVITE_SENT,
            actor_id="actor123",
            target_id="target456",
            details={"org": "test-org"},
            ip_address="192.168.1.1",
            user_agent="TestBot/1.0",
            request_id="req-abc123",
            outcome="success"
        )

        logs = audit_logger.get_logs(limit=1)
        assert len(logs) == 1

        record = logs[0]
        assert record.id == audit_id
        assert record.event_type == AuditEvent.GITHUB_INVITE_SENT.value
        assert record.actor_id == "actor123"
        assert record.target_id == "target456"
        assert record.details == {"org": "test-org"}
        assert record.ip_address == "192.168.1.1"
        assert record.user_agent == "TestBot/1.0"
        assert record.request_id == "req-abc123"
        assert record.outcome == "success"

    def test_log_default_outcome_is_success(self, audit_logger):
        """Test log() defaults to success outcome."""
        audit_logger.log(
            event_type=AuditEvent.INTERN_ONBOARDED,
            actor_id="actor123"
        )

        logs = audit_logger.get_logs()
        assert logs[0].outcome == "success"

    def test_log_sanitizes_sensitive_data(self, audit_logger):
        """Test log() redacts sensitive information."""
        audit_logger.log(
            event_type=AuditEvent.AUTH_LOGIN_SUCCESS,
            actor_id="user123",
            details={
                "username": "testuser",
                "password": "secret123",
                "api_key": "sk-12345",
                "access_token": "bearer-token"
            }
        )

        logs = audit_logger.get_logs()
        details = logs[0].details

        assert details["username"] == "testuser"
        assert details["password"] == "[REDACTED]"
        assert details["api_key"] == "[REDACTED]"
        assert details["access_token"] == "[REDACTED]"


class TestAuditLogQueries:
    """Tests for audit log querying."""

    def test_get_logs_by_event_type(self, audit_logger):
        """Test filtering logs by event type."""
        audit_logger.log(event_type=AuditEvent.INTERN_ONBOARDED, actor_id="a1")
        audit_logger.log(event_type=AuditEvent.INTERN_OFFBOARDED, actor_id="a2")
        audit_logger.log(event_type=AuditEvent.INTERN_ONBOARDED, actor_id="a3")

        logs = audit_logger.get_logs(event_type=AuditEvent.INTERN_ONBOARDED)

        assert len(logs) == 2
        assert all(l.event_type == AuditEvent.INTERN_ONBOARDED.value for l in logs)

    def test_get_logs_by_actor(self, audit_logger):
        """Test filtering logs by actor."""
        audit_logger.log(event_type=AuditEvent.WORKFLOW_STARTED, actor_id="user1")
        audit_logger.log(event_type=AuditEvent.WORKFLOW_COMPLETED, actor_id="user2")
        audit_logger.log(event_type=AuditEvent.WORKFLOW_FAILED, actor_id="user1")

        logs = audit_logger.get_logs(actor_id="user1")

        assert len(logs) == 2
        assert all(l.actor_id == "user1" for l in logs)

    def test_get_logs_by_target(self, audit_logger):
        """Test filtering logs by target."""
        audit_logger.log(
            event_type=AuditEvent.GITHUB_USER_REMOVED,
            actor_id="admin",
            target_id="target1"
        )
        audit_logger.log(
            event_type=AuditEvent.GITHUB_INVITE_SENT,
            actor_id="admin",
            target_id="target2"
        )

        logs = audit_logger.get_logs(target_id="target1")

        assert len(logs) == 1
        assert logs[0].target_id == "target1"

    def test_get_logs_by_outcome(self, audit_logger):
        """Test filtering logs by outcome."""
        audit_logger.log(
            event_type=AuditEvent.AUTH_LOGIN_SUCCESS,
            actor_id="user1",
            outcome="success"
        )
        audit_logger.log(
            event_type=AuditEvent.AUTH_LOGIN_FAILED,
            actor_id="user2",
            outcome="failure"
        )

        success_logs = audit_logger.get_logs(outcome="success")
        failure_logs = audit_logger.get_logs(outcome="failure")

        assert len(success_logs) == 1
        assert len(failure_logs) == 1
        assert success_logs[0].outcome == "success"
        assert failure_logs[0].outcome == "failure"

    def test_get_logs_pagination(self, audit_logger):
        """Test log pagination."""
        for i in range(10):
            audit_logger.log(event_type=AuditEvent.WORKFLOW_STARTED, actor_id=f"user{i}")

        page1 = audit_logger.get_logs(limit=3, offset=0)
        page2 = audit_logger.get_logs(limit=3, offset=3)

        assert len(page1) == 3
        assert len(page2) == 3

        # Pages should have different records
        page1_ids = {l.id for l in page1}
        page2_ids = {l.id for l in page2}
        assert page1_ids.isdisjoint(page2_ids)

    def test_get_logs_ordered_by_timestamp_desc(self, audit_logger):
        """Test logs are ordered newest first."""
        import time

        audit_logger.log(event_type=AuditEvent.WORKFLOW_STARTED, actor_id="first")
        time.sleep(0.01)
        audit_logger.log(event_type=AuditEvent.WORKFLOW_STARTED, actor_id="second")
        time.sleep(0.01)
        audit_logger.log(event_type=AuditEvent.WORKFLOW_STARTED, actor_id="third")

        logs = audit_logger.get_logs()

        # Newest should be first
        assert logs[0].actor_id == "third"
        assert logs[1].actor_id == "second"
        assert logs[2].actor_id == "first"


class TestAuditCount:
    """Tests for counting audit events."""

    def test_count_all_events(self, audit_logger):
        """Test counting all events."""
        for i in range(5):
            audit_logger.log(event_type=AuditEvent.WORKFLOW_STARTED, actor_id=f"u{i}")

        count = audit_logger.count_events()
        assert count == 5

    def test_count_by_event_type(self, audit_logger):
        """Test counting by event type."""
        audit_logger.log(event_type=AuditEvent.INTERN_ONBOARDED, actor_id="a1")
        audit_logger.log(event_type=AuditEvent.INTERN_OFFBOARDED, actor_id="a2")
        audit_logger.log(event_type=AuditEvent.INTERN_ONBOARDED, actor_id="a3")

        count = audit_logger.count_events(event_type=AuditEvent.INTERN_ONBOARDED)
        assert count == 2

    def test_count_by_outcome(self, audit_logger):
        """Test counting by outcome."""
        audit_logger.log(event_type=AuditEvent.AUTH_LOGIN_SUCCESS, actor_id="u1", outcome="success")
        audit_logger.log(event_type=AuditEvent.AUTH_LOGIN_FAILED, actor_id="u2", outcome="failure")
        audit_logger.log(event_type=AuditEvent.AUTH_LOGIN_SUCCESS, actor_id="u3", outcome="success")

        success_count = audit_logger.count_events(outcome="success")
        failure_count = audit_logger.count_events(outcome="failure")

        assert success_count == 2
        assert failure_count == 1


class TestAuditExport:
    """Tests for audit log export."""

    def test_export_json(self, audit_logger):
        """Test JSON export format."""
        audit_logger.log(event_type=AuditEvent.INTERN_ONBOARDED, actor_id="actor1")
        audit_logger.log(event_type=AuditEvent.INTERN_OFFBOARDED, actor_id="actor2")

        export_data = audit_logger.export_logs(format="json")
        parsed = json.loads(export_data)

        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert "event_type" in parsed[0]
        assert "actor_id" in parsed[0]

    def test_export_csv(self, audit_logger):
        """Test CSV export format."""
        audit_logger.log(event_type=AuditEvent.WORKFLOW_STARTED, actor_id="actor1")

        export_data = audit_logger.export_logs(format="csv")

        # Check header
        assert "id,timestamp,event_type" in export_data
        # Check data row
        assert "actor1" in export_data

    def test_export_invalid_format(self, audit_logger):
        """Test invalid export format raises error."""
        with pytest.raises(ValueError) as exc_info:
            audit_logger.export_logs(format="xml")
        assert "Unsupported export format" in str(exc_info.value)


class TestActivityQueries:
    """Tests for activity query helpers."""

    def test_get_actor_activity(self, audit_logger):
        """Test getting actor activity."""
        audit_logger.log(event_type=AuditEvent.WORKFLOW_STARTED, actor_id="user123")
        audit_logger.log(event_type=AuditEvent.WORKFLOW_COMPLETED, actor_id="user123")
        audit_logger.log(event_type=AuditEvent.WORKFLOW_STARTED, actor_id="other")

        activity = audit_logger.get_actor_activity("user123")

        assert len(activity) == 2
        assert all(a.actor_id == "user123" for a in activity)

    def test_get_target_history(self, audit_logger):
        """Test getting target history."""
        audit_logger.log(
            event_type=AuditEvent.GITHUB_INVITE_SENT,
            actor_id="admin1",
            target_id="intern123"
        )
        audit_logger.log(
            event_type=AuditEvent.GITHUB_USER_REMOVED,
            actor_id="admin2",
            target_id="intern123"
        )

        history = audit_logger.get_target_history("intern123")

        assert len(history) == 2
        assert all(h.target_id == "intern123" for h in history)


class TestConvenienceFunctions:
    """Tests for convenience logging functions."""

    def test_log_onboarding(self, audit_logger):
        """Test onboarding convenience function."""
        audit_id = log_onboarding(
            audit_logger,
            actor_id="manager",
            intern_id="intern123",
            github_username="internuser",
            start_date="2024-01-15"
        )

        logs = audit_logger.get_logs()
        assert len(logs) == 1
        assert logs[0].event_type == AuditEvent.INTERN_ONBOARDED.value
        assert logs[0].details["github_username"] == "internuser"
        assert logs[0].details["start_date"] == "2024-01-15"

    def test_log_offboarding(self, audit_logger):
        """Test offboarding convenience function."""
        audit_id = log_offboarding(
            audit_logger,
            actor_id="manager",
            intern_id="intern123",
            reason="Internship completed"
        )

        logs = audit_logger.get_logs()
        assert len(logs) == 1
        assert logs[0].event_type == AuditEvent.INTERN_OFFBOARDED.value
        assert logs[0].details["reason"] == "Internship completed"

    def test_log_github_invite_success(self, audit_logger):
        """Test GitHub invite logging for success."""
        log_github_invite(
            audit_logger,
            actor_id="admin",
            github_username="newuser",
            success=True
        )

        logs = audit_logger.get_logs()
        assert logs[0].event_type == AuditEvent.GITHUB_INVITE_SENT.value
        assert logs[0].outcome == "success"

    def test_log_github_invite_failure(self, audit_logger):
        """Test GitHub invite logging for failure."""
        log_github_invite(
            audit_logger,
            actor_id="admin",
            github_username="newuser",
            success=False,
            error="User not found"
        )

        logs = audit_logger.get_logs()
        assert logs[0].event_type == AuditEvent.GITHUB_INVITE_FAILED.value
        assert logs[0].outcome == "failure"
        assert logs[0].details["error"] == "User not found"

    def test_log_permission_denied(self, audit_logger):
        """Test permission denied logging."""
        log_permission_denied(
            audit_logger,
            actor_id="user123",
            action="delete_intern",
            resource="intern456",
            ip_address="10.0.0.1"
        )

        logs = audit_logger.get_logs()
        assert logs[0].event_type == AuditEvent.AUTH_PERMISSION_DENIED.value
        assert logs[0].outcome == "failure"
        assert logs[0].ip_address == "10.0.0.1"


class TestAuditRecord:
    """Tests for AuditRecord dataclass."""

    def test_to_dict(self):
        """Test AuditRecord to_dict conversion."""
        record = AuditRecord(
            id="test-id",
            timestamp="2024-01-15T10:00:00Z",
            event_type="intern.onboarded",
            actor_id="actor123",
            target_id="target456",
            details={"key": "value"},
            ip_address="192.168.1.1",
            user_agent="TestBot",
            request_id="req-123",
            outcome="success"
        )

        d = record.to_dict()

        assert d["id"] == "test-id"
        assert d["event_type"] == "intern.onboarded"
        assert d["details"] == {"key": "value"}
