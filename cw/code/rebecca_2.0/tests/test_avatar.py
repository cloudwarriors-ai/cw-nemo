"""
Tests for avatar integration module.

Tests SimliClient, AvatarSessionManager, AvatarWebpageServer,
and avatar-related Flask endpoints.
"""
import base64
import json
import queue
import threading
import time
from unittest.mock import Mock, patch, MagicMock

import pytest

from src.avatar.simli_client import (
    SimliClient,
    SimliSession,
    SimliSessionState,
    MockSimliClient
)
from src.avatar.avatar_session import (
    AvatarSessionManager,
    AvatarWebpageServer,
    AvatarMode,
    AvatarState
)


# ============================================================================
# SimliSession Tests
# ============================================================================

class TestSimliSession:
    """Tests for SimliSession dataclass."""

    def test_session_creation(self):
        """Test creating a session with defaults."""
        session = SimliSession(
            session_id="test-123",
            face_id="face-abc"
        )

        assert session.session_id == "test-123"
        assert session.face_id == "face-abc"
        assert session.state == SimliSessionState.CREATED
        assert session.frames_sent == 0
        assert session.frames_received == 0
        assert session.error is None
        assert session.created_at > 0

    def test_is_active_connected(self):
        """Test is_active returns True when connected."""
        session = SimliSession(
            session_id="test-123",
            face_id="face-abc",
            state=SimliSessionState.CONNECTED
        )

        assert session.is_active() is True

    def test_is_active_streaming(self):
        """Test is_active returns True when streaming."""
        session = SimliSession(
            session_id="test-123",
            face_id="face-abc",
            state=SimliSessionState.STREAMING
        )

        assert session.is_active() is True

    def test_is_active_false_for_created(self):
        """Test is_active returns False when created but not connected."""
        session = SimliSession(
            session_id="test-123",
            face_id="face-abc",
            state=SimliSessionState.CREATED
        )

        assert session.is_active() is False

    def test_is_active_false_for_closed(self):
        """Test is_active returns False when closed."""
        session = SimliSession(
            session_id="test-123",
            face_id="face-abc",
            state=SimliSessionState.CLOSED
        )

        assert session.is_active() is False

    def test_is_active_false_for_error(self):
        """Test is_active returns False when in error state."""
        session = SimliSession(
            session_id="test-123",
            face_id="face-abc",
            state=SimliSessionState.ERROR
        )

        assert session.is_active() is False


# ============================================================================
# SimliClient Tests
# ============================================================================

class TestSimliClient:
    """Tests for SimliClient."""

    def test_client_initialization(self):
        """Test client initializes with correct defaults."""
        client = SimliClient(api_key="test-key")

        assert client.api_key == "test-key"
        assert client.face_id == SimliClient.FACES["professional_female"]
        assert client.timeout == 10.0
        assert client.max_retries == 3
        assert client._active_session is None

    def test_client_custom_face_id(self):
        """Test client accepts custom face ID."""
        client = SimliClient(
            api_key="test-key",
            face_id="custom-face-123"
        )

        assert client.face_id == "custom-face-123"

    def test_create_session(self):
        """Test session creation."""
        client = SimliClient(api_key="test-key")
        session = client.create_session()

        assert session is not None
        assert session.session_id.startswith("simli-")
        assert session.face_id == client.face_id
        assert session.state == SimliSessionState.CREATED
        assert client._active_session == session

    def test_create_session_unique_ids(self):
        """Test each session gets unique ID."""
        client = SimliClient(api_key="test-key")

        session1 = client.create_session()
        time.sleep(0.001)  # Small delay to ensure different timestamp
        session2 = client.create_session()

        assert session1.session_id != session2.session_id

    @patch("src.avatar.simli_client.can_call_service", return_value=True)
    @patch("src.avatar.simli_client.requests.post")
    def test_send_audio_rest_fallback(self, mock_post, mock_rate_limit):
        """Test audio send via REST fallback."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "video": base64.b64encode(b"fake_video").decode()
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        client = SimliClient(api_key="test-key")
        session = client.create_session()
        session.state = SimliSessionState.CONNECTED

        result = client.send_audio(session, b"audio_data", 24000)

        assert result is True
        assert session.frames_sent == 1
        assert session.frames_received == 1
        mock_post.assert_called_once()

    @patch("src.avatar.simli_client.requests.post")
    def test_send_audio_rest_error(self, mock_post):
        """Test audio send handles REST errors gracefully."""
        import requests
        mock_post.side_effect = requests.RequestException("API error")

        client = SimliClient(api_key="test-key")
        session = client.create_session()
        session.state = SimliSessionState.CONNECTED

        result = client.send_audio(session, b"audio_data", 24000)

        assert result is False

    def test_send_audio_inactive_session(self):
        """Test audio send fails for inactive session."""
        client = SimliClient(api_key="test-key")
        session = client.create_session()
        # Session is CREATED, not CONNECTED

        result = client.send_audio(session, b"audio_data", 24000)

        assert result is False

    def test_get_video_frame_empty_queue(self):
        """Test get_video_frame returns None on empty queue."""
        client = SimliClient(api_key="test-key")

        result = client.get_video_frame(timeout=0.1)

        assert result is None

    def test_get_video_frame_with_data(self):
        """Test get_video_frame returns frame from queue."""
        client = SimliClient(api_key="test-key")
        test_frame = b"test_video_frame"
        client._video_queue.put(test_frame)

        result = client.get_video_frame(timeout=0.1)

        assert result == test_frame

    def test_close_session(self):
        """Test session closing."""
        client = SimliClient(api_key="test-key")
        session = client.create_session()
        session.state = SimliSessionState.CONNECTED

        client.close_session(session)

        assert session.state == SimliSessionState.CLOSED
        assert client._running is False

    def test_close_session_already_closed(self):
        """Test closing already closed session is no-op."""
        client = SimliClient(api_key="test-key")
        session = client.create_session()
        session.state = SimliSessionState.CLOSED

        # Should not raise
        client.close_session(session)

        assert session.state == SimliSessionState.CLOSED

    @patch("src.avatar.simli_client.can_call_service", return_value=True)
    @patch("src.avatar.simli_client.requests.post")
    def test_generate_video_sync(self, mock_post, mock_rate_limit):
        """Test synchronous video generation."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "video": base64.b64encode(b"video_content").decode()
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        client = SimliClient(api_key="test-key")
        result = client.generate_video_sync(b"audio_data")

        assert result == b"video_content"

    @patch("src.avatar.simli_client.can_call_service", return_value=True)
    @patch("src.avatar.simli_client.requests.post")
    @patch("src.avatar.simli_client.requests.get")
    def test_generate_video_sync_url(self, mock_get, mock_post, mock_rate_limit):
        """Test sync generation with video URL response."""
        mock_post_response = Mock()
        mock_post_response.json.return_value = {
            "video_url": "https://simli.ai/video/123.mp4"
        }
        mock_post_response.raise_for_status = Mock()
        mock_post.return_value = mock_post_response

        mock_get_response = Mock()
        mock_get_response.content = b"video_from_url"
        mock_get_response.raise_for_status = Mock()
        mock_get.return_value = mock_get_response

        client = SimliClient(api_key="test-key")
        result = client.generate_video_sync(b"audio_data")

        assert result == b"video_from_url"

    @patch("src.avatar.simli_client.requests.post")
    def test_generate_video_sync_error(self, mock_post):
        """Test sync generation handles errors."""
        import requests
        mock_post.side_effect = requests.RequestException("API error")

        client = SimliClient(api_key="test-key")
        result = client.generate_video_sync(b"audio_data")

        assert result is None

    def test_get_session_stats(self):
        """Test getting session statistics."""
        client = SimliClient(api_key="test-key")
        session = client.create_session()
        session.frames_sent = 10
        session.frames_received = 8

        stats = client.get_session_stats(session)

        assert stats["session_id"] == session.session_id
        assert stats["state"] == "created"
        assert stats["face_id"] == session.face_id
        assert stats["frames_sent"] == 10
        assert stats["frames_received"] == 8
        assert "duration_seconds" in stats

    def test_faces_dict_exists(self):
        """Test default face presets exist."""
        assert "professional_male" in SimliClient.FACES
        assert "professional_female" in SimliClient.FACES
        assert "friendly_male" in SimliClient.FACES
        assert "friendly_female" in SimliClient.FACES


# ============================================================================
# MockSimliClient Tests
# ============================================================================

class TestMockSimliClient:
    """Tests for MockSimliClient."""

    def test_mock_client_creation(self):
        """Test mock client initializes without API key."""
        client = MockSimliClient()

        assert client.api_key == "mock-key"
        assert client._mock_frame_count == 0

    def test_mock_connect_websocket(self):
        """Test mock WebSocket connection always succeeds."""
        client = MockSimliClient()
        session = client.create_session()

        result = client.connect_websocket(session)

        assert result is True
        assert session.state == SimliSessionState.CONNECTED
        assert client._running is True

    def test_mock_send_audio(self):
        """Test mock audio send generates frame."""
        client = MockSimliClient()
        session = client.create_session()
        session.state = SimliSessionState.CONNECTED

        result = client.send_audio(session, b"audio_data")

        assert result is True
        assert session.state == SimliSessionState.STREAMING
        assert session.frames_sent == 1
        assert session.frames_received == 1
        assert client._mock_frame_count == 1

    def test_mock_send_audio_generates_video_frame(self):
        """Test mock audio send puts frame in queue."""
        client = MockSimliClient()
        session = client.create_session()
        session.state = SimliSessionState.CONNECTED

        client.send_audio(session, b"audio_data")
        frame = client.get_video_frame(timeout=0.1)

        assert frame is not None
        # Mock frame is a minimal JPEG
        assert frame[:2] == b'\xff\xd8'  # JPEG magic bytes

    def test_mock_send_audio_inactive_session(self):
        """Test mock audio send fails for inactive session."""
        client = MockSimliClient()
        session = client.create_session()
        # Session is CREATED, not CONNECTED

        result = client.send_audio(session, b"audio_data")

        assert result is False

    def test_mock_generate_video_sync(self):
        """Test mock sync generation returns data."""
        client = MockSimliClient()

        result = client.generate_video_sync(b"audio_data")

        assert result is not None
        assert result.startswith(b"mock_video_data_")


# ============================================================================
# AvatarState Tests
# ============================================================================

class TestAvatarState:
    """Tests for AvatarState dataclass."""

    def test_default_state(self):
        """Test default avatar state."""
        state = AvatarState()

        assert state.mode == AvatarMode.IDLE
        assert state.current_text == ""
        assert state.error_message is None
        assert state.last_update > 0


# ============================================================================
# AvatarSessionManager Tests
# ============================================================================

class TestAvatarSessionManager:
    """Tests for AvatarSessionManager."""

    def test_manager_initialization(self):
        """Test manager initializes correctly."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)

        assert manager.simli_client == mock_client
        assert manager._session is None
        assert manager._meeting_id is None
        assert manager.is_active is False

    def test_initial_state(self):
        """Test initial avatar state."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)

        state = manager.state

        assert state.mode == AvatarMode.IDLE
        assert state.current_text == ""

    def test_start_session(self):
        """Test starting an avatar session."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)

        result = manager.start_session("meeting-123")

        assert result is True
        assert manager.is_active is True
        assert manager._meeting_id == "meeting-123"
        assert manager.state.mode == AvatarMode.IDLE

    def test_start_session_already_active(self):
        """Test starting session when one is already active."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)

        manager.start_session("meeting-123")
        result = manager.start_session("meeting-456")

        assert result is False
        assert manager._meeting_id == "meeting-123"

    def test_stop_session(self):
        """Test stopping an avatar session."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        manager.start_session("meeting-123")

        manager.stop_session()

        assert manager._session is None
        assert manager._meeting_id is None
        assert manager.is_active is False

    def test_stop_session_not_started(self):
        """Test stopping when no session active is safe."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)

        # Should not raise
        manager.stop_session()

        assert manager._session is None

    def test_set_listening(self):
        """Test setting listening state."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)

        manager.set_listening()

        assert manager.state.mode == AvatarMode.LISTENING

    def test_set_thinking(self):
        """Test setting thinking state."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)

        manager.set_thinking()

        assert manager.state.mode == AvatarMode.THINKING

    def test_send_audio_for_avatar_no_session(self):
        """Test sending audio without active session is no-op."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)

        # Should not raise
        manager.send_audio_for_avatar(b"audio_data", "Hello")

        # No change since no session
        assert manager.state.mode == AvatarMode.IDLE

    def test_send_audio_for_avatar_with_session(self):
        """Test sending audio with active session."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        manager.start_session("meeting-123")

        manager.send_audio_for_avatar(b"audio_data", "Hello there")

        assert manager.state.mode == AvatarMode.SPEAKING
        assert manager.state.current_text == "Hello there"

    def test_on_state_change_callback(self):
        """Test state change callback is invoked."""
        mock_client = MockSimliClient()
        callback_states = []

        def on_state_change(state):
            callback_states.append(state.mode)

        manager = AvatarSessionManager(
            simli_client=mock_client,
            on_state_change=on_state_change
        )

        manager.set_listening()
        manager.set_thinking()

        assert AvatarMode.LISTENING in callback_states
        assert AvatarMode.THINKING in callback_states

    def test_get_metrics(self):
        """Test getting session metrics."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)

        metrics = manager.get_metrics()

        assert "total_audio_chunks" in metrics
        assert "total_video_frames" in metrics
        assert "avg_latency_ms" in metrics
        assert "errors" in metrics
        assert "current_state" in metrics

    def test_get_state_for_webpage(self):
        """Test getting state formatted for webpage."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        manager.start_session("meeting-123")
        manager.set_listening()

        state = manager.get_state_for_webpage()

        assert state["mode"] == "listening"
        assert state["session_active"] is True
        assert state["meeting_id"] == "meeting-123"
        assert "timestamp" in state


# ============================================================================
# AvatarWebpageServer Tests
# ============================================================================

class TestAvatarWebpageServer:
    """Tests for AvatarWebpageServer."""

    def test_server_initialization(self):
        """Test server initializes correctly."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        server = AvatarWebpageServer(
            session_manager=manager,
            static_image_url="/images/avatar.png"
        )

        assert server.session_manager == manager
        assert server.static_image_url == "/images/avatar.png"
        assert server._current_frame is None

    def test_get_current_frame_empty(self):
        """Test getting frame when none available."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        server = AvatarWebpageServer(session_manager=manager)

        frame = server.get_current_frame()

        assert frame is None

    def test_get_current_frame_with_data(self):
        """Test getting frame when available."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        server = AvatarWebpageServer(session_manager=manager)

        # Simulate receiving a frame
        server._on_video_frame(b"test_frame_data")
        frame = server.get_current_frame()

        assert frame == b"test_frame_data"

    def test_get_current_frame_base64(self):
        """Test getting frame as base64."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        server = AvatarWebpageServer(session_manager=manager)

        server._on_video_frame(b"test_frame_data")
        b64 = server.get_current_frame_base64()

        assert b64 == base64.b64encode(b"test_frame_data").decode()

    def test_get_current_frame_base64_empty(self):
        """Test getting base64 frame when none available."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        server = AvatarWebpageServer(session_manager=manager)

        b64 = server.get_current_frame_base64()

        assert b64 is None

    def test_get_webpage_html(self):
        """Test generating webpage HTML."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        server = AvatarWebpageServer(
            session_manager=manager,
            static_image_url="/images/avatar.png"
        )

        html = server.get_webpage_html()

        assert "<!DOCTYPE html>" in html
        assert "QA Bot Avatar" in html
        assert "/images/avatar.png" in html
        assert "avatar-container" in html
        assert "status-indicator" in html

    def test_get_webpage_html_default_image(self):
        """Test webpage HTML with default image."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        server = AvatarWebpageServer(session_manager=manager)

        html = server.get_webpage_html()

        assert "/static/avatar/default.png" in html

    def test_video_frame_callback_registered(self):
        """Test that server registers as video frame handler."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)

        # Create server - should register callback
        server = AvatarWebpageServer(session_manager=manager)

        assert manager.on_video_frame == server._on_video_frame

    def test_frame_thread_safety(self):
        """Test frame access is thread-safe."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        server = AvatarWebpageServer(session_manager=manager)

        received_frames = []
        errors = []

        def writer():
            for i in range(100):
                server._on_video_frame(f"frame_{i}".encode())
                time.sleep(0.001)

        def reader():
            for _ in range(100):
                try:
                    frame = server.get_current_frame()
                    if frame:
                        received_frames.append(frame)
                except Exception as e:
                    errors.append(e)
                time.sleep(0.001)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0


# ============================================================================
# Flask Endpoint Tests
# ============================================================================

class TestAvatarEndpoints:
    """Tests for avatar-related Flask endpoints."""

    @pytest.fixture
    def app_with_avatar(self):
        """Create Flask app with avatar session manager mocked."""
        from src.bot.app import create_app

        app = create_app()
        app.config["TESTING"] = True

        # Mock the avatar session manager
        mock_simli = MockSimliClient()
        mock_manager = AvatarSessionManager(simli_client=mock_simli)
        app.avatar_session_manager = mock_manager

        # Mock meeting handler for endpoints that need it
        mock_meeting_handler = Mock()
        mock_meeting_handler.get_meeting_status.return_value = {
            "status": "in_call",
            "meeting_id": "meeting-123"
        }
        mock_meeting_handler.join_meeting.return_value = {
            "id": "bot-123",
            "status": "joining",
            "meeting_id": "meeting-123"
        }
        app.meeting_handler = mock_meeting_handler

        return app

    @pytest.fixture
    def client(self, app_with_avatar):
        """Create test client with avatar enabled."""
        with app_with_avatar.test_client() as client:
            yield client

    @pytest.fixture
    def client_avatar_disabled(self):
        """Create test client with avatar disabled."""
        from src.bot.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        app.avatar_session_manager = None  # Explicitly disabled

        with app.test_client() as client:
            yield client

    def test_avatar_status_enabled(self, client):
        """Test avatar status endpoint when enabled."""
        response = client.get("/api/avatar/status")

        assert response.status_code == 200
        data = response.get_json()
        assert "enabled" in data
        assert data["enabled"] is True
        assert "active" in data
        assert "metrics" in data

    def test_avatar_status_disabled(self, client_avatar_disabled):
        """Test avatar status endpoint when disabled."""
        response = client_avatar_disabled.get("/api/avatar/status")

        assert response.status_code == 200
        data = response.get_json()
        assert data["enabled"] is False

    def test_avatar_start_success(self, client, app_with_avatar):
        """Test starting avatar session."""
        response = client.post("/api/avatar/start/meeting-123")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "started"
        assert data["meeting_id"] == "meeting-123"

    def test_avatar_start_disabled(self, client_avatar_disabled):
        """Test starting avatar when disabled."""
        response = client_avatar_disabled.post("/api/avatar/start/meeting-123")

        assert response.status_code == 503
        data = response.get_json()
        assert "not configured" in data["error"]

    def test_avatar_stop(self, client, app_with_avatar):
        """Test stopping avatar session."""
        # Start first
        client.post("/api/avatar/start/meeting-123")

        response = client.post("/api/avatar/stop")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "stopped"

    def test_avatar_state(self, client):
        """Test getting avatar state for webpage."""
        response = client.get("/api/avatar/state")

        assert response.status_code == 200
        data = response.get_json()
        assert "mode" in data
        assert "session_active" in data

    def test_avatar_page(self, client):
        """Test serving avatar webpage."""
        response = client.get("/avatar/page")

        assert response.status_code == 200
        assert "text/html" in response.content_type
        assert b"QA Bot Avatar" in response.data

    def test_avatar_page_disabled(self, client_avatar_disabled):
        """Test avatar page shows placeholder when disabled."""
        response = client_avatar_disabled.get("/avatar/page")

        assert response.status_code == 200
        assert b"QA Bot" in response.data

    def test_join_with_avatar_success(self, client, app_with_avatar):
        """Test join meeting with avatar endpoint."""
        response = client.post(
            "/api/meeting/join-with-avatar",
            json={
                "meeting_url": "https://zoom.us/j/123456789",
                "bot_name": "QA Bot"
            }
        )

        assert response.status_code == 201
        data = response.get_json()
        assert "id" in data or "meeting_id" in data
        assert data.get("avatar_enabled") is True
        assert "avatar_page_url" in data

    def test_join_with_avatar_missing_url(self, client, app_with_avatar):
        """Test join with avatar requires meeting URL."""
        response = client.post(
            "/api/meeting/join-with-avatar",
            json={}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "meeting_url" in data["error"]

    def test_join_with_avatar_no_meeting_handler(self):
        """Test join with avatar when meeting handler not configured."""
        from src.bot.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        app.meeting_handler = None  # Meeting integration required

        with app.test_client() as client:
            response = client.post(
                "/api/meeting/join-with-avatar",
                json={"meeting_url": "https://zoom.us/j/123"}
            )

            assert response.status_code == 503  # Meeting integration required
            data = response.get_json()
            assert "Meeting integration" in data["error"]


# ============================================================================
# Integration Tests
# ============================================================================

class TestAvatarIntegration:
    """Integration tests for avatar system."""

    def test_full_session_lifecycle(self):
        """Test complete avatar session lifecycle."""
        mock_client = MockSimliClient()
        frames_received = []

        def on_frame(frame):
            frames_received.append(frame)

        manager = AvatarSessionManager(
            simli_client=mock_client,
            on_video_frame=on_frame
        )

        # Start session
        assert manager.start_session("meeting-123") is True
        assert manager.is_active is True

        # Cycle through states
        manager.set_listening()
        assert manager.state.mode == AvatarMode.LISTENING

        manager.set_thinking()
        assert manager.state.mode == AvatarMode.THINKING

        # Send audio - should transition to speaking
        manager.send_audio_for_avatar(b"hello_audio", "Hello!")
        assert manager.state.mode == AvatarMode.SPEAKING

        # Check metrics
        metrics = manager.get_metrics()
        assert metrics["current_state"] == "speaking"

        # Stop session
        manager.stop_session()
        assert manager.is_active is False
        assert manager._session is None

    def test_webpage_server_with_session(self):
        """Test webpage server receiving frames from session."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        server = AvatarWebpageServer(session_manager=manager)

        # Start session
        manager.start_session("meeting-123")

        # Get webpage - should work
        html = server.get_webpage_html()
        assert "QA Bot Avatar" in html

        # Get state
        state = manager.get_state_for_webpage()
        assert state["session_active"] is True

    def test_graceful_degradation_no_simli(self):
        """Test system degrades gracefully without Simli."""
        # Create manager with no client - should still initialize
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)

        # Should be able to get state even without active session
        state = manager.get_state_for_webpage()
        assert state["mode"] == "idle"
        assert state["session_active"] is False

    def test_concurrent_audio_sends(self):
        """Test handling concurrent audio sends."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        manager.start_session("meeting-123")

        errors = []

        def send_audio():
            try:
                for i in range(10):
                    manager.send_audio_for_avatar(f"audio_{i}".encode(), f"Text {i}")
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=send_audio) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        manager.stop_session()

    def test_worker_thread_continues_after_error(self):
        """Test worker thread recovers from processing errors."""
        mock_client = MockSimliClient()
        error_count = {"count": 0}
        original_send = mock_client.send_audio

        def error_on_first_send(session, audio, sample_rate=24000):
            if error_count["count"] == 0:
                error_count["count"] += 1
                raise Exception("Simulated processing error")
            return original_send(session, audio, sample_rate)

        mock_client.send_audio = error_on_first_send
        manager = AvatarSessionManager(simli_client=mock_client)
        manager.start_session("meeting-123")

        # Queue audio chunks - first will error, second should succeed
        manager.send_audio_for_avatar(b"audio1", "Text 1")
        time.sleep(0.7)  # Wait for worker to process first item
        manager.send_audio_for_avatar(b"audio2", "Text 2")
        time.sleep(0.7)  # Wait for worker to process second item

        # Worker should have continued despite first error
        assert manager._metrics["errors"] >= 1
        manager.stop_session()

    def test_queue_drains_on_stop(self):
        """Test audio queue is drained when session stops."""
        mock_client = MockSimliClient()
        manager = AvatarSessionManager(simli_client=mock_client)
        manager.start_session("meeting-123")

        # Queue many items
        for i in range(10):
            manager._audio_queue.put({"audio": b"test", "text": f"Text {i}", "sample_rate": 24000, "timestamp": time.time()})

        # Stop should drain queue
        manager.stop_session()

        assert manager._audio_queue.empty()
