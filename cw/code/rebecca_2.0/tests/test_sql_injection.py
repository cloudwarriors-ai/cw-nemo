"""
Tests for SQL injection prevention.

Verifies that SQL injection vulnerabilities are properly mitigated
through allowlist validation and parameterized queries.
"""
import pytest
import sqlite3

from src.bot.database import (
    init_db,
    run_migrations,
    create_conversation_flow,
    update_conversation_flow,
    get_active_flow,
)
from src.bot.services.rate_limit_service import RateLimitService


class TestRateLimitServiceSQLInjection:
    """Test SQL injection prevention in RateLimitService."""

    @pytest.fixture
    def rate_service(self, temp_db):
        """Create RateLimitService instance."""
        return RateLimitService(db_path=temp_db)

    def test_check_limit_rejects_invalid_table(self, rate_service):
        """Test that _check_limit rejects non-allowlisted table names."""
        with pytest.raises(ValueError, match="Invalid rate limit table"):
            rate_service._check_limit(
                user_id="test_user",
                limit=10,
                table="malicious_table"
            )

    def test_check_limit_rejects_sql_injection_in_table(self, rate_service):
        """Test that SQL injection attempts in table name are blocked."""
        injection_attempts = [
            "rate_limits; DROP TABLE rate_limits;--",
            "rate_limits UNION SELECT * FROM sqlite_master",
            "rate_limits WHERE 1=1; DELETE FROM rate_limits;--",
            "' OR '1'='1",
            "rate_limits\x00malicious",
            "users",
            "",
        ]

        for attempt in injection_attempts:
            with pytest.raises(ValueError, match="Invalid rate limit table"):
                rate_service._check_limit(
                    user_id="test_user",
                    limit=10,
                    table=attempt
                )

    def test_check_limit_accepts_rate_limits_table(self, rate_service):
        """Test that rate_limits table name is accepted."""
        result = rate_service._check_limit(
            user_id="test_user",
            limit=10,
            table="rate_limits"
        )
        assert result is True

    def test_check_limit_accepts_meeting_rate_limits_table(self, rate_service):
        """Test that meeting_rate_limits table name is accepted."""
        result = rate_service._check_limit(
            user_id="test_user",
            limit=10,
            table="meeting_rate_limits"
        )
        assert result is True

    def test_check_chat_limit_uses_valid_table(self, rate_service):
        """Test that check_chat_limit uses valid table internally."""
        # Should not raise - uses hardcoded valid table name
        result = rate_service.check_chat_limit("user1", 10)
        assert result is True

    def test_check_meeting_limit_uses_valid_table(self, rate_service):
        """Test that check_meeting_limit uses valid table internally."""
        # Should not raise - uses hardcoded valid table name
        result = rate_service.check_meeting_limit("user1", 10)
        assert result is True


class TestConversationFlowSQLInjection:
    """Test SQL injection prevention in conversation flow operations."""

    @pytest.fixture
    def db_with_migrations(self, temp_db):
        """Database with migrations run."""
        run_migrations(temp_db)
        return temp_db

    def test_update_flow_parameterizes_flow_id(self, db_with_migrations):
        """Test that SQL injection in flow_id is safely parameterized."""
        # Create a legitimate flow first
        flow_id = "test-flow-id-001"
        create_conversation_flow(
            db_path=db_with_migrations,
            flow_id=flow_id,
            user_id="test_user",
            channel_id="test_channel",
            flow_type="onboarding"
        )

        # Attempt SQL injection in flow_id parameter
        # This should be safely parameterized and just not match any row
        malicious_id = "'; DROP TABLE conversation_flows;--"
        result = update_conversation_flow(
            db_path=db_with_migrations,
            flow_id=malicious_id,
            current_step=5
        )

        # Should return False (no rows matched) but NOT execute injection
        assert result is False

        # Verify table still exists and original flow is intact
        conn = sqlite3.connect(db_with_migrations)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM conversation_flows WHERE id = ?", (flow_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None, "Original flow should still exist"

    def test_update_flow_parameterizes_current_step(self, db_with_migrations):
        """Test that current_step is properly parameterized."""
        flow_id = "test-flow-id-002"
        create_conversation_flow(
            db_path=db_with_migrations,
            flow_id=flow_id,
            user_id="test_user2",
            channel_id="test_channel",
            flow_type="onboarding"
        )

        # Update with valid step
        result = update_conversation_flow(
            db_path=db_with_migrations,
            flow_id=flow_id,
            current_step=3
        )
        assert result is True

        # Verify update worked
        flow = get_active_flow(db_with_migrations, "test_user2")
        assert flow is not None
        assert flow["current_step"] == 3

    def test_update_flow_handles_sql_chars_in_collected_data(self, db_with_migrations):
        """Test that special SQL characters in collected_data are safely stored."""
        flow_id = "test-flow-id-003"
        create_conversation_flow(
            db_path=db_with_migrations,
            flow_id=flow_id,
            user_id="test_user3",
            channel_id="test_channel",
            flow_type="onboarding"
        )

        # Data with SQL-like content (Bobby Tables attack)
        malicious_data = {
            "name": "Robert'); DROP TABLE students;--",
            "email": "test@example.com",
            "query": "SELECT * FROM users WHERE 1=1",
            "comment": "'; DELETE FROM conversation_flows; --",
        }

        result = update_conversation_flow(
            db_path=db_with_migrations,
            flow_id=flow_id,
            collected_data=malicious_data
        )

        assert result is True

        # Verify data was stored literally, not executed as SQL
        flow = get_active_flow(db_with_migrations, "test_user3")

        assert flow is not None
        assert flow["collected_data"]["name"] == "Robert'); DROP TABLE students;--"
        assert flow["collected_data"]["query"] == "SELECT * FROM users WHERE 1=1"

    def test_update_flow_both_fields(self, db_with_migrations):
        """Test updating both current_step and collected_data together."""
        flow_id = "test-flow-id-004"
        create_conversation_flow(
            db_path=db_with_migrations,
            flow_id=flow_id,
            user_id="test_user4",
            channel_id="test_channel",
            flow_type="onboarding"
        )

        data = {"field1": "value1", "field2": "value2"}
        result = update_conversation_flow(
            db_path=db_with_migrations,
            flow_id=flow_id,
            current_step=5,
            collected_data=data
        )

        assert result is True

        flow = get_active_flow(db_with_migrations, "test_user4")
        assert flow["current_step"] == 5
        assert flow["collected_data"] == data

    def test_update_nonexistent_flow_returns_false(self, db_with_migrations):
        """Test that updating a non-existent flow returns False."""
        result = update_conversation_flow(
            db_path=db_with_migrations,
            flow_id="nonexistent-flow-id-12345",
            current_step=1
        )
        assert result is False

    def test_update_with_no_changes_returns_true(self, db_with_migrations):
        """Test that calling update with no changes returns True."""
        result = update_conversation_flow(
            db_path=db_with_migrations,
            flow_id="any-id"
            # No current_step or collected_data provided
        )
        assert result is True


class TestRateLimitServiceFunctionality:
    """Additional tests for rate limit service functionality."""

    @pytest.fixture
    def rate_service(self, temp_db):
        """Create RateLimitService instance."""
        return RateLimitService(db_path=temp_db)

    def test_rate_limit_blocks_over_limit(self, rate_service):
        """Test that requests over limit are blocked."""
        user_id = "rate_limited_user"

        # Use up the limit
        for _ in range(5):
            rate_service.check_chat_limit(user_id, limit=5)

        # Next request should be blocked
        assert rate_service.check_chat_limit(user_id, limit=5) is False

    def test_different_users_have_separate_limits(self, rate_service):
        """Test that rate limits are per-user."""
        # User 1 hits limit
        for _ in range(3):
            rate_service.check_chat_limit("user1", limit=3)
        assert rate_service.check_chat_limit("user1", limit=3) is False

        # User 2 should still be allowed
        assert rate_service.check_chat_limit("user2", limit=3) is True

    def test_reset_user_clears_limits(self, rate_service):
        """Test that reset_user clears all limits for user."""
        user_id = "reset_user"

        # Hit the limit
        for _ in range(5):
            rate_service.check_chat_limit(user_id, limit=5)
        assert rate_service.check_chat_limit(user_id, limit=5) is False

        # Reset
        rate_service.reset_user(user_id)

        # Should be allowed again
        assert rate_service.check_chat_limit(user_id, limit=5) is True

    def test_disabled_limit_always_allows(self, rate_service):
        """Test that limit=0 disables rate limiting."""
        user_id = "unlimited_user"

        for _ in range(100):
            assert rate_service.check_chat_limit(user_id, limit=0) is True
