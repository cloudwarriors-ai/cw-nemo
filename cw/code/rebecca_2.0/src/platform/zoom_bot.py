"""
Zoom Meeting SDK Bot for real-time avatar video streaming.

This module provides a bridge between the LiveKit avatar agent and Zoom meetings
using the Zoom Meeting SDK. It joins meetings as a bot participant and streams
custom video frames from the Simli avatar.

Requirements:
- Linux environment (Zoom Meeting SDK requirement)
- Virtual display (Xvfb) for headless operation
- ZOOM_SDK_CLIENT_ID and ZOOM_SDK_CLIENT_SECRET environment variables

Architecture:
    LiveKit/Simli Avatar → Video Frames → ZoomMeetingBot → Zoom Meeting

IMPORTANT LIMITATION (as of 2025):
    The PyZoomMeetingSDK (zoom-meeting-sdk) Python package currently only
    implements 36 out of 235 SDK objects. Custom video source functionality
    (IZoomSDKVideoSource) is NOT yet available in the Python bindings.

    This implementation is structured to support custom video when bindings
    become available, but currently the video output functionality will not
    work. Audio capture and meeting join/leave work correctly.

    Alternatives for video output:
    1. Use Recall.ai Output Media (current approach in src/meeting/)
    2. Use the C++ SDK directly with Python bindings via ctypes
    3. Wait for PyZoomMeetingSDK to add video source support

    Track progress: https://github.com/noah-duncan/py-zoom-meeting-sdk
"""

import asyncio
import base64
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional
from queue import Queue

# Constants for configuration
VIDEO_QUEUE_SIZE = 30  # ~1 second at 30fps
AUDIO_QUEUE_SIZE = 100  # ~1 second of audio chunks
THREAD_JOIN_TIMEOUT = 5  # seconds
MAX_MEETING_ID_LENGTH = 20
MIN_MEETING_ID_LENGTH = 9

logger = logging.getLogger("qa_agent.zoom_bot")


class ZoomBotState(Enum):
    """Bot connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    IN_WAITING_ROOM = "in_waiting_room"
    IN_MEETING = "in_meeting"
    ERROR = "error"


@dataclass
class ZoomCredentials:
    """Zoom SDK credentials."""
    client_id: str
    client_secret: str
    meeting_id: str
    meeting_password: str = ""
    display_name: str = "QA Bot"


@dataclass
class VideoFrame:
    """Video frame data for streaming to Zoom."""
    data: bytes  # Raw pixel data
    width: int
    height: int
    format: str  # 'yuv420', 'rgb24', 'rgba'
    timestamp_ms: int


class ZoomMeetingBot:
    """
    Zoom Meeting SDK bot for streaming avatar video.

    This bot:
    1. Joins a Zoom meeting using the Meeting SDK
    2. Receives video frames from the LiveKit/Simli avatar
    3. Converts frames to YUV420 format
    4. Streams frames to Zoom as the bot's video feed
    5. Optionally streams audio from TTS

    Note: This requires the zoom-meeting-sdk Python package and
    Linux with a virtual display for headless operation.
    """

    def __init__(
        self,
        client_id: str = None,
        client_secret: str = None,
        display_name: str = "QA Bot",
    ):
        """
        Initialize the Zoom bot.

        Args:
            client_id: Zoom SDK Client ID (or ZOOM_SDK_CLIENT_ID env var)
            client_secret: Zoom SDK Client Secret (or ZOOM_SDK_CLIENT_SECRET env var)
            display_name: Bot display name in meeting
        """
        self.client_id = client_id or os.getenv("ZOOM_SDK_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("ZOOM_SDK_CLIENT_SECRET")
        self.display_name = display_name

        # Validate credentials
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Zoom SDK credentials required. Set ZOOM_SDK_CLIENT_ID and "
                "ZOOM_SDK_CLIENT_SECRET environment variables."
            )

        # Runtime state
        self._state = ZoomBotState.DISCONNECTED
        self._meeting_id: Optional[str] = None
        self._sdk = None
        self._video_sender = None
        self._audio_sender = None

        # Frame queue for async video streaming
        self._video_queue: Queue[VideoFrame] = Queue(maxsize=VIDEO_QUEUE_SIZE)
        self._audio_queue: Queue[bytes] = Queue(maxsize=AUDIO_QUEUE_SIZE)
        self._queue_lock = threading.Lock()  # Protect queue operations
        self._streaming = False
        self._stream_thread: Optional[threading.Thread] = None

        # Callbacks
        self._on_state_change: Optional[Callable[[ZoomBotState], None]] = None
        self._on_participant_joined: Optional[Callable[[str], None]] = None
        self._on_audio_received: Optional[Callable[[bytes], None]] = None

    @property
    def state(self) -> ZoomBotState:
        """Get current bot state."""
        return self._state

    @property
    def is_in_meeting(self) -> bool:
        """Check if bot is actively in a meeting."""
        return self._state == ZoomBotState.IN_MEETING

    def _set_state(self, state: ZoomBotState):
        """Update state and notify callback."""
        old_state = self._state
        self._state = state
        logger.info(f"Zoom bot state: {old_state.value} → {state.value}")
        if self._on_state_change:
            self._on_state_change(state)

    def set_callbacks(
        self,
        on_state_change: Callable[[ZoomBotState], None] = None,
        on_participant_joined: Callable[[str], None] = None,
        on_audio_received: Callable[[bytes], None] = None,
    ):
        """
        Set event callbacks.

        Args:
            on_state_change: Called when bot state changes
            on_participant_joined: Called when participant joins
            on_audio_received: Called when audio is received from meeting
        """
        self._on_state_change = on_state_change
        self._on_participant_joined = on_participant_joined
        self._on_audio_received = on_audio_received

    def _validate_meeting_id(self, meeting_id: str) -> str:
        """
        Validate and normalize meeting ID.

        Args:
            meeting_id: Raw meeting ID input

        Returns:
            Normalized meeting ID (digits only)

        Raises:
            ValueError: If meeting ID is invalid
        """
        if not meeting_id:
            raise ValueError("Meeting ID cannot be empty")

        # Remove common separators (spaces, dashes)
        normalized = re.sub(r'[\s\-]', '', str(meeting_id))

        # Must be numeric
        if not normalized.isdigit():
            raise ValueError(f"Meeting ID must be numeric, got: {meeting_id}")

        # Length validation
        if len(normalized) < MIN_MEETING_ID_LENGTH:
            raise ValueError(f"Meeting ID too short (min {MIN_MEETING_ID_LENGTH} digits)")
        if len(normalized) > MAX_MEETING_ID_LENGTH:
            raise ValueError(f"Meeting ID too long (max {MAX_MEETING_ID_LENGTH} digits)")

        return normalized

    async def join_meeting(
        self,
        meeting_id: str,
        password: str = "",
        timeout_seconds: int = 60,
    ) -> bool:
        """
        Join a Zoom meeting.

        Args:
            meeting_id: Zoom meeting ID
            password: Meeting password (if required)
            timeout_seconds: Max time to wait for join

        Returns:
            True if joined successfully

        Raises:
            ValueError: If meeting_id is invalid
        """
        # Validate and normalize meeting ID
        normalized_id = self._validate_meeting_id(meeting_id)
        self._meeting_id = normalized_id
        self._set_state(ZoomBotState.CONNECTING)

        try:
            # Initialize SDK
            await self._init_sdk()

            # Generate JWT for authentication
            jwt = self._generate_jwt(meeting_id)

            # Join the meeting
            logger.info(f"Joining meeting: {meeting_id}")
            await self._join_with_sdk(meeting_id, password, jwt)

            # Wait for in-meeting state
            start_time = time.time()
            while self._state != ZoomBotState.IN_MEETING:
                if time.time() - start_time > timeout_seconds:
                    raise TimeoutError("Timed out waiting to join meeting")

                if self._state == ZoomBotState.ERROR:
                    raise RuntimeError("Failed to join meeting")

                await asyncio.sleep(0.5)

            # Start video streaming thread
            self._start_streaming()

            logger.info(f"Joined meeting: {meeting_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to join meeting: {e}")
            self._set_state(ZoomBotState.ERROR)
            return False

    async def _init_sdk(self):
        """Initialize the Zoom Meeting SDK."""
        try:
            import zoom_meeting_sdk as zsdk

            # Initialize SDK with credentials
            self._sdk = zsdk.MeetingSDK()
            self._sdk.init(
                client_id=self.client_id,
                client_secret=self.client_secret,
            )

            logger.info("Zoom Meeting SDK initialized")

        except ImportError:
            logger.error(
                "zoom-meeting-sdk not installed. Install with: "
                "pip install zoom-meeting-sdk"
            )
            raise
        except Exception as e:
            logger.error(f"SDK initialization failed: {e}")
            raise

    def _generate_jwt(self, meeting_id: str) -> str:
        """
        Generate JWT for meeting authentication.

        Args:
            meeting_id: The meeting ID to join

        Returns:
            JWT string for authentication
        """
        import hmac
        import hashlib
        import json
        import time

        # JWT header
        header = {"alg": "HS256", "typ": "JWT"}

        # JWT payload
        now = int(time.time())
        payload = {
            "appKey": self.client_id,
            "sdkKey": self.client_id,
            "mn": meeting_id,
            "role": 0,  # 0 = participant, 1 = host
            "iat": now,
            "exp": now + 3600,  # 1 hour expiry
            "tokenExp": now + 3600,
        }

        # Encode
        def b64_encode(data):
            return base64.urlsafe_b64encode(
                json.dumps(data).encode()
            ).rstrip(b"=").decode()

        header_b64 = b64_encode(header)
        payload_b64 = b64_encode(payload)

        # Sign
        message = f"{header_b64}.{payload_b64}"
        signature = hmac.new(
            self.client_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

        return f"{header_b64}.{payload_b64}.{signature_b64}"

    async def _join_with_sdk(self, meeting_id: str, password: str, jwt: str):
        """
        Join meeting using the SDK.

        Args:
            meeting_id: Meeting ID
            password: Meeting password
            jwt: Authentication JWT
        """
        if not self._sdk:
            raise RuntimeError("SDK not initialized")

        # Set up callbacks for state changes
        def on_meeting_status(status):
            if status == "MEETING_STATUS_INMEETING":
                self._set_state(ZoomBotState.IN_MEETING)
            elif status == "MEETING_STATUS_WAITINGFORHOST":
                self._set_state(ZoomBotState.IN_WAITING_ROOM)
            elif status == "MEETING_STATUS_ENDED":
                self._set_state(ZoomBotState.DISCONNECTED)

        self._sdk.on_meeting_status = on_meeting_status

        # Join the meeting
        self._sdk.join(
            meeting_number=meeting_id,
            password=password,
            display_name=self.display_name,
            jwt=jwt,
        )

    def _start_streaming(self):
        """Start the video/audio streaming thread."""
        if self._streaming:
            return

        self._streaming = True
        self._stream_thread = threading.Thread(
            target=self._streaming_loop,
            daemon=True
        )
        self._stream_thread.start()
        logger.info("Video streaming thread started")

    def _streaming_loop(self):
        """Background thread for streaming video frames to Zoom."""
        while self._streaming and self.is_in_meeting:
            try:
                # Get next video frame
                if not self._video_queue.empty():
                    frame = self._video_queue.get_nowait()
                    self._send_video_frame(frame)

                # Get next audio chunk
                if not self._audio_queue.empty():
                    audio = self._audio_queue.get_nowait()
                    self._send_audio_chunk(audio)

                # Small sleep to prevent busy waiting
                time.sleep(0.001)  # 1ms

            except Exception as e:
                logger.error(f"Streaming error: {e}")

        logger.info("Video streaming thread stopped")

    def _send_video_frame(self, frame: VideoFrame):
        """
        Send a video frame to Zoom.

        Args:
            frame: Video frame to send
        """
        if not self._sdk or not self.is_in_meeting:
            return

        try:
            # Convert to YUV420 if needed
            if frame.format != "yuv420":
                yuv_data = self._convert_to_yuv420(frame)
            else:
                yuv_data = frame.data

            # Send via SDK's video source
            if self._video_sender:
                self._video_sender.send_frame(
                    data=yuv_data,
                    width=frame.width,
                    height=frame.height,
                    timestamp=frame.timestamp_ms,
                )

        except Exception as e:
            logger.error(f"Failed to send video frame: {e}")

    def _send_audio_chunk(self, audio_data: bytes):
        """
        Send an audio chunk to Zoom.

        Args:
            audio_data: PCM audio data (16-bit, 16kHz mono)
        """
        if not self._sdk or not self.is_in_meeting:
            return

        try:
            if self._audio_sender:
                self._audio_sender.send_audio(audio_data)
        except Exception as e:
            logger.error(f"Failed to send audio: {e}")

    def _convert_to_yuv420(self, frame: VideoFrame) -> bytes:
        """
        Convert video frame to YUV420 format.

        Args:
            frame: Source video frame (RGB24 or RGBA)

        Returns:
            YUV420 pixel data
        """
        try:
            import numpy as np

            width, height = frame.width, frame.height

            if frame.format == "rgb24":
                # Reshape to HxWx3
                rgb = np.frombuffer(frame.data, dtype=np.uint8).reshape(height, width, 3)
            elif frame.format == "rgba":
                # Reshape to HxWx4, drop alpha
                rgba = np.frombuffer(frame.data, dtype=np.uint8).reshape(height, width, 4)
                rgb = rgba[:, :, :3]
            else:
                raise ValueError(f"Unsupported format: {frame.format}")

            # Convert RGB to YUV
            r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]

            # Y channel (full resolution)
            y = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8)

            # U and V channels (half resolution)
            u = (128 - 0.168736 * r - 0.331264 * g + 0.5 * b)[::2, ::2].astype(np.uint8)
            v = (128 + 0.5 * r - 0.418688 * g - 0.081312 * b)[::2, ::2].astype(np.uint8)

            # Combine into I420 format: Y plane, then U plane, then V plane
            return y.tobytes() + u.tobytes() + v.tobytes()

        except ImportError:
            logger.error("numpy required for video format conversion")
            raise

    def send_video_frame(self, frame: VideoFrame):
        """
        Queue a video frame for streaming to Zoom.

        Thread-safe with lock protection to prevent race conditions.

        Args:
            frame: Video frame from avatar

        Raises:
            ValueError: If frame dimensions don't match data size
        """
        # Validate frame
        if not frame or not frame.data:
            logger.warning("Received empty video frame, skipping")
            return

        expected_size = self._get_expected_frame_size(frame)
        if expected_size and len(frame.data) != expected_size:
            logger.warning(
                f"Frame data size mismatch: expected {expected_size}, "
                f"got {len(frame.data)} for {frame.width}x{frame.height} {frame.format}"
            )

        # Thread-safe queue operation
        with self._queue_lock:
            if self._video_queue.full():
                # Drop oldest frame to prevent lag
                try:
                    self._video_queue.get_nowait()
                except Exception:
                    pass

            self._video_queue.put(frame)

    def _get_expected_frame_size(self, frame: VideoFrame) -> Optional[int]:
        """Calculate expected data size for frame dimensions and format."""
        if frame.format == "yuv420":
            # Y plane + U plane (1/4) + V plane (1/4) = 1.5 * width * height
            return int(frame.width * frame.height * 1.5)
        elif frame.format == "rgb24":
            return frame.width * frame.height * 3
        elif frame.format == "rgba":
            return frame.width * frame.height * 4
        return None  # Unknown format

    def send_audio(self, audio_data: bytes):
        """
        Queue audio data for streaming to Zoom.

        Thread-safe with lock protection.

        Args:
            audio_data: PCM audio (16-bit, 16kHz mono)
        """
        if not audio_data:
            return

        # Thread-safe queue operation
        with self._queue_lock:
            if self._audio_queue.full():
                try:
                    self._audio_queue.get_nowait()
                except Exception:
                    pass

            self._audio_queue.put(audio_data)

    async def leave_meeting(self):
        """Leave the current meeting."""
        if not self.is_in_meeting:
            return

        try:
            self._streaming = False

            if self._stream_thread:
                self._stream_thread.join(timeout=THREAD_JOIN_TIMEOUT)

            if self._sdk:
                self._sdk.leave()

            self._set_state(ZoomBotState.DISCONNECTED)
            logger.info("Left meeting")

        except Exception as e:
            logger.error(f"Error leaving meeting: {e}")

    async def cleanup(self):
        """Clean up SDK resources."""
        await self.leave_meeting()

        if self._sdk:
            self._sdk.cleanup()
            self._sdk = None

        logger.info("Zoom bot cleaned up")


class ZoomAvatarBridge:
    """
    Bridge between LiveKit avatar and Zoom meeting.

    This class:
    1. Receives video/audio from LiveKit/Simli avatar
    2. Converts to Zoom-compatible formats
    3. Streams to Zoom meeting via ZoomMeetingBot
    """

    def __init__(
        self,
        zoom_bot: ZoomMeetingBot,
        target_fps: int = 30,
        target_width: int = 1280,
        target_height: int = 720,
    ):
        """
        Initialize the bridge.

        Args:
            zoom_bot: ZoomMeetingBot instance
            target_fps: Target frame rate
            target_width: Target video width
            target_height: Target video height
        """
        self.zoom_bot = zoom_bot
        self.target_fps = target_fps
        self.target_width = target_width
        self.target_height = target_height

        self._running = False
        self._frame_interval = 1.0 / target_fps
        self._last_frame_time = 0

    async def start(self):
        """Start the bridge."""
        self._running = True
        logger.info("Zoom avatar bridge started")

    async def stop(self):
        """Stop the bridge."""
        self._running = False
        logger.info("Zoom avatar bridge stopped")

    def on_video_frame(self, data: bytes, width: int, height: int, format: str):
        """
        Handle incoming video frame from avatar.

        Args:
            data: Raw pixel data
            width: Frame width
            height: Frame height
            format: Pixel format (rgb24, rgba, yuv420)
        """
        if not self._running or not self.zoom_bot.is_in_meeting:
            return

        # Rate limit to target FPS
        now = time.time()
        if now - self._last_frame_time < self._frame_interval:
            return
        self._last_frame_time = now

        # Create frame and send to Zoom
        frame = VideoFrame(
            data=data,
            width=width,
            height=height,
            format=format,
            timestamp_ms=int(now * 1000),
        )
        self.zoom_bot.send_video_frame(frame)

    def on_audio_chunk(self, data: bytes):
        """
        Handle incoming audio from TTS.

        Args:
            data: PCM audio data
        """
        if not self._running or not self.zoom_bot.is_in_meeting:
            return

        self.zoom_bot.send_audio(data)


# Convenience function for creating a complete avatar-to-Zoom pipeline
async def create_zoom_avatar_session(
    meeting_id: str,
    meeting_password: str = "",
    query_handler: Callable[[str], str] = None,
) -> tuple[ZoomMeetingBot, ZoomAvatarBridge]:
    """
    Create a complete avatar session for Zoom.

    Args:
        meeting_id: Zoom meeting ID to join
        meeting_password: Meeting password
        query_handler: Function to handle user queries

    Returns:
        Tuple of (ZoomMeetingBot, ZoomAvatarBridge)
    """
    # Create Zoom bot
    zoom_bot = ZoomMeetingBot()

    # Create bridge
    bridge = ZoomAvatarBridge(zoom_bot)

    # Join meeting
    await zoom_bot.join_meeting(meeting_id, meeting_password)

    # Start bridge
    await bridge.start()

    return zoom_bot, bridge


if __name__ == "__main__":
    # Test the Zoom bot standalone
    logging.basicConfig(level=logging.INFO)

    async def test():
        bot = ZoomMeetingBot()
        print("Zoom bot initialized")
        print(f"Client ID: {bot.client_id[:8]}...")

        # Would need a real meeting ID to test
        # await bot.join_meeting("123456789", "password")

    asyncio.run(test())
