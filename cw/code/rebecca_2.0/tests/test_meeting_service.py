"""
Tests for MeetingService.

Tests meeting join operations and avatar configuration.
"""
import pytest
from unittest.mock import MagicMock, patch
import logging

from src.bot.services.meeting_service import (
    MeetingService,
    MeetingJoinResult,
    AvatarConfig
)


class TestAvatarConfig:
    """Tests for AvatarConfig dataclass."""

    def test_basic_creation(self):
        """Test basic AvatarConfig creation."""
        config = AvatarConfig(
            mode="websocket",
            bot_id="qa-bot-abc123-1234",
            page_url="https://example.com/avatar/page?bot_id=abc"
        )

        assert config.mode == "websocket"
        assert config.bot_id == "qa-bot-abc123-1234"
        assert config.page_url == "https://example.com/avatar/page?bot_id=abc"
        assert config.room_name is None

    def test_with_livekit_room(self):
        """Test AvatarConfig with LiveKit room."""
        config = AvatarConfig(
            mode="livekit",
            bot_id="qa-bot-abc123-1234",
            page_url="https://example.com/avatar/page?mode=livekit&room=test",
            room_name="avatar-abc123-1234"
        )

        assert config.mode == "livekit"
        assert config.room_name == "avatar-abc123-1234"


class TestMeetingJoinResult:
    """Tests for MeetingJoinResult dataclass."""

    def test_success_result(self):
        """Test successful join result."""
        result = MeetingJoinResult(
            success=True,
            message="Bot joining meeting",
            bot_id="bot123",
            meeting_id="meeting456",
            avatar_enabled=True,
            avatar_mode="websocket"
        )

        assert result.success is True
        assert result.bot_id == "bot123"
        assert result.avatar_enabled is True
        assert result.error is None

    def test_failure_result(self):
        """Test failed join result."""
        result = MeetingJoinResult(
            success=False,
            message="Failed to join meeting",
            error="meeting_not_found"
        )

        assert result.success is False
        assert result.error == "meeting_not_found"
        assert result.bot_id is None


class TestMeetingService:
    """Tests for MeetingService."""

    @pytest.fixture
    def mock_meeting_handler(self):
        """Create a mock meeting handler."""
        handler = MagicMock()
        handler.join_meeting.return_value = {
            "status": "joining",
            "bot_id": "recall-bot-123",
            "meeting_id": "meeting-456"
        }
        return handler

    @pytest.fixture
    def mock_ws_manager(self):
        """Create a mock WebSocket manager."""
        manager = MagicMock()
        return manager

    @pytest.fixture
    def service(self, mock_meeting_handler, mock_ws_manager):
        """Create a MeetingService instance with mocks."""
        return MeetingService(
            meeting_handler=mock_meeting_handler,
            ws_manager=mock_ws_manager,
            public_url="https://example.com",
            default_bot_name="Test Bot",
            logger=logging.getLogger("test")
        )

    def test_generate_bot_id(self, service):
        """Test bot ID generation."""
        bot_id = service.generate_bot_id("https://zoom.us/j/123456")

        assert bot_id.startswith("qa-bot-")
        assert len(bot_id) > 10  # Should have hash and timestamp

    def test_generate_bot_id_uniqueness(self, service):
        """Test that bot IDs are unique for same URL at different times."""
        with patch('time.time', return_value=1000):
            bot_id1 = service.generate_bot_id("https://zoom.us/j/123456")

        with patch('time.time', return_value=2000):
            bot_id2 = service.generate_bot_id("https://zoom.us/j/123456")

        # Timestamps differ, so bot IDs should differ
        assert bot_id1 != bot_id2

    def test_build_avatar_config_websocket(self, service):
        """Test avatar config building for websocket mode."""
        config = service.build_avatar_config(
            meeting_url="https://zoom.us/j/123456",
            mode="websocket"
        )

        assert config.mode == "websocket"
        assert config.bot_id.startswith("qa-bot-")
        assert "mode=websocket" in config.page_url
        assert "bot_id=" in config.page_url
        assert config.room_name is None

    def test_build_avatar_config_no_base_url(self):
        """Test avatar config raises error without base URL."""
        service = MeetingService(
            meeting_handler=MagicMock(),
            public_url=None
        )

        with pytest.raises(ValueError, match="No base URL configured"):
            service.build_avatar_config("https://zoom.us/j/123456")

    def test_join_meeting_success(self, service, mock_meeting_handler, mock_ws_manager):
        """Test successful meeting join."""
        result = service.join_meeting(
            meeting_url="https://zoom.us/j/123456",
            requested_by="user123",
            with_avatar=True
        )

        assert result.success is True
        assert result.bot_id == "recall-bot-123"
        assert result.avatar_enabled is True

        # Verify meeting handler was called
        mock_meeting_handler.join_meeting.assert_called_once()

        # Verify ID mapping was added
        mock_ws_manager.add_id_mapping.assert_called_once()

    def test_join_meeting_no_handler(self):
        """Test join meeting without meeting handler configured."""
        service = MeetingService(
            meeting_handler=None,
            public_url="https://example.com"
        )

        result = service.join_meeting(
            meeting_url="https://zoom.us/j/123456",
            requested_by="user123"
        )

        assert result.success is False
        assert result.error == "meeting_handler_not_configured"

    def test_join_meeting_handler_error(self, service, mock_meeting_handler):
        """Test handling of meeting handler errors."""
        mock_meeting_handler.join_meeting.return_value = {
            "status": "error",
            "error": "invalid_meeting_url"
        }

        result = service.join_meeting(
            meeting_url="https://invalid.url",
            requested_by="user123"
        )

        assert result.success is False
        assert "invalid_meeting_url" in result.error

    def test_join_meeting_without_avatar(self, service, mock_meeting_handler):
        """Test join meeting without avatar."""
        result = service.join_meeting(
            meeting_url="https://zoom.us/j/123456",
            requested_by="user123",
            with_avatar=False
        )

        assert result.success is True
        assert result.avatar_enabled is False

        # Meeting handler should be called without output_media_url
        call_kwargs = mock_meeting_handler.join_meeting.call_args.kwargs
        assert call_kwargs.get("output_media_url") is None

    def test_join_meeting_for_chat(self, service):
        """Test chat command meeting join."""
        response = service.join_meeting_for_chat(
            meeting_url="https://zoom.us/j/123456",
            user_id="user123",
            user_name="John Doe",
            request_id="req456"
        )

        assert "joining" in response.lower()
        assert "avatar" in response.lower()

    def test_join_meeting_for_chat_failure(self):
        """Test chat command meeting join failure."""
        service = MeetingService(
            meeting_handler=None,
            public_url="https://example.com"
        )

        response = service.join_meeting_for_chat(
            meeting_url="https://zoom.us/j/123456",
            user_id="user123",
            user_name="John Doe",
            request_id="req456"
        )

        assert "not configured" in response.lower()
