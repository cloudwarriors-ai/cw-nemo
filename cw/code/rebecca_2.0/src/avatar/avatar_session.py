"""
Avatar session manager for coordinating voice + avatar.

Manages the lifecycle of avatar sessions and coordinates
between the voice pipeline (ASR → LLM → TTS) and avatar
generation (Simli).
"""
import base64
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any
from enum import Enum

from .simli_client import SimliClient, SimliSession, SimliSessionState


class AvatarMode(Enum):
    """Avatar display modes."""
    IDLE = "idle"           # Static image, not speaking
    LISTENING = "listening" # Listening indicator
    THINKING = "thinking"   # Processing indicator
    SPEAKING = "speaking"   # Animated lip-sync
    ERROR = "error"         # Error state


@dataclass
class AvatarState:
    """Current state of the avatar."""
    mode: AvatarMode = AvatarMode.IDLE
    current_text: str = ""
    last_update: float = field(default_factory=time.time)
    error_message: Optional[str] = None


class AvatarSessionManager:
    """
    Manages avatar sessions for meetings.

    Coordinates between:
    - Voice pipeline (provides audio to animate)
    - Simli client (generates avatar video)
    - Recall.ai (streams to meeting)

    Features:
    - Graceful degradation (avatar → static → voice-only)
    - State tracking (idle, listening, speaking)
    - Latency monitoring
    - Error threshold with automatic recovery (Council fix)
    """

    # Timeouts for degradation
    SIMLI_TIMEOUT_MS = 1000     # Max wait for Simli response
    FALLBACK_TIMEOUT_MS = 2000  # When to fall back to voice-only

    # Council fix: Error threshold for automatic session recovery
    MAX_CONSECUTIVE_ERRORS = 10  # Restart session after this many consecutive errors
    ERROR_RECOVERY_DELAY_MS = 5000  # Delay before auto-restart

    def __init__(
        self,
        simli_client: SimliClient,
        logger: logging.Logger = None,
        on_state_change: Callable[[AvatarState], None] = None,
        on_video_frame: Callable[[bytes], None] = None
    ):
        """
        Initialize avatar session manager.

        Args:
            simli_client: Simli API client
            logger: Logger instance
            on_state_change: Callback when avatar state changes
            on_video_frame: Callback when video frame is ready
        """
        self.simli_client = simli_client
        self.logger = logger or logging.getLogger("qa_agent")
        self.on_state_change = on_state_change
        self.on_video_frame = on_video_frame

        self._session: Optional[SimliSession] = None
        self._state = AvatarState()
        self._meeting_id: Optional[str] = None

        # Queues for async processing
        self._audio_queue: queue.Queue = queue.Queue()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Metrics
        self._metrics = {
            "total_audio_chunks": 0,
            "total_video_frames": 0,
            "avg_latency_ms": 0,
            "errors": 0,
            "fallbacks": 0,
            "consecutive_errors": 0,  # Council fix: track for recovery
            "restarts": 0
        }

    @property
    def state(self) -> AvatarState:
        """Get current avatar state."""
        return self._state

    @property
    def is_active(self) -> bool:
        """Check if avatar session is active."""
        return self._session is not None and self._session.is_active()

    def start_session(self, meeting_id: str) -> bool:
        """
        Start an avatar session for a meeting.

        Args:
            meeting_id: Meeting identifier

        Returns:
            True if session started successfully
        """
        if self._session and self._session.is_active():
            self.logger.warning(f"Session already active for {self._meeting_id}")
            return False

        try:
            self._meeting_id = meeting_id
            self._session = self.simli_client.create_session()

            # Connect WebSocket for streaming
            connected = self.simli_client.connect_websocket(
                self._session,
                on_video_frame=self._handle_video_frame
            )

            if not connected:
                self.logger.warning("WebSocket connection failed, using REST fallback")

            # Start worker thread
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._process_loop,
                daemon=True
            )
            self._worker_thread.start()

            self._set_state(AvatarMode.IDLE)
            self.logger.info(f"Avatar session started for meeting {meeting_id}")

            return True

        except Exception as e:
            self.logger.error(f"Failed to start avatar session: {e}")
            self._set_state(AvatarMode.ERROR, error=str(e))
            return False

    def stop_session(self):
        """Stop the current avatar session."""
        if not self._session:
            return

        self._running = False

        # Drain the audio queue to prevent memory leak
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)

        if self._session:
            self.simli_client.close_session(self._session)

        self._set_state(AvatarMode.IDLE)
        self.logger.info(
            f"Avatar session stopped for meeting {self._meeting_id}. "
            f"Metrics: {self._metrics}"
        )

        self._session = None
        self._meeting_id = None

    def cleanup_session(self, meeting_id: str):
        """
        Clean up avatar session for a specific meeting.

        Called when a meeting ends to release resources.

        Args:
            meeting_id: Meeting identifier
        """
        if self._meeting_id == meeting_id:
            self.logger.info(f"Cleaning up avatar session for meeting {meeting_id}")
            self.stop_session()
        else:
            self.logger.debug(
                f"Cleanup requested for {meeting_id} but current session is {self._meeting_id}"
            )

    def set_listening(self):
        """Set avatar to listening state."""
        self._set_state(AvatarMode.LISTENING)

    def set_thinking(self):
        """Set avatar to thinking/processing state."""
        self._set_state(AvatarMode.THINKING)

    def send_audio_for_avatar(
        self,
        audio_data: bytes,
        text: str = "",
        sample_rate: int = 24000
    ):
        """
        Queue audio for avatar lip-sync.

        Args:
            audio_data: TTS audio bytes (PCM)
            text: Text being spoken (for state tracking)
            sample_rate: Audio sample rate
        """
        if not self.is_active:
            self.logger.debug("No active session, skipping avatar audio")
            return

        self._audio_queue.put({
            "audio": audio_data,
            "text": text,
            "sample_rate": sample_rate,
            "timestamp": time.time()
        })

        self._state.current_text = text
        self._set_state(AvatarMode.SPEAKING)

    def _process_loop(self):
        """Background worker for processing audio → avatar."""
        while self._running:
            try:
                # Get audio from queue with timeout
                try:
                    item = self._audio_queue.get(timeout=0.5)
                except queue.Empty:
                    # No audio, check if we should go idle
                    if self._state.mode == AvatarMode.SPEAKING:
                        idle_timeout = time.time() - self._state.last_update > 2.0
                        if idle_timeout:
                            self._set_state(AvatarMode.IDLE)
                    continue

                # Process audio through Simli
                success = self._process_audio_chunk(item)

                # Council fix: Track consecutive errors and trigger recovery
                if success:
                    self._metrics["consecutive_errors"] = 0
                else:
                    self._metrics["consecutive_errors"] += 1
                    self._metrics["errors"] += 1

                    # Check if we need to trigger recovery
                    if self._metrics["consecutive_errors"] >= self.MAX_CONSECUTIVE_ERRORS:
                        self.logger.warning(
                            f"Avatar session hit {self.MAX_CONSECUTIVE_ERRORS} consecutive errors, "
                            f"triggering recovery..."
                        )
                        self._trigger_recovery()

            except Exception as e:
                self.logger.error(f"Avatar processing error: {e}", exc_info=True)
                self._metrics["errors"] += 1
                self._metrics["consecutive_errors"] += 1

                # Council fix: Also check error threshold on exceptions
                if self._metrics["consecutive_errors"] >= self.MAX_CONSECUTIVE_ERRORS:
                    self._trigger_recovery()

    def _trigger_recovery(self):
        """
        Council fix: Attempt to recover from error state.

        Stops current session and restarts after delay.
        """
        meeting_id = self._meeting_id
        if not meeting_id:
            self.logger.warning("Cannot recover - no meeting_id stored")
            return

        self.logger.info(f"Triggering avatar session recovery for {meeting_id}")
        self._metrics["restarts"] += 1
        self._metrics["consecutive_errors"] = 0

        # Stop current session
        self.simli_client.close_session(self._session)
        self._session = None
        self._set_state(AvatarMode.ERROR, error="Reconnecting...")

        # Restart after delay (in background thread to not block worker)
        def restart():
            time.sleep(self.ERROR_RECOVERY_DELAY_MS / 1000)
            if self._running and meeting_id:
                self.logger.info(f"Restarting avatar session for {meeting_id}")
                self.start_session(meeting_id)

        recovery_thread = threading.Thread(target=restart, daemon=True)
        recovery_thread.start()

    def _process_audio_chunk(self, item: dict) -> bool:
        """
        Process a single audio chunk through Simli.

        Returns:
            True if successful, False on error
        """
        start_time = time.time()
        audio_data = item["audio"]
        sample_rate = item["sample_rate"]

        self._metrics["total_audio_chunks"] += 1

        # Send to Simli
        success = self.simli_client.send_audio(
            self._session,
            audio_data,
            sample_rate
        )

        if success:
            # Wait for video frame with timeout
            frame = self.simli_client.get_video_frame(
                timeout=self.SIMLI_TIMEOUT_MS / 1000
            )

            if frame:
                self._metrics["total_video_frames"] += 1
                latency = (time.time() - start_time) * 1000

                # Update running average
                n = self._metrics["total_video_frames"]
                avg = self._metrics["avg_latency_ms"]
                self._metrics["avg_latency_ms"] = avg + (latency - avg) / n

                # Emit video frame
                if self.on_video_frame:
                    self.on_video_frame(frame)

                return True
            else:
                self.logger.debug("Simli timeout, continuing without video frame")
                self._metrics["fallbacks"] += 1
                return True  # Timeout is not a failure, just degraded
        else:
            self.logger.warning("Failed to send audio to Simli")
            return False

    def _handle_video_frame(self, frame: bytes):
        """Handle incoming video frame from Simli WebSocket."""
        self._metrics["total_video_frames"] += 1

        # Council fix: Route video frames to avatar webpage via WebSocket
        if self._meeting_id:
            try:
                from .websocket_manager import get_avatar_ws_manager
                manager = get_avatar_ws_manager(self.logger)
                manager.send_video_frame(self._meeting_id, frame, "jpeg")
            except Exception as e:
                self.logger.warning(f"Failed to route video frame: {e}")

        # Also call the callback if provided
        if self.on_video_frame:
            self.on_video_frame(frame)

    def _set_state(
        self,
        mode: AvatarMode,
        text: str = None,
        error: str = None
    ):
        """Update avatar state and notify listeners."""
        self._state.mode = mode
        self._state.last_update = time.time()

        if text is not None:
            self._state.current_text = text
        if error is not None:
            self._state.error_message = error

        if self.on_state_change:
            self.on_state_change(self._state)

    def get_metrics(self) -> dict:
        """Get session metrics."""
        metrics = dict(self._metrics)

        if self._session:
            metrics["session"] = self.simli_client.get_session_stats(self._session)

        metrics["current_state"] = self._state.mode.value
        metrics["meeting_id"] = self._meeting_id

        return metrics

    def get_state_for_webpage(self) -> dict:
        """
        Get current state formatted for avatar webpage.

        Returns:
            Dict with state info for rendering
        """
        return {
            "mode": self._state.mode.value,
            "text": self._state.current_text,
            "error": self._state.error_message,
            "timestamp": self._state.last_update,
            "session_active": self.is_active,
            "meeting_id": self._meeting_id
        }


class AvatarWebpageServer:
    """
    Serves the avatar webpage for Recall.ai Output Media.

    This is the webpage that Recall.ai renders as the bot's
    camera feed in meetings.
    """

    def __init__(
        self,
        session_manager: AvatarSessionManager,
        static_image_url: str = None,
        logger: logging.Logger = None
    ):
        """
        Initialize webpage server.

        Args:
            session_manager: Avatar session manager
            static_image_url: URL of fallback static avatar image
            logger: Logger instance
        """
        self.session_manager = session_manager
        self.static_image_url = static_image_url
        self.logger = logger or logging.getLogger("qa_agent")

        # Video frame buffer for webpage
        self._current_frame: Optional[bytes] = None
        self._frame_lock = threading.Lock()

        # Register as video frame handler
        session_manager.on_video_frame = self._on_video_frame

    def _on_video_frame(self, frame: bytes):
        """Handle new video frame."""
        with self._frame_lock:
            self._current_frame = frame

    def get_current_frame(self) -> Optional[bytes]:
        """Get current video frame for display."""
        with self._frame_lock:
            return self._current_frame

    def get_current_frame_base64(self) -> Optional[str]:
        """Get current video frame as base64 for embedding."""
        frame = self.get_current_frame()
        if frame:
            return base64.b64encode(frame).decode()
        return None

    def get_webpage_html(self) -> str:
        """
        Generate the avatar webpage HTML.

        This HTML is rendered by Recall.ai's browser and
        streamed as the bot's camera feed.
        """
        state = self.session_manager.get_state_for_webpage()

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=1280, height=720">
    <title>QA Bot Avatar</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            width: 1280px;
            height: 720px;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            overflow: hidden;
        }}
        .avatar-container {{
            position: relative;
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }}
        #avatar-video {{
            max-width: 80%;
            max-height: 70%;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
        }}
        #avatar-image {{
            max-width: 80%;
            max-height: 70%;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
        }}
        .status-bar {{
            position: absolute;
            bottom: 40px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            padding: 12px 24px;
            border-radius: 30px;
            color: white;
            font-size: 18px;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .status-indicator {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #4CAF50;
        }}
        .status-indicator.listening {{ background: #2196F3; animation: pulse 1.5s infinite; }}
        .status-indicator.thinking {{ background: #FF9800; animation: pulse 0.8s infinite; }}
        .status-indicator.speaking {{ background: #4CAF50; animation: pulse 0.5s infinite; }}
        .status-indicator.error {{ background: #f44336; }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.6; transform: scale(1.2); }}
        }}
        .name-tag {{
            position: absolute;
            top: 40px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0,0,0,0.6);
            padding: 8px 20px;
            border-radius: 20px;
            color: white;
            font-size: 24px;
            font-weight: 600;
        }}
        .caption {{
            position: absolute;
            bottom: 100px;
            left: 50%;
            transform: translateX(-50%);
            max-width: 80%;
            background: rgba(0,0,0,0.7);
            padding: 12px 24px;
            border-radius: 10px;
            color: white;
            font-size: 20px;
            text-align: center;
            display: none;
        }}
        .caption.visible {{ display: block; }}
    </style>
</head>
<body>
    <div class="avatar-container">
        <div class="name-tag">QA Bot</div>

        <video id="avatar-video" autoplay muted playsinline style="display: none;"></video>
        <img id="avatar-image" src="{self.static_image_url or '/static/avatar/default.png'}" alt="QA Bot">

        <div class="caption" id="caption"></div>

        <div class="status-bar">
            <div class="status-indicator" id="status-indicator"></div>
            <span id="status-text">Ready</span>
        </div>
    </div>

    <script>
        const avatarVideo = document.getElementById('avatar-video');
        const avatarImage = document.getElementById('avatar-image');
        const statusIndicator = document.getElementById('status-indicator');
        const statusText = document.getElementById('status-text');
        const caption = document.getElementById('caption');

        // Connect to server for updates
        const ws = new WebSocket('wss://' + window.location.host + '/avatar/ws');

        ws.onmessage = (event) => {{
            const data = JSON.parse(event.data);

            // Update status
            statusIndicator.className = 'status-indicator ' + data.mode;
            statusText.textContent = getStatusText(data.mode);

            // Update caption
            if (data.text && data.mode === 'speaking') {{
                caption.textContent = data.text;
                caption.classList.add('visible');
            }} else {{
                caption.classList.remove('visible');
            }}

            // Handle video frame
            if (data.video_frame) {{
                avatarImage.style.display = 'none';
                avatarVideo.style.display = 'block';
                // Video frame handling would go here
            }}
        }};

        function getStatusText(mode) {{
            switch(mode) {{
                case 'idle': return 'Ready';
                case 'listening': return 'Listening...';
                case 'thinking': return 'Thinking...';
                case 'speaking': return 'Speaking';
                case 'error': return 'Error';
                default: return 'Ready';
            }}
        }}

        // Handle meeting audio input (provided by Recall.ai)
        async function setupAudioInput() {{
            try {{
                const mediaStream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                const audioTrack = mediaStream.getAudioTracks()[0];

                // Send audio to server for processing
                const processor = new MediaStreamTrackProcessor({{ track: audioTrack }});
                const reader = processor.readable.getReader();

                while (true) {{
                    const {{ value, done }} = await reader.read();
                    if (done) break;

                    // Convert AudioData to bytes and send
                    // This would need proper implementation
                }}
            }} catch (e) {{
                console.log('Audio input not available:', e);
            }}
        }}

        setupAudioInput();
    </script>
</body>
</html>"""
