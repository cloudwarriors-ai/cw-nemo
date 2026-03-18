"""
Tests for platform module (LiveKit avatar and Zoom Meeting SDK bridge).

Tests QABrainLLMAdapter, LLMResponseChunk, LiveKitAvatarAgent,
ZoomMeetingBot, ZoomAvatarBridge, and VideoFrame.
"""
import asyncio
import os
import threading
import time
from dataclasses import dataclass
from queue import Queue
from unittest.mock import Mock, MagicMock, patch, AsyncMock

import pytest

# Check if livekit is available
try:
    import livekit
    LIVEKIT_AVAILABLE = True
except ImportError:
    LIVEKIT_AVAILABLE = False

# Skip decorator for livekit-dependent tests
requires_livekit = pytest.mark.skipif(
    not LIVEKIT_AVAILABLE,
    reason="LiveKit not installed"
)


# ============================================================================
# LLMResponseChunk Tests
# ============================================================================

@requires_livekit
@pytest.mark.xfail(reason="LLMResponseChunk class not yet implemented in livekit_avatar.py")
class TestLLMResponseChunk:
    """Tests for LLMResponseChunk dataclass."""

    def test_chunk_creation(self):
        """Test creating a response chunk."""
        from src.platform.livekit_avatar import LLMResponseChunk

        chunk = LLMResponseChunk("Hello world")

        assert chunk.text == "Hello world"
        assert chunk.content == "Hello world"
        assert chunk.delta == "Hello world"
        assert chunk.is_final is False

    def test_chunk_final_flag(self):
        """Test chunk with is_final flag."""
        from src.platform.livekit_avatar import LLMResponseChunk

        chunk = LLMResponseChunk("Done", is_final=True)

        assert chunk.is_final is True

    def test_chunk_str_representation(self):
        """Test string representation."""
        from src.platform.livekit_avatar import LLMResponseChunk

        chunk = LLMResponseChunk("Test text")

        assert str(chunk) == "Test text"

    def test_chunk_repr(self):
        """Test repr for debugging."""
        from src.platform.livekit_avatar import LLMResponseChunk

        chunk = LLMResponseChunk("Test")

        assert "LLMResponseChunk" in repr(chunk)
        assert "Test" in repr(chunk)


# ============================================================================
# QABrainLLMAdapter Tests
# ============================================================================

@requires_livekit
@pytest.mark.xfail(reason="QABrainLLMAdapter class not yet implemented in livekit_avatar.py")
class TestQABrainLLMAdapter:
    """Tests for QABrainLLMAdapter."""

    def test_adapter_initialization(self):
        """Test adapter initializes with query handler."""
        from src.platform.livekit_avatar import QABrainLLMAdapter

        handler = Mock(return_value="response")
        adapter = QABrainLLMAdapter(handler)

        assert adapter.query_handler == handler
        assert adapter._conversation_history == []

    def test_adapter_requires_handler(self):
        """Test adapter raises error without handler."""
        from src.platform.livekit_avatar import QABrainLLMAdapter

        with pytest.raises(ValueError, match="query_handler cannot be None"):
            QABrainLLMAdapter(None)

    @pytest.mark.asyncio
    async def test_chat_extracts_user_message(self):
        """Test chat extracts the latest user message."""
        from src.platform.livekit_avatar import QABrainLLMAdapter

        handler = Mock(return_value="Response text")
        adapter = QABrainLLMAdapter(handler)

        messages = [
            {"role": "system", "content": "You are a QA assistant"},
            {"role": "user", "content": "What is the status?"},
        ]

        chunks = []
        async for chunk in adapter.chat(messages):
            chunks.append(chunk)

        handler.assert_called_once_with("What is the status?")
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_chat_handles_multiple_user_messages(self):
        """Test chat uses the most recent user message."""
        from src.platform.livekit_avatar import QABrainLLMAdapter

        handler = Mock(return_value="Response")
        adapter = QABrainLLMAdapter(handler)

        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "First response"},
            {"role": "user", "content": "Second message"},
        ]

        chunks = []
        async for chunk in adapter.chat(messages):
            chunks.append(chunk)

        handler.assert_called_once_with("Second message")

    @pytest.mark.asyncio
    async def test_chat_streams_response_in_chunks(self):
        """Test chat yields response in word chunks."""
        from src.platform.livekit_avatar import QABrainLLMAdapter

        # Response with 12 words should yield 3 chunks (5 words each, last has 2)
        handler = Mock(return_value="One two three four five six seven eight nine ten eleven twelve")
        adapter = QABrainLLMAdapter(handler)

        messages = [{"role": "user", "content": "test"}]

        chunks = []
        async for chunk in adapter.chat(messages):
            chunks.append(chunk.text)

        # Should have multiple chunks
        assert len(chunks) == 3
        # Full text should be reconstructed
        full_text = "".join(chunks)
        assert "One two three four five" in full_text
        assert "twelve" in full_text

    @pytest.mark.asyncio
    async def test_chat_empty_messages(self):
        """Test chat handles empty messages list."""
        from src.platform.livekit_avatar import QABrainLLMAdapter

        handler = Mock(return_value="Response")
        adapter = QABrainLLMAdapter(handler)

        chunks = []
        async for chunk in adapter.chat([]):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "didn't receive" in chunks[0].text.lower()
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_chat_no_user_message(self):
        """Test chat handles messages with no user role."""
        from src.platform.livekit_avatar import QABrainLLMAdapter

        handler = Mock(return_value="Response")
        adapter = QABrainLLMAdapter(handler)

        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "assistant", "content": "Previous response"},
        ]

        chunks = []
        async for chunk in adapter.chat(messages):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "didn't catch" in chunks[0].text.lower()
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_chat_empty_response(self):
        """Test chat handles empty response from handler."""
        from src.platform.livekit_avatar import QABrainLLMAdapter

        handler = Mock(return_value="")
        adapter = QABrainLLMAdapter(handler)

        messages = [{"role": "user", "content": "test"}]

        chunks = []
        async for chunk in adapter.chat(messages):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "don't have a response" in chunks[0].text.lower()

    @pytest.mark.asyncio
    async def test_chat_handler_exception(self):
        """Test chat handles exceptions from handler."""
        from src.platform.livekit_avatar import QABrainLLMAdapter

        handler = Mock(side_effect=Exception("Database error"))
        adapter = QABrainLLMAdapter(handler)

        messages = [{"role": "user", "content": "test"}]

        chunks = []
        async for chunk in adapter.chat(messages):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "error" in chunks[0].text.lower()

    def test_adapter_async_iteration_support(self):
        """Test adapter supports async iteration protocol."""
        from src.platform.livekit_avatar import QABrainLLMAdapter

        handler = Mock(return_value="Response")
        adapter = QABrainLLMAdapter(handler)

        assert adapter.__aiter__() == adapter

    @pytest.mark.asyncio
    async def test_adapter_anext_raises_stop(self):
        """Test __anext__ raises StopAsyncIteration."""
        from src.platform.livekit_avatar import QABrainLLMAdapter

        handler = Mock(return_value="Response")
        adapter = QABrainLLMAdapter(handler)

        with pytest.raises(StopAsyncIteration):
            await adapter.__anext__()


# ============================================================================
# ZoomBotState Tests
# ============================================================================

class TestZoomBotState:
    """Tests for ZoomBotState enum."""

    def test_state_values(self):
        """Test all state values exist."""
        from src.platform.zoom_bot import ZoomBotState

        assert ZoomBotState.DISCONNECTED.value == "disconnected"
        assert ZoomBotState.CONNECTING.value == "connecting"
        assert ZoomBotState.IN_WAITING_ROOM.value == "in_waiting_room"
        assert ZoomBotState.IN_MEETING.value == "in_meeting"
        assert ZoomBotState.ERROR.value == "error"


# ============================================================================
# VideoFrame Tests
# ============================================================================

class TestVideoFrame:
    """Tests for VideoFrame dataclass."""

    def test_frame_creation(self):
        """Test creating a video frame."""
        from src.platform.zoom_bot import VideoFrame

        frame = VideoFrame(
            data=b"pixel_data",
            width=1920,
            height=1080,
            format="rgb24",
            timestamp_ms=12345,
        )

        assert frame.data == b"pixel_data"
        assert frame.width == 1920
        assert frame.height == 1080
        assert frame.format == "rgb24"
        assert frame.timestamp_ms == 12345

    def test_frame_yuv420_format(self):
        """Test frame with YUV420 format."""
        from src.platform.zoom_bot import VideoFrame

        frame = VideoFrame(
            data=b"yuv_data",
            width=640,
            height=480,
            format="yuv420",
            timestamp_ms=0,
        )

        assert frame.format == "yuv420"


# ============================================================================
# ZoomMeetingBot Tests
# ============================================================================

class TestZoomMeetingBot:
    """Tests for ZoomMeetingBot."""

    @pytest.fixture
    def mock_env(self):
        """Set up mock environment variables."""
        with patch.dict(os.environ, {
            "ZOOM_SDK_CLIENT_ID": "test-client-id",
            "ZOOM_SDK_CLIENT_SECRET": "test-client-secret",
        }):
            yield

    def test_bot_initialization(self, mock_env):
        """Test bot initializes with environment credentials."""
        from src.platform.zoom_bot import ZoomMeetingBot, ZoomBotState

        bot = ZoomMeetingBot()

        assert bot.client_id == "test-client-id"
        assert bot.client_secret == "test-client-secret"
        assert bot.display_name == "QA Bot"
        assert bot.state == ZoomBotState.DISCONNECTED
        assert bot._sdk is None

    def test_bot_custom_credentials(self, mock_env):
        """Test bot accepts custom credentials."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot(
            client_id="custom-id",
            client_secret="custom-secret",
            display_name="Custom Bot",
        )

        assert bot.client_id == "custom-id"
        assert bot.client_secret == "custom-secret"
        assert bot.display_name == "Custom Bot"

    def test_bot_missing_credentials(self):
        """Test bot raises error without credentials."""
        from src.platform.zoom_bot import ZoomMeetingBot

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="credentials required"):
                ZoomMeetingBot()

    def test_bot_state_property(self, mock_env):
        """Test state property returns current state."""
        from src.platform.zoom_bot import ZoomMeetingBot, ZoomBotState

        bot = ZoomMeetingBot()

        assert bot.state == ZoomBotState.DISCONNECTED

    def test_bot_is_in_meeting_false(self, mock_env):
        """Test is_in_meeting returns False when disconnected."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        assert bot.is_in_meeting is False

    def test_bot_is_in_meeting_true(self, mock_env):
        """Test is_in_meeting returns True when in meeting."""
        from src.platform.zoom_bot import ZoomMeetingBot, ZoomBotState

        bot = ZoomMeetingBot()
        bot._state = ZoomBotState.IN_MEETING

        assert bot.is_in_meeting is True

    def test_set_state_updates_and_notifies(self, mock_env):
        """Test _set_state updates state and calls callback."""
        from src.platform.zoom_bot import ZoomMeetingBot, ZoomBotState

        bot = ZoomMeetingBot()
        states_received = []

        def on_state_change(state):
            states_received.append(state)

        bot._on_state_change = on_state_change
        bot._set_state(ZoomBotState.CONNECTING)

        assert bot._state == ZoomBotState.CONNECTING
        assert ZoomBotState.CONNECTING in states_received

    def test_set_callbacks(self, mock_env):
        """Test set_callbacks stores callbacks."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()
        state_cb = Mock()
        participant_cb = Mock()
        audio_cb = Mock()

        bot.set_callbacks(
            on_state_change=state_cb,
            on_participant_joined=participant_cb,
            on_audio_received=audio_cb,
        )

        assert bot._on_state_change == state_cb
        assert bot._on_participant_joined == participant_cb
        assert bot._on_audio_received == audio_cb

    # Meeting ID validation tests
    def test_validate_meeting_id_valid(self, mock_env):
        """Test meeting ID validation with valid ID."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        result = bot._validate_meeting_id("123456789")

        assert result == "123456789"

    def test_validate_meeting_id_with_dashes(self, mock_env):
        """Test meeting ID strips dashes."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        result = bot._validate_meeting_id("123-456-789")

        assert result == "123456789"

    def test_validate_meeting_id_with_spaces(self, mock_env):
        """Test meeting ID strips spaces."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        result = bot._validate_meeting_id("123 456 789")

        assert result == "123456789"

    def test_validate_meeting_id_empty(self, mock_env):
        """Test empty meeting ID raises error."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        with pytest.raises(ValueError, match="cannot be empty"):
            bot._validate_meeting_id("")

    def test_validate_meeting_id_non_numeric(self, mock_env):
        """Test non-numeric meeting ID raises error."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        with pytest.raises(ValueError, match="must be numeric"):
            bot._validate_meeting_id("abc123def")

    def test_validate_meeting_id_too_short(self, mock_env):
        """Test short meeting ID raises error."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        with pytest.raises(ValueError, match="too short"):
            bot._validate_meeting_id("12345678")  # 8 digits, min is 9

    def test_validate_meeting_id_too_long(self, mock_env):
        """Test long meeting ID raises error."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        with pytest.raises(ValueError, match="too long"):
            bot._validate_meeting_id("123456789012345678901")  # 21 digits, max is 20

    # Video frame queue tests
    def test_send_video_frame_queues_frame(self, mock_env):
        """Test send_video_frame adds frame to queue."""
        from src.platform.zoom_bot import ZoomMeetingBot, VideoFrame

        bot = ZoomMeetingBot()
        frame = VideoFrame(
            data=b"x" * (640 * 480 * 3),  # rgb24 size
            width=640,
            height=480,
            format="rgb24",
            timestamp_ms=1000,
        )

        bot.send_video_frame(frame)

        assert not bot._video_queue.empty()
        queued_frame = bot._video_queue.get_nowait()
        assert queued_frame == frame

    def test_send_video_frame_empty_frame_ignored(self, mock_env):
        """Test empty frames are ignored."""
        from src.platform.zoom_bot import ZoomMeetingBot, VideoFrame

        bot = ZoomMeetingBot()
        frame = VideoFrame(
            data=b"",
            width=640,
            height=480,
            format="rgb24",
            timestamp_ms=1000,
        )

        bot.send_video_frame(frame)

        assert bot._video_queue.empty()

    def test_send_video_frame_none_ignored(self, mock_env):
        """Test None frames are ignored."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        bot.send_video_frame(None)

        assert bot._video_queue.empty()

    def test_send_video_frame_drops_oldest_when_full(self, mock_env):
        """Test oldest frame is dropped when queue is full."""
        from src.platform.zoom_bot import ZoomMeetingBot, VideoFrame, VIDEO_QUEUE_SIZE

        bot = ZoomMeetingBot()

        # Fill the queue
        for i in range(VIDEO_QUEUE_SIZE):
            frame = VideoFrame(
                data=b"x",
                width=1,
                height=1,
                format="rgb24",
                timestamp_ms=i,
            )
            bot._video_queue.put(frame)

        # Queue should be full
        assert bot._video_queue.full()

        # Add one more
        new_frame = VideoFrame(
            data=b"new",
            width=1,
            height=1,
            format="rgb24",
            timestamp_ms=9999,
        )
        bot.send_video_frame(new_frame)

        # Should still be at max size
        assert bot._video_queue.qsize() == VIDEO_QUEUE_SIZE

        # Drain queue - newest frame should be last
        frames = []
        while not bot._video_queue.empty():
            frames.append(bot._video_queue.get_nowait())

        assert frames[-1].timestamp_ms == 9999

    def test_send_video_frame_thread_safe(self, mock_env):
        """Test send_video_frame is thread-safe."""
        from src.platform.zoom_bot import ZoomMeetingBot, VideoFrame

        bot = ZoomMeetingBot()
        errors = []

        def send_frames():
            try:
                for i in range(50):
                    frame = VideoFrame(
                        data=b"x",
                        width=1,
                        height=1,
                        format="rgb24",
                        timestamp_ms=i,
                    )
                    bot.send_video_frame(frame)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=send_frames) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    # Audio queue tests
    def test_send_audio_queues_data(self, mock_env):
        """Test send_audio adds data to queue."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        bot.send_audio(b"audio_data")

        assert not bot._audio_queue.empty()
        assert bot._audio_queue.get_nowait() == b"audio_data"

    def test_send_audio_empty_ignored(self, mock_env):
        """Test empty audio is ignored."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        bot.send_audio(b"")

        assert bot._audio_queue.empty()

    def test_send_audio_none_ignored(self, mock_env):
        """Test None audio is ignored."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        bot.send_audio(None)

        assert bot._audio_queue.empty()

    # Expected frame size calculation
    def test_get_expected_frame_size_yuv420(self, mock_env):
        """Test YUV420 frame size calculation."""
        from src.platform.zoom_bot import ZoomMeetingBot, VideoFrame

        bot = ZoomMeetingBot()
        frame = VideoFrame(
            data=b"",
            width=640,
            height=480,
            format="yuv420",
            timestamp_ms=0,
        )

        expected = bot._get_expected_frame_size(frame)

        # YUV420 = width * height * 1.5
        assert expected == int(640 * 480 * 1.5)

    def test_get_expected_frame_size_rgb24(self, mock_env):
        """Test RGB24 frame size calculation."""
        from src.platform.zoom_bot import ZoomMeetingBot, VideoFrame

        bot = ZoomMeetingBot()
        frame = VideoFrame(
            data=b"",
            width=640,
            height=480,
            format="rgb24",
            timestamp_ms=0,
        )

        expected = bot._get_expected_frame_size(frame)

        # RGB24 = width * height * 3
        assert expected == 640 * 480 * 3

    def test_get_expected_frame_size_rgba(self, mock_env):
        """Test RGBA frame size calculation."""
        from src.platform.zoom_bot import ZoomMeetingBot, VideoFrame

        bot = ZoomMeetingBot()
        frame = VideoFrame(
            data=b"",
            width=640,
            height=480,
            format="rgba",
            timestamp_ms=0,
        )

        expected = bot._get_expected_frame_size(frame)

        # RGBA = width * height * 4
        assert expected == 640 * 480 * 4

    def test_get_expected_frame_size_unknown(self, mock_env):
        """Test unknown format returns None."""
        from src.platform.zoom_bot import ZoomMeetingBot, VideoFrame

        bot = ZoomMeetingBot()
        frame = VideoFrame(
            data=b"",
            width=640,
            height=480,
            format="unknown",
            timestamp_ms=0,
        )

        expected = bot._get_expected_frame_size(frame)

        assert expected is None

    # JWT generation
    def test_generate_jwt(self, mock_env):
        """Test JWT generation produces valid format."""
        from src.platform.zoom_bot import ZoomMeetingBot

        bot = ZoomMeetingBot()

        jwt = bot._generate_jwt("123456789")

        # JWT has 3 parts separated by dots
        parts = jwt.split(".")
        assert len(parts) == 3
        # All parts should be base64-ish
        for part in parts:
            assert len(part) > 0


# ============================================================================
# ZoomAvatarBridge Tests
# ============================================================================

class TestZoomAvatarBridge:
    """Tests for ZoomAvatarBridge."""

    @pytest.fixture
    def mock_zoom_bot(self):
        """Create a mock ZoomMeetingBot."""
        with patch.dict(os.environ, {
            "ZOOM_SDK_CLIENT_ID": "test-client-id",
            "ZOOM_SDK_CLIENT_SECRET": "test-client-secret",
        }):
            from src.platform.zoom_bot import ZoomMeetingBot, ZoomBotState
            bot = ZoomMeetingBot()
            bot._state = ZoomBotState.IN_MEETING
            return bot

    def test_bridge_initialization(self, mock_zoom_bot):
        """Test bridge initializes with correct defaults."""
        from src.platform.zoom_bot import ZoomAvatarBridge

        bridge = ZoomAvatarBridge(mock_zoom_bot)

        assert bridge.zoom_bot == mock_zoom_bot
        assert bridge.target_fps == 30
        assert bridge.target_width == 1280
        assert bridge.target_height == 720
        assert bridge._running is False

    def test_bridge_custom_settings(self, mock_zoom_bot):
        """Test bridge accepts custom settings."""
        from src.platform.zoom_bot import ZoomAvatarBridge

        bridge = ZoomAvatarBridge(
            mock_zoom_bot,
            target_fps=60,
            target_width=1920,
            target_height=1080,
        )

        assert bridge.target_fps == 60
        assert bridge.target_width == 1920
        assert bridge.target_height == 1080

    @pytest.mark.asyncio
    async def test_bridge_start(self, mock_zoom_bot):
        """Test bridge start sets running flag."""
        from src.platform.zoom_bot import ZoomAvatarBridge

        bridge = ZoomAvatarBridge(mock_zoom_bot)

        await bridge.start()

        assert bridge._running is True

    @pytest.mark.asyncio
    async def test_bridge_stop(self, mock_zoom_bot):
        """Test bridge stop clears running flag."""
        from src.platform.zoom_bot import ZoomAvatarBridge

        bridge = ZoomAvatarBridge(mock_zoom_bot)
        bridge._running = True

        await bridge.stop()

        assert bridge._running is False

    def test_on_video_frame_not_running(self, mock_zoom_bot):
        """Test video frame ignored when not running."""
        from src.platform.zoom_bot import ZoomAvatarBridge

        bridge = ZoomAvatarBridge(mock_zoom_bot)
        mock_zoom_bot.send_video_frame = Mock()

        bridge.on_video_frame(b"data", 640, 480, "rgb24")

        mock_zoom_bot.send_video_frame.assert_not_called()

    def test_on_video_frame_not_in_meeting(self, mock_zoom_bot):
        """Test video frame ignored when not in meeting."""
        from src.platform.zoom_bot import ZoomAvatarBridge, ZoomBotState

        mock_zoom_bot._state = ZoomBotState.DISCONNECTED
        bridge = ZoomAvatarBridge(mock_zoom_bot)
        bridge._running = True
        mock_zoom_bot.send_video_frame = Mock()

        bridge.on_video_frame(b"data", 640, 480, "rgb24")

        mock_zoom_bot.send_video_frame.assert_not_called()

    def test_on_video_frame_rate_limited(self, mock_zoom_bot):
        """Test video frame rate limiting."""
        from src.platform.zoom_bot import ZoomAvatarBridge

        bridge = ZoomAvatarBridge(mock_zoom_bot, target_fps=30)
        bridge._running = True
        mock_zoom_bot.send_video_frame = Mock()

        # First frame should go through
        bridge.on_video_frame(b"data1", 640, 480, "rgb24")
        # Second frame immediately after should be rate-limited
        bridge.on_video_frame(b"data2", 640, 480, "rgb24")

        # Only one call expected due to rate limiting
        assert mock_zoom_bot.send_video_frame.call_count == 1

    def test_on_video_frame_creates_correct_frame(self, mock_zoom_bot):
        """Test video frame is created with correct properties."""
        from src.platform.zoom_bot import ZoomAvatarBridge, VideoFrame

        bridge = ZoomAvatarBridge(mock_zoom_bot)
        bridge._running = True
        mock_zoom_bot.send_video_frame = Mock()

        bridge.on_video_frame(b"pixel_data", 640, 480, "rgb24")

        mock_zoom_bot.send_video_frame.assert_called_once()
        frame = mock_zoom_bot.send_video_frame.call_args[0][0]
        assert isinstance(frame, VideoFrame)
        assert frame.data == b"pixel_data"
        assert frame.width == 640
        assert frame.height == 480
        assert frame.format == "rgb24"

    def test_on_audio_chunk_not_running(self, mock_zoom_bot):
        """Test audio chunk ignored when not running."""
        from src.platform.zoom_bot import ZoomAvatarBridge

        bridge = ZoomAvatarBridge(mock_zoom_bot)
        mock_zoom_bot.send_audio = Mock()

        bridge.on_audio_chunk(b"audio")

        mock_zoom_bot.send_audio.assert_not_called()

    def test_on_audio_chunk_sends_to_bot(self, mock_zoom_bot):
        """Test audio chunk is sent to bot."""
        from src.platform.zoom_bot import ZoomAvatarBridge

        bridge = ZoomAvatarBridge(mock_zoom_bot)
        bridge._running = True
        mock_zoom_bot.send_audio = Mock()

        bridge.on_audio_chunk(b"audio_data")

        mock_zoom_bot.send_audio.assert_called_once_with(b"audio_data")


# ============================================================================
# LiveKitAvatarAgent Tests
# ============================================================================

@requires_livekit
@pytest.mark.xfail(reason="LiveKitAvatarAgent class not yet implemented in livekit_avatar.py")
class TestLiveKitAvatarAgent:
    """Tests for LiveKitAvatarAgent."""

    @pytest.fixture
    def mock_env(self):
        """Set up mock environment variables."""
        with patch.dict(os.environ, {
            "SIMLI_API_KEY": "test-simli-key",
            "SIMLI_FACE_ID": "test-face-id",
            "DEEPGRAM_API_KEY": "test-deepgram-key",
            "CARTESIA_API_KEY": "test-cartesia-key",
            "LIVEKIT_URL": "wss://test.livekit.cloud",
            "LIVEKIT_API_KEY": "test-livekit-key",
            "LIVEKIT_API_SECRET": "test-livekit-secret",
        }):
            yield

    def test_agent_initialization(self, mock_env):
        """Test agent initializes with environment variables."""
        from src.platform.livekit_avatar import LiveKitAvatarAgent

        handler = Mock(return_value="response")
        agent = LiveKitAvatarAgent(handler)

        assert agent.query_handler == handler
        assert agent.simli_api_key == "test-simli-key"
        assert agent.simli_face_id == "test-face-id"
        assert agent.deepgram_api_key == "test-deepgram-key"
        assert agent.cartesia_api_key == "test-cartesia-key"
        assert agent.livekit_url == "wss://test.livekit.cloud"
        assert agent._session is None
        assert agent._avatar is None

    def test_agent_custom_credentials(self, mock_env):
        """Test agent accepts custom credentials."""
        from src.platform.livekit_avatar import LiveKitAvatarAgent

        handler = Mock(return_value="response")
        agent = LiveKitAvatarAgent(
            handler,
            simli_api_key="custom-simli",
            simli_face_id="custom-face",
            deepgram_api_key="custom-deepgram",
            cartesia_api_key="custom-cartesia",
            livekit_url="wss://custom.livekit.cloud",
            livekit_api_key="custom-key",
            livekit_api_secret="custom-secret",
        )

        assert agent.simli_api_key == "custom-simli"
        assert agent.simli_face_id == "custom-face"
        assert agent.deepgram_api_key == "custom-deepgram"
        assert agent.cartesia_api_key == "custom-cartesia"
        assert agent.livekit_url == "wss://custom.livekit.cloud"

    def test_agent_missing_simli_key(self):
        """Test agent raises error without SIMLI_API_KEY."""
        from src.platform.livekit_avatar import LiveKitAvatarAgent

        with patch.dict(os.environ, {
            "DEEPGRAM_API_KEY": "test",
            "CARTESIA_API_KEY": "test",
            "LIVEKIT_URL": "wss://test",
            "LIVEKIT_API_KEY": "test",
            "LIVEKIT_API_SECRET": "test",
        }, clear=True):
            handler = Mock(return_value="response")

            with pytest.raises(ValueError, match="SIMLI_API_KEY"):
                LiveKitAvatarAgent(handler)

    def test_agent_missing_deepgram_key(self):
        """Test agent raises error without DEEPGRAM_API_KEY."""
        from src.platform.livekit_avatar import LiveKitAvatarAgent

        with patch.dict(os.environ, {
            "SIMLI_API_KEY": "test",
            "CARTESIA_API_KEY": "test",
            "LIVEKIT_URL": "wss://test",
            "LIVEKIT_API_KEY": "test",
            "LIVEKIT_API_SECRET": "test",
        }, clear=True):
            handler = Mock(return_value="response")

            with pytest.raises(ValueError, match="DEEPGRAM_API_KEY"):
                LiveKitAvatarAgent(handler)

    def test_agent_missing_livekit_url(self):
        """Test agent raises error without LIVEKIT_URL."""
        from src.platform.livekit_avatar import LiveKitAvatarAgent

        with patch.dict(os.environ, {
            "SIMLI_API_KEY": "test",
            "DEEPGRAM_API_KEY": "test",
            "CARTESIA_API_KEY": "test",
            "LIVEKIT_API_KEY": "test",
            "LIVEKIT_API_SECRET": "test",
        }, clear=True):
            handler = Mock(return_value="response")

            with pytest.raises(ValueError, match="LIVEKIT_URL"):
                LiveKitAvatarAgent(handler)

    def test_default_face_id(self):
        """Test default face ID is used when not specified."""
        from src.platform.livekit_avatar import LiveKitAvatarAgent

        with patch.dict(os.environ, {
            "SIMLI_API_KEY": "test",
            "DEEPGRAM_API_KEY": "test",
            "CARTESIA_API_KEY": "test",
            "LIVEKIT_URL": "wss://test",
            "LIVEKIT_API_KEY": "test",
            "LIVEKIT_API_SECRET": "test",
        }, clear=True):
            handler = Mock(return_value="response")
            agent = LiveKitAvatarAgent(handler)

            # Default from code
            assert agent.simli_face_id == "tmp9i8bbq7c"

    def test_get_video_track_none_when_not_running(self, mock_env):
        """Test get_video_track returns None when not running."""
        from src.platform.livekit_avatar import LiveKitAvatarAgent

        handler = Mock(return_value="response")
        agent = LiveKitAvatarAgent(handler)

        assert agent.get_video_track() is None

    def test_get_audio_track_none_when_not_running(self, mock_env):
        """Test get_audio_track returns None when not running."""
        from src.platform.livekit_avatar import LiveKitAvatarAgent

        handler = Mock(return_value="response")
        agent = LiveKitAvatarAgent(handler)

        assert agent.get_audio_track() is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, mock_env):
        """Test stop is safe when not started."""
        from src.platform.livekit_avatar import LiveKitAvatarAgent

        handler = Mock(return_value="response")
        agent = LiveKitAvatarAgent(handler)

        # Should not raise
        await agent.stop()


# ============================================================================
# Module-Level Function Tests
# ============================================================================

@requires_livekit
@pytest.mark.xfail(reason="create_avatar_worker function not yet implemented")
class TestCreateAvatarWorker:
    """Tests for create_avatar_worker function."""

    def test_creates_worker_options(self):
        """Test worker options are created correctly."""
        with patch.dict(os.environ, {
            "SIMLI_API_KEY": "test",
            "DEEPGRAM_API_KEY": "test",
            "CARTESIA_API_KEY": "test",
            "LIVEKIT_URL": "wss://test.livekit.cloud",
            "LIVEKIT_API_KEY": "test-key",
            "LIVEKIT_API_SECRET": "test-secret",
        }):
            from src.platform.livekit_avatar import create_avatar_worker

            handler = Mock(return_value="response")
            worker_opts = create_avatar_worker(handler)

            assert worker_opts is not None
            assert worker_opts.api_key == "test-key"
            assert worker_opts.api_secret == "test-secret"
            assert worker_opts.ws_url == "wss://test.livekit.cloud"


class TestCreateZoomAvatarSession:
    """Tests for create_zoom_avatar_session function."""

    @pytest.mark.asyncio
    async def test_creates_session_components(self):
        """Test session creation returns bot and bridge."""
        with patch.dict(os.environ, {
            "ZOOM_SDK_CLIENT_ID": "test-id",
            "ZOOM_SDK_CLIENT_SECRET": "test-secret",
        }):
            from src.platform.zoom_bot import create_zoom_avatar_session, ZoomMeetingBot

            with patch.object(ZoomMeetingBot, "join_meeting", new_callable=AsyncMock) as mock_join:
                mock_join.return_value = True

                bot, bridge = await create_zoom_avatar_session("123456789")

                assert bot is not None
                assert bridge is not None
                mock_join.assert_called_once_with("123456789", "")


# ============================================================================
# Package Import Tests
# ============================================================================

class TestPackageImports:
    """Tests for package __init__.py exports."""

    def test_package_exports_zoom_bot(self):
        """Test ZoomMeetingBot is exported."""
        from src.platform import ZoomMeetingBot

        assert ZoomMeetingBot is not None

    @requires_livekit
    @pytest.mark.xfail(reason="LiveKitAvatarAgent class not yet implemented")
    def test_package_exports_livekit_agent(self):
        """Test LiveKitAvatarAgent is exported when livekit is installed."""
        from src.platform import LiveKitAvatarAgent

        assert LiveKitAvatarAgent is not None

    def test_package_handles_missing_livekit(self):
        """Test package loads even without livekit."""
        # Import should succeed regardless of livekit availability
        import src.platform as platform

        assert hasattr(platform, "ZoomMeetingBot")
        assert hasattr(platform, "LiveKitAvatarAgent")
        # LiveKitAvatarAgent may be None if livekit not installed
        if not LIVEKIT_AVAILABLE:
            assert platform.LiveKitAvatarAgent is None
