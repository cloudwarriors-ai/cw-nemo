"""
Tests for the channel abstraction layer.

Tests ChannelManager, Message, DeliveryResult, and channel adapters.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock


class TestMessage:
    """Tests for the Message dataclass."""

    def test_message_creation_minimal(self):
        """Test creating a message with minimal fields."""
        from src.bot.channels import Message

        msg = Message(content="Hello world")

        assert msg.content == "Hello world"
        assert msg.title is None
        assert msg.priority == "normal"
        assert msg.source_service == ""
        assert msg.metadata == {}
        assert isinstance(msg.created_at, datetime)

    def test_message_creation_full(self):
        """Test creating a message with all fields."""
        from src.bot.channels import Message

        msg = Message(
            content="Weekly report",
            title="QA Report",
            priority="high",
            source_service="report",
            metadata={"total_issues": 42}
        )

        assert msg.content == "Weekly report"
        assert msg.title == "QA Report"
        assert msg.priority == "high"
        assert msg.source_service == "report"
        assert msg.metadata == {"total_issues": 42}

    def test_message_to_dict(self):
        """Test message serialization."""
        from src.bot.channels import Message

        msg = Message(content="Test", title="Title")
        data = msg.to_dict()

        assert data["content"] == "Test"
        assert data["title"] == "Title"
        assert "created_at" in data


class TestDeliveryResult:
    """Tests for the DeliveryResult dataclass."""

    def test_success_result(self):
        """Test successful delivery result."""
        from src.bot.channels import DeliveryResult, ChannelType

        result = DeliveryResult(
            success=True,
            channel=ChannelType.ZOOM,
            message_id="msg-123",
            delivered_at=datetime.now()
        )

        assert result.success is True
        assert result.channel == ChannelType.ZOOM
        assert result.message_id == "msg-123"
        assert result.error is None
        assert result.retry_count == 0

    def test_failed_result(self):
        """Test failed delivery result."""
        from src.bot.channels import DeliveryResult, ChannelType

        result = DeliveryResult(
            success=False,
            channel=ChannelType.ZOOM,
            error="Connection timeout",
            retry_count=3
        )

        assert result.success is False
        assert result.error == "Connection timeout"
        assert result.retry_count == 3

    def test_result_to_dict(self):
        """Test result serialization."""
        from src.bot.channels import DeliveryResult, ChannelType

        result = DeliveryResult(
            success=True,
            channel=ChannelType.ZOOM
        )
        data = result.to_dict()

        assert data["success"] is True
        assert data["channel"] == "zoom"


class TestChannelType:
    """Tests for the ChannelType enum."""

    def test_channel_types_exist(self):
        """Test that expected channel types exist."""
        from src.bot.channels import ChannelType

        assert ChannelType.ZOOM.value == "zoom"
        assert ChannelType.SLACK.value == "slack"
        assert ChannelType.EMAIL.value == "email"
        assert ChannelType.SMS.value == "sms"
        assert ChannelType.WEBHOOK.value == "webhook"


class TestZoomChannelAdapter:
    """Tests for the ZoomChannelAdapter."""

    def test_adapter_initialization(self):
        """Test adapter initializes correctly."""
        from src.bot.channels import ZoomChannelAdapter, ChannelType

        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(
            chatbot=mock_chatbot,
            account_id="account-123"
        )

        assert adapter.channel_type == ChannelType.ZOOM
        assert adapter.is_available() is True

    def test_adapter_not_available_without_chatbot(self):
        """Test adapter reports unavailable without chatbot."""
        from src.bot.channels import ZoomChannelAdapter

        adapter = ZoomChannelAdapter(
            chatbot=None,
            account_id="account-123"
        )

        assert adapter.is_available() is False

    def test_format_simple_message(self):
        """Test formatting a simple message."""
        from src.bot.channels import ZoomChannelAdapter, Message

        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(
            chatbot=mock_chatbot,
            account_id="account-123"
        )

        msg = Message(content="Hello world")
        formatted = adapter.format(msg)

        assert formatted == "Hello world"

    def test_format_message_with_title(self):
        """Test formatting a message with title."""
        from src.bot.channels import ZoomChannelAdapter, Message

        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(
            chatbot=mock_chatbot,
            account_id="account-123"
        )

        msg = Message(content="Report content", title="Weekly Report")
        formatted = adapter.format(msg)

        assert "**Weekly Report**" in formatted
        assert "Report content" in formatted

    def test_format_urgent_message(self):
        """Test formatting an urgent message."""
        from src.bot.channels import ZoomChannelAdapter, Message

        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(
            chatbot=mock_chatbot,
            account_id="account-123"
        )

        msg = Message(content="Critical!", priority="urgent")
        formatted = adapter.format(msg)

        assert "immediate attention" in formatted.lower()

    def test_send_success(self):
        """Test successful message send."""
        from src.bot.channels import ZoomChannelAdapter, ChannelType

        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(
            chatbot=mock_chatbot,
            account_id="account-123"
        )

        result = adapter.send("Test message", "jid@zoom.us")

        assert result.success is True
        assert result.channel == ChannelType.ZOOM
        mock_chatbot.send_message.assert_called_once_with(
            message="Test message",
            to_jid="jid@zoom.us",
            account_id="account-123",
            user_jid="jid@zoom.us"
        )

    def test_send_failure_with_retry(self):
        """Test message send with retries on failure."""
        from src.bot.channels import ZoomChannelAdapter

        mock_chatbot = Mock()
        mock_chatbot.send_message.side_effect = Exception("Network error")

        adapter = ZoomChannelAdapter(
            chatbot=mock_chatbot,
            account_id="account-123",
            max_retries=3,
            retry_delay_base=0.01  # Fast retries for tests
        )

        result = adapter.send("Test message", "jid@zoom.us")

        assert result.success is False
        assert "Failed after 3 attempts" in result.error
        assert mock_chatbot.send_message.call_count == 3


class TestChannelManager:
    """Tests for the ChannelManager."""

    def test_manager_initialization(self):
        """Test manager initializes with no adapters."""
        from src.bot.channels import ChannelManager

        manager = ChannelManager()

        assert manager.get_registered_channels() == []
        assert manager.get_available_channels() == []

    def test_register_adapter(self):
        """Test registering an adapter."""
        from src.bot.channels import ChannelManager, ZoomChannelAdapter, ChannelType

        manager = ChannelManager()
        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(mock_chatbot, "account-123")

        manager.register_adapter(adapter)

        assert ChannelType.ZOOM in manager.get_registered_channels()
        assert manager.has_channel(ChannelType.ZOOM)

    def test_register_with_default_destination(self):
        """Test registering adapter with default destination."""
        from src.bot.channels import ChannelManager, ZoomChannelAdapter, ChannelType

        manager = ChannelManager()
        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(mock_chatbot, "account-123")

        manager.register_adapter(adapter, default_destination="default@zoom.us")

        # Should use default when destination not specified
        assert manager._default_destinations[ChannelType.ZOOM] == "default@zoom.us"

    def test_unregister_adapter(self):
        """Test unregistering an adapter."""
        from src.bot.channels import ChannelManager, ZoomChannelAdapter, ChannelType

        manager = ChannelManager()
        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(mock_chatbot, "account-123")

        manager.register_adapter(adapter)
        result = manager.unregister_adapter(ChannelType.ZOOM)

        assert result is True
        assert not manager.has_channel(ChannelType.ZOOM)

    def test_unregister_nonexistent_adapter(self):
        """Test unregistering adapter that doesn't exist."""
        from src.bot.channels import ChannelManager, ChannelType

        manager = ChannelManager()
        result = manager.unregister_adapter(ChannelType.SLACK)

        assert result is False

    def test_send_via_manager(self):
        """Test sending via the manager."""
        from src.bot.channels import ChannelManager, ZoomChannelAdapter, ChannelType, Message

        manager = ChannelManager()
        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(mock_chatbot, "account-123")
        manager.register_adapter(adapter)

        msg = Message(content="Test")
        result = manager.send(msg, ChannelType.ZOOM, destination="test@zoom.us")

        assert result.success is True
        mock_chatbot.send_message.assert_called_once()

    def test_send_no_adapter(self):
        """Test sending to unregistered channel."""
        from src.bot.channels import ChannelManager, ChannelType, Message

        manager = ChannelManager()
        msg = Message(content="Test")

        result = manager.send(msg, ChannelType.SLACK, destination="channel")

        assert result.success is False
        assert "No adapter registered" in result.error

    def test_send_no_destination(self):
        """Test sending without destination or default."""
        from src.bot.channels import ChannelManager, ZoomChannelAdapter, ChannelType, Message

        manager = ChannelManager()
        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(mock_chatbot, "account-123")
        manager.register_adapter(adapter)  # No default destination

        msg = Message(content="Test")
        result = manager.send(msg, ChannelType.ZOOM)  # No destination

        assert result.success is False
        assert "No destination configured" in result.error

    def test_send_uses_default_destination(self):
        """Test sending uses default destination when none provided."""
        from src.bot.channels import ChannelManager, ZoomChannelAdapter, ChannelType, Message

        manager = ChannelManager()
        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(mock_chatbot, "account-123")
        manager.register_adapter(adapter, default_destination="default@zoom.us")

        msg = Message(content="Test")
        result = manager.send(msg, ChannelType.ZOOM)  # No explicit destination

        assert result.success is True
        mock_chatbot.send_message.assert_called_once()
        # Check the destination used was the default
        call_args = mock_chatbot.send_message.call_args
        assert call_args.kwargs["to_jid"] == "default@zoom.us"

    def test_broadcast(self):
        """Test broadcasting to multiple channels."""
        from src.bot.channels import ChannelManager, ZoomChannelAdapter, ChannelType, Message

        manager = ChannelManager()
        mock_chatbot = Mock()
        adapter = ZoomChannelAdapter(mock_chatbot, "account-123")
        manager.register_adapter(adapter, default_destination="channel@zoom.us")

        msg = Message(content="Broadcast test")
        results = manager.broadcast(msg)

        assert ChannelType.ZOOM in results
        assert results[ChannelType.ZOOM].success is True

    def test_get_available_channels(self):
        """Test getting available (configured) channels."""
        from src.bot.channels import ChannelManager, ZoomChannelAdapter, ChannelType

        manager = ChannelManager()

        # Add one available, one unavailable
        available_adapter = ZoomChannelAdapter(Mock(), "account-123")
        unavailable_adapter = ZoomChannelAdapter(None, "account-123")  # No chatbot

        manager.register_adapter(available_adapter)

        available = manager.get_available_channels()
        assert ChannelType.ZOOM in available
