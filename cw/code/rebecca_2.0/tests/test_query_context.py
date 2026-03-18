"""
Tests for QueryContext dataclass.

Tests the query context object used to encapsulate query parameters.
"""
import pytest

from src.bot.services.query_context import QueryContext


class TestQueryContext:
    """Tests for QueryContext dataclass."""

    def test_basic_creation(self):
        """Test basic QueryContext creation with required fields."""
        ctx = QueryContext(
            text="show high priority issues",
            user_id="user123"
        )

        assert ctx.text == "show high priority issues"
        assert ctx.user_id == "user123"
        assert ctx.user_name == ""
        assert ctx.channel_id == ""
        assert ctx.request_id == ""
        assert ctx.user_email == ""
        assert ctx.conversation_history == []

    def test_full_creation(self):
        """Test QueryContext with all fields populated."""
        history = [{"role": "user", "content": "hello"}]
        ctx = QueryContext(
            text="show issues",
            user_id="user123",
            user_name="John Doe",
            channel_id="channel456",
            request_id="req789",
            user_email="john@example.com",
            conversation_history=history
        )

        assert ctx.text == "show issues"
        assert ctx.user_id == "user123"
        assert ctx.user_name == "John Doe"
        assert ctx.channel_id == "channel456"
        assert ctx.request_id == "req789"
        assert ctx.user_email == "john@example.com"
        assert ctx.conversation_history == history

    def test_text_lower_property(self):
        """Test text_lower property returns lowercase stripped text."""
        ctx = QueryContext(
            text="  SHOW HIGH Priority Issues  ",
            user_id="user123"
        )

        assert ctx.text_lower == "show high priority issues"

    def test_text_lower_empty(self):
        """Test text_lower with empty text."""
        ctx = QueryContext(text="", user_id="user123")
        assert ctx.text_lower == ""

    def test_text_lower_whitespace_only(self):
        """Test text_lower with whitespace-only text."""
        ctx = QueryContext(text="   ", user_id="user123")
        assert ctx.text_lower == ""

    def test_log_prefix_with_request_id(self):
        """Test log_prefix returns bracketed request ID."""
        ctx = QueryContext(
            text="query",
            user_id="user123",
            request_id="abc123"
        )

        assert ctx.log_prefix() == "[abc123]"

    def test_log_prefix_without_request_id(self):
        """Test log_prefix returns empty string when no request ID."""
        ctx = QueryContext(
            text="query",
            user_id="user123"
        )

        assert ctx.log_prefix() == ""

    def test_conversation_history_default_factory(self):
        """Test that conversation_history defaults to empty list, not shared."""
        ctx1 = QueryContext(text="query1", user_id="user1")
        ctx2 = QueryContext(text="query2", user_id="user2")

        ctx1.conversation_history.append({"role": "user", "content": "test"})

        # Should not affect ctx2
        assert ctx1.conversation_history == [{"role": "user", "content": "test"}]
        assert ctx2.conversation_history == []
