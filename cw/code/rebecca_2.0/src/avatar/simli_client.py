"""
Simli API client for real-time avatar generation.

Simli provides <300ms speech-to-video latency for
lip-synced avatar animations.

Supports both REST API for simple use cases and
WebSocket API for streaming low-latency applications.

Includes circuit breaker protection and rate limit tracking
per CLAUDE.md guidelines.
"""
import base64
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Generator
from enum import Enum

import requests

from ..bot.circuit_breaker import get_circuit_breaker, CircuitOpenError
from ..rate_limits.session_limits import record_call, can_call_service


class SimliSessionState(Enum):
    """State of a Simli avatar session."""
    CREATED = "created"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STREAMING = "streaming"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"


@dataclass
class SimliSession:
    """
    Represents an active Simli avatar session.

    Sessions maintain a persistent connection for
    streaming audio and receiving video frames.
    """
    session_id: str
    face_id: str
    state: SimliSessionState = SimliSessionState.CREATED
    created_at: float = field(default_factory=time.time)
    frames_sent: int = 0
    frames_received: int = 0
    error: Optional[str] = None

    def is_active(self) -> bool:
        """Check if session is in an active state."""
        return self.state in (
            SimliSessionState.CONNECTED,
            SimliSessionState.STREAMING
        )


class SimliClient:
    """
    Client for Simli real-time avatar API.

    Features:
    - WebSocket streaming for low-latency (<300ms)
    - REST API fallback
    - Graceful degradation on errors
    - Session management
    """

    API_BASE = "https://api.simli.ai"
    WS_BASE = "wss://api.simli.ai/ws"

    # Default face IDs (Simli provides these)
    FACES = {
        "professional_male": "tmp9i8bbq7c",      # Business professional male
        "professional_female": "tmpvh1h0qr3",    # Business professional female
        "friendly_male": "tmp2wqz9gu4",          # Casual friendly male
        "friendly_female": "tmpkcj0d8z1",        # Casual friendly female
    }

    def __init__(
        self,
        api_key: str,
        face_id: str = None,
        logger: logging.Logger = None,
        timeout: float = 10.0,
        max_retries: int = 3
    ):
        """
        Initialize Simli client.

        Args:
            api_key: Simli API key
            face_id: Avatar face ID (use FACES dict for presets)
            logger: Logger instance
            timeout: Request timeout in seconds
            max_retries: Max retry attempts for failed requests
        """
        self.api_key = api_key
        self.face_id = face_id or self.FACES["professional_female"]
        self.logger = logger or logging.getLogger("qa_agent")
        self.timeout = timeout
        self.max_retries = max_retries

        self._active_session: Optional[SimliSession] = None
        self._ws = None
        self._ws_thread = None
        # Bounded queue to prevent memory growth if frames arrive faster than consumed
        self._video_queue: queue.Queue = queue.Queue(maxsize=100)
        self._running = False

        # Circuit breaker for API calls (Council fix: protect against cascading failures)
        # Lower threshold (3) since Simli has strict rate limits (2 calls/session)
        self._circuit_breaker = get_circuit_breaker(
            "simli",
            failure_threshold=3,
            recovery_timeout=60,  # Longer timeout since rate limits are strict
            logger=self.logger
        )

    def create_session(self) -> SimliSession:
        """
        Create a new avatar session.

        Returns:
            SimliSession object for tracking the session
        """
        session_id = f"simli-{int(time.time() * 1000)}"

        session = SimliSession(
            session_id=session_id,
            face_id=self.face_id,
            state=SimliSessionState.CREATED
        )

        self._active_session = session
        self.logger.info(f"Created Simli session: {session_id}")

        return session

    def connect_websocket(
        self,
        session: SimliSession,
        on_video_frame: Callable[[bytes], None] = None
    ) -> bool:
        """
        Connect WebSocket for streaming avatar generation.

        Args:
            session: Session to connect
            on_video_frame: Callback for received video frames

        Returns:
            True if connected successfully
        """
        try:
            import websocket

            session.state = SimliSessionState.CONNECTING

            ws_url = f"{self.WS_BASE}/stream?api_key={self.api_key}&face_id={self.face_id}"

            self._ws = websocket.WebSocketApp(
                ws_url,
                on_open=lambda ws: self._on_ws_open(ws, session),
                on_message=lambda ws, msg: self._on_ws_message(ws, msg, session, on_video_frame),
                on_error=lambda ws, err: self._on_ws_error(ws, err, session),
                on_close=lambda ws, code, msg: self._on_ws_close(ws, code, msg, session)
            )

            self._running = True
            self._ws_thread = threading.Thread(
                target=self._ws.run_forever,
                daemon=True
            )
            self._ws_thread.start()

            # Wait for connection
            timeout_at = time.time() + self.timeout
            while session.state == SimliSessionState.CONNECTING:
                if time.time() > timeout_at:
                    session.state = SimliSessionState.ERROR
                    session.error = "Connection timeout"
                    # Clean up the running thread on timeout
                    self._running = False
                    if self._ws:
                        try:
                            self._ws.close()
                        except Exception:
                            pass
                    return False
                time.sleep(0.1)

            return session.state == SimliSessionState.CONNECTED

        except ImportError:
            self.logger.warning("websocket-client not installed, using REST fallback")
            session.state = SimliSessionState.CONNECTED
            return True
        except Exception as e:
            self.logger.error(f"WebSocket connection error: {e}")
            session.state = SimliSessionState.ERROR
            session.error = str(e)
            return False

    def _on_ws_open(self, ws, session: SimliSession):
        """Handle WebSocket connection open."""
        session.state = SimliSessionState.CONNECTED
        self.logger.debug(f"Simli WebSocket connected: {session.session_id}")

    def _on_ws_message(
        self,
        ws,
        message,
        session: SimliSession,
        on_video_frame: Callable[[bytes], None]
    ):
        """Handle incoming WebSocket message (video frame)."""
        try:
            if isinstance(message, bytes):
                # Binary frame - video data
                session.frames_received += 1
                if on_video_frame:
                    on_video_frame(message)
                # Non-blocking queue put with overflow handling
                # Council fix: Use put_nowait() to avoid blocking WebSocket thread
                try:
                    self._video_queue.put_nowait(message)
                except queue.Full:
                    # Drop oldest frame to make room (overflow policy)
                    try:
                        self._video_queue.get_nowait()
                        self._video_queue.put_nowait(message)
                        self.logger.debug("Video frame queue full, dropped oldest frame")
                    except queue.Empty:
                        pass
            else:
                # JSON message - status/error
                data = json.loads(message)
                if data.get("error"):
                    self.logger.error(f"Simli error: {data['error']}")
                    session.error = data["error"]
        except Exception as e:
            self.logger.error(f"Error processing Simli message: {e}")

    def _on_ws_error(self, ws, error, session: SimliSession):
        """Handle WebSocket error."""
        self.logger.error(f"Simli WebSocket error: {error}")
        session.state = SimliSessionState.ERROR
        session.error = str(error)

    def _on_ws_close(self, ws, close_code, close_msg, session: SimliSession):
        """Handle WebSocket close."""
        self.logger.debug(f"Simli WebSocket closed: {close_code} - {close_msg}")
        if session.state != SimliSessionState.ERROR:
            session.state = SimliSessionState.CLOSED

    def send_audio(
        self,
        session: SimliSession,
        audio_data: bytes,
        sample_rate: int = 24000
    ) -> bool:
        """
        Send audio data for avatar lip-sync.

        Args:
            session: Active session
            audio_data: PCM audio bytes (16-bit)
            sample_rate: Audio sample rate

        Returns:
            True if sent successfully
        """
        if not session.is_active():
            self.logger.warning(f"Cannot send audio - session not active: {session.state}")
            return False

        try:
            if self._ws and self._ws.sock:
                # WebSocket streaming
                session.state = SimliSessionState.STREAMING

                # Send audio as binary with header
                header = json.dumps({
                    "type": "audio",
                    "sample_rate": sample_rate,
                    "format": "pcm_s16le"
                }).encode()

                # Protocol: 4-byte header length + header + audio
                header_len = len(header).to_bytes(4, 'big')
                self._ws.send(header_len + header + audio_data, opcode=0x2)

                session.frames_sent += 1
                return True
            else:
                # REST fallback
                return self._send_audio_rest(session, audio_data, sample_rate)

        except Exception as e:
            self.logger.error(f"Error sending audio to Simli: {e}")
            return False

    def _send_audio_rest(
        self,
        session: SimliSession,
        audio_data: bytes,
        sample_rate: int
    ) -> bool:
        """Send audio via REST API (higher latency fallback)."""
        # Council fix: Check rate limits before API call
        if not can_call_service("simli"):
            self.logger.error("Simli rate limit reached, cannot send audio via REST")
            return False

        # Council fix: Check circuit breaker
        if not self._circuit_breaker.can_execute():
            self.logger.warning("Simli circuit breaker open, skipping REST call")
            return False

        try:
            response = requests.post(
                f"{self.API_BASE}/v1/audio-to-video",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "face_id": self.face_id,
                    "audio": base64.b64encode(audio_data).decode(),
                    "sample_rate": sample_rate,
                    "format": "pcm_s16le"
                },
                timeout=self.timeout
            )

            response.raise_for_status()
            result = response.json()

            # Record successful API call
            record_call("simli")
            self._circuit_breaker.record_success()

            # Queue video frames (non-blocking)
            if result.get("video"):
                video_data = base64.b64decode(result["video"])
                try:
                    self._video_queue.put_nowait(video_data)
                except queue.Full:
                    try:
                        self._video_queue.get_nowait()
                        self._video_queue.put_nowait(video_data)
                    except queue.Empty:
                        pass
                session.frames_received += 1

            session.frames_sent += 1
            return True

        except requests.RequestException as e:
            self.logger.error(f"Simli REST API error: {e}")
            self._circuit_breaker.record_failure()
            return False

    def get_video_frame(self, timeout: float = 1.0) -> Optional[bytes]:
        """
        Get next video frame from queue.

        Args:
            timeout: Max wait time in seconds

        Returns:
            Video frame bytes, or None if timeout
        """
        try:
            return self._video_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_video_frames(self) -> Generator[bytes, None, None]:
        """
        Generator that yields video frames as they arrive.

        Yields:
            Video frame bytes
        """
        while self._running or not self._video_queue.empty():
            frame = self.get_video_frame(timeout=0.1)
            if frame:
                yield frame

    def close_session(self, session: SimliSession):
        """
        Close an avatar session.

        Args:
            session: Session to close
        """
        if session.state == SimliSessionState.CLOSED:
            return

        session.state = SimliSessionState.CLOSING
        self._running = False

        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=2)

        session.state = SimliSessionState.CLOSED
        self.logger.info(
            f"Closed Simli session {session.session_id}: "
            f"{session.frames_sent} sent, {session.frames_received} received"
        )

    def generate_video_sync(
        self,
        audio_data: bytes,
        sample_rate: int = 24000
    ) -> Optional[bytes]:
        """
        Generate avatar video synchronously (simple API).

        This is a convenience method for one-shot video generation.
        For streaming, use create_session() + send_audio().

        Args:
            audio_data: PCM audio bytes
            sample_rate: Audio sample rate

        Returns:
            Video bytes, or None on error
        """
        # Council fix: Check rate limits before API call
        if not can_call_service("simli"):
            self.logger.error("Simli rate limit reached, cannot generate video")
            return None

        # Council fix: Check circuit breaker
        if not self._circuit_breaker.can_execute():
            self.logger.warning("Simli circuit breaker open, skipping video generation")
            return None

        try:
            response = requests.post(
                f"{self.API_BASE}/v1/audio-to-video",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "face_id": self.face_id,
                    "audio": base64.b64encode(audio_data).decode(),
                    "sample_rate": sample_rate,
                    "format": "pcm_s16le",
                    "output_format": "mp4"
                },
                timeout=30  # Video generation can take longer
            )

            response.raise_for_status()
            result = response.json()

            # Record successful API call
            record_call("simli")
            self._circuit_breaker.record_success()

            if result.get("video"):
                return base64.b64decode(result["video"])
            elif result.get("video_url"):
                # Fetch video from URL
                video_response = requests.get(result["video_url"], timeout=30)
                video_response.raise_for_status()
                return video_response.content

            return None

        except requests.RequestException as e:
            self.logger.error(f"Simli sync generation error: {e}")
            self._circuit_breaker.record_failure()
            return None

    def get_session_stats(self, session: SimliSession) -> dict:
        """
        Get statistics for a session.

        Args:
            session: Session to get stats for

        Returns:
            Dict with session statistics
        """
        return {
            "session_id": session.session_id,
            "state": session.state.value,
            "face_id": session.face_id,
            "created_at": session.created_at,
            "duration_seconds": time.time() - session.created_at,
            "frames_sent": session.frames_sent,
            "frames_received": session.frames_received,
            "error": session.error
        }


class MockSimliClient(SimliClient):
    """
    Mock Simli client for testing.

    Generates placeholder video frames without calling the API.
    """

    def __init__(self, *args, **kwargs):
        """Initialize mock client (ignores API key)."""
        super().__init__(api_key="mock-key", *args, **kwargs)
        self._mock_frame_count = 0

    def connect_websocket(
        self,
        session: SimliSession,
        on_video_frame: Callable[[bytes], None] = None
    ) -> bool:
        """Mock WebSocket connection - always succeeds."""
        session.state = SimliSessionState.CONNECTED
        self._running = True
        return True

    def send_audio(
        self,
        session: SimliSession,
        audio_data: bytes,
        sample_rate: int = 24000
    ) -> bool:
        """Mock audio send - generates fake video frame."""
        if not session.is_active():
            return False

        session.state = SimliSessionState.STREAMING
        session.frames_sent += 1

        # Generate mock video frame (1x1 black pixel JPEG)
        mock_frame = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46,
            0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
            0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08,
            0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C,
            0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D,
            0x1A, 0x1C, 0x1C, 0x20, 0x24, 0x2E, 0x27, 0x20,
            0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27,
            0x39, 0x3D, 0x38, 0x32, 0x3C, 0x2E, 0x33, 0x34,
            0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
            0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4,
            0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01,
            0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04,
            0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0xFF,
            0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
            0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04,
            0x00, 0x00, 0x01, 0x7D, 0x01, 0x02, 0x03, 0x00,
            0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
            0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32,
            0x81, 0x91, 0xA1, 0x08, 0x23, 0x42, 0xB1, 0xC1,
            0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
            0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A,
            0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x34, 0x35,
            0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
            0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55,
            0x56, 0x57, 0x58, 0x59, 0x5A, 0x63, 0x64, 0x65,
            0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
            0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85,
            0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00,
            0x3F, 0x00, 0xFB, 0xD3, 0xFF, 0xD9
        ])

        self._video_queue.put(mock_frame)
        session.frames_received += 1
        self._mock_frame_count += 1

        return True

    def generate_video_sync(
        self,
        audio_data: bytes,
        sample_rate: int = 24000
    ) -> Optional[bytes]:
        """Mock sync generation - returns minimal MP4."""
        # Return a minimal valid MP4 header (not playable but valid structure)
        return b"mock_video_data_" + str(self._mock_frame_count).encode()
