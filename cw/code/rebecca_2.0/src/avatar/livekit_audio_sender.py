"""
LiveKit Audio Sender for Simli lip sync.

Sends TTS audio from the Flask server to the Simli avatar agent
via LiveKit DataStream for lip-synced video generation.
"""
import asyncio
import logging
import os
import threading
import time
from typing import Optional
import struct

try:
    from livekit import rtc, api
    LIVEKIT_AVAILABLE = True
except ImportError:
    LIVEKIT_AVAILABLE = False
    rtc = None
    api = None


logger = logging.getLogger("qa_agent.livekit_audio_sender")

# Constants matching livekit-agents DataStreamAudioOutput
AUDIO_STREAM_TOPIC = "lk.audio_stream"
SIMLI_AVATAR_IDENTITY = "simli-avatar-agent"


class LiveKitAudioSender:
    """
    Sends audio to Simli avatar via LiveKit DataStream.

    This allows the Flask voice pipeline to send TTS audio to
    the Simli avatar agent for lip-synced video generation.

    Usage:
        sender = LiveKitAudioSender()
        await sender.connect("room-name")
        await sender.send_audio(audio_bytes, sample_rate=24000)
        await sender.disconnect()
    """

    def __init__(
        self,
        livekit_url: str = None,
        api_key: str = None,
        api_secret: str = None,
    ):
        """
        Initialize the audio sender.

        Args:
            livekit_url: LiveKit server URL (or LIVEKIT_URL env var)
            api_key: LiveKit API key (or LIVEKIT_API_KEY env var)
            api_secret: LiveKit API secret (or LIVEKIT_API_SECRET env var)
        """
        self.livekit_url = livekit_url or os.getenv("LIVEKIT_URL")
        self.api_key = api_key or os.getenv("LIVEKIT_API_KEY")
        self.api_secret = api_secret or os.getenv("LIVEKIT_API_SECRET")

        self._room: Optional[rtc.Room] = None
        self._stream_writer: Optional[rtc.ByteStreamWriter] = None
        self._connected = False
        self._room_name: Optional[str] = None

        # Background event loop for async operations
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None

    @property
    def is_configured(self) -> bool:
        """Check if LiveKit is properly configured."""
        return LIVEKIT_AVAILABLE and all([
            self.livekit_url,
            self.api_key,
            self.api_secret
        ])

    @property
    def is_connected(self) -> bool:
        """Check if connected to a room."""
        return self._connected and self._room is not None

    def _ensure_loop(self):
        """Ensure background event loop is running."""
        if self._loop is None or not self._loop.is_running():
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._run_loop,
                daemon=True
            )
            self._loop_thread.start()
            # Wait for loop to start
            time.sleep(0.1)

    def _run_loop(self):
        """Run the event loop in background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _generate_token(self, room_name: str, identity: str) -> str:
        """Generate a LiveKit access token."""
        token = api.AccessToken(self.api_key, self.api_secret)
        token.with_identity(identity)
        token.with_name("Flask Audio Sender")
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,  # Need to publish audio via DataStream
            can_publish_data=True,
            can_subscribe=False,  # Don't need to receive anything
        ))
        return token.to_jwt()

    def connect(self, room_name: str, max_retries: int = 3) -> bool:
        """
        Connect to a LiveKit room (synchronous wrapper).

        Args:
            room_name: Name of the room to connect to
            max_retries: Maximum connection attempts

        Returns:
            True if connected successfully
        """
        if not self.is_configured:
            logger.error("LiveKit not configured")
            return False

        self._ensure_loop()

        for attempt in range(max_retries):
            future = asyncio.run_coroutine_threadsafe(
                self._connect_async(room_name),
                self._loop
            )
            try:
                result = future.result(timeout=15)  # Increased timeout
                if result:
                    return True
                logger.warning(f"Connect attempt {attempt + 1}/{max_retries} failed, retrying...")
            except Exception as e:
                logger.warning(f"Connect attempt {attempt + 1}/{max_retries} error: {e}")

            if attempt < max_retries - 1:
                time.sleep(1)  # Wait before retry

        logger.error(f"Failed to connect after {max_retries} attempts")
        return False

    async def _connect_async(self, room_name: str) -> bool:
        """Connect to LiveKit room asynchronously."""
        try:
            # Generate token for this connection
            identity = f"flask-audio-sender-{int(time.time())}"
            token = self._generate_token(room_name, identity)

            # Create and connect room
            self._room = rtc.Room()
            await self._room.connect(self.livekit_url, token)

            self._room_name = room_name
            self._connected = True

            logger.info(f"Connected to LiveKit room: {room_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to room {room_name}: {e}")
            self._connected = False
            return False

    def disconnect(self):
        """Disconnect from the room (synchronous wrapper)."""
        if self._loop and self._connected:
            future = asyncio.run_coroutine_threadsafe(
                self._disconnect_async(),
                self._loop
            )
            try:
                future.result(timeout=5)
            except Exception as e:
                logger.warning(f"Disconnect error: {e}")

    async def _disconnect_async(self):
        """Disconnect asynchronously."""
        if self._stream_writer:
            try:
                await self._stream_writer.aclose()
            except Exception:
                pass
            self._stream_writer = None

        if self._room:
            await self._room.disconnect()
            self._room = None

        self._connected = False
        logger.info(f"Disconnected from room {self._room_name}")

    def send_audio(
        self,
        audio_data: bytes,
        sample_rate: int = 24000,
        num_channels: int = 1
    ) -> bool:
        """
        Send audio to Simli avatar agent (synchronous wrapper).

        Args:
            audio_data: Raw PCM audio bytes (16-bit signed)
            sample_rate: Audio sample rate
            num_channels: Number of audio channels

        Returns:
            True if audio was sent successfully
        """
        if not self.is_connected:
            logger.warning("Not connected to room, cannot send audio")
            return False

        future = asyncio.run_coroutine_threadsafe(
            self._send_audio_async(audio_data, sample_rate, num_channels),
            self._loop
        )
        try:
            return future.result(timeout=10)
        except Exception as e:
            logger.error(f"Send audio failed: {e}")
            return False

    async def _send_audio_async(
        self,
        audio_data: bytes,
        sample_rate: int,
        num_channels: int
    ) -> bool:
        """Send audio via DataStream asynchronously."""
        try:
            if not self._room or not self._room.isconnected():
                logger.error("Room not connected")
                return False

            # Check if simli-avatar-agent is in the room
            simli_participant = None
            for participant in self._room.remote_participants.values():
                if participant.identity == SIMLI_AVATAR_IDENTITY:
                    simli_participant = participant
                    break

            if not simli_participant:
                logger.warning(f"Simli avatar agent ({SIMLI_AVATAR_IDENTITY}) not found in room")
                return False

            # Create new stream writer for this audio segment
            logger.debug(f"Sending {len(audio_data)} bytes to {SIMLI_AVATAR_IDENTITY}")

            stream_writer = await self._room.local_participant.stream_bytes(
                name=f"audio_{int(time.time() * 1000)}",
                topic=AUDIO_STREAM_TOPIC,
                destination_identities=[SIMLI_AVATAR_IDENTITY],
                attributes={
                    "sample_rate": str(sample_rate),
                    "num_channels": str(num_channels),
                },
            )

            # Write audio data
            await stream_writer.write(audio_data)

            # Close stream to signal end of segment
            await stream_writer.aclose()

            logger.debug(f"Audio sent successfully to Simli")
            return True

        except Exception as e:
            logger.error(f"Failed to send audio: {e}")
            return False

    def send_audio_mp3(
        self,
        mp3_data: bytes,
        sample_rate: int = 24000
    ) -> bool:
        """
        Send MP3 audio to Simli (converts to PCM first).

        Args:
            mp3_data: MP3 encoded audio bytes
            sample_rate: Target sample rate for PCM

        Returns:
            True if audio was sent successfully
        """
        try:
            # Convert MP3 to PCM
            pcm_data = self._mp3_to_pcm(mp3_data, sample_rate)
            if pcm_data:
                return self.send_audio(pcm_data, sample_rate)
            else:
                logger.warning("MP3 to PCM conversion failed")
                return False
        except Exception as e:
            logger.error(f"MP3 send failed: {e}")
            return False

    def _mp3_to_pcm(self, mp3_data: bytes, target_rate: int = 16000) -> Optional[bytes]:
        """
        Convert MP3 to PCM audio at Simli's expected sample rate.

        Simli expects 16kHz mono PCM audio for lip sync.

        Args:
            mp3_data: MP3 encoded bytes
            target_rate: Target sample rate (default 16kHz for Simli)

        Returns:
            PCM bytes (16-bit signed, mono) or None on error
        """
        try:
            from pydub import AudioSegment
            import io

            # Load MP3
            audio = AudioSegment.from_mp3(io.BytesIO(mp3_data))

            # Convert to mono, target sample rate (16kHz for Simli), 16-bit
            audio = audio.set_channels(1)
            audio = audio.set_frame_rate(target_rate)
            audio = audio.set_sample_width(2)  # 16-bit

            logger.debug(f"Converted MP3 to PCM: {len(audio.raw_data)} bytes at {target_rate}Hz")

            # Export as raw PCM
            return audio.raw_data

        except ImportError:
            logger.warning("pydub not available for MP3 conversion")
            return None
        except Exception as e:
            logger.error(f"MP3 conversion error: {e}")
            return None


# Singleton instance
_audio_sender: Optional[LiveKitAudioSender] = None
_sender_lock = threading.Lock()


def get_livekit_audio_sender() -> LiveKitAudioSender:
    """Get or create the LiveKit audio sender singleton."""
    global _audio_sender
    with _sender_lock:
        if _audio_sender is None:
            _audio_sender = LiveKitAudioSender()
        return _audio_sender


def send_audio_to_simli(
    room_name: str,
    audio_data: bytes,
    sample_rate: int = 24000,
    is_mp3: bool = False,
    async_send: bool = True
) -> bool:
    """
    Convenience function to send audio to Simli avatar.

    Handles connection management automatically.

    Args:
        room_name: LiveKit room name
        audio_data: Audio bytes (PCM or MP3)
        sample_rate: Audio sample rate
        is_mp3: True if audio_data is MP3 encoded
        async_send: If True, send in background thread (non-blocking)

    Returns:
        True if audio was queued/sent successfully
    """
    if async_send:
        # Run in background thread to avoid blocking voice response
        thread = threading.Thread(
            target=_send_audio_to_simli_sync,
            args=(room_name, audio_data, sample_rate, is_mp3),
            daemon=True
        )
        thread.start()
        logger.debug(f"Queued audio for Simli (async) in room {room_name}")
        return True
    else:
        return _send_audio_to_simli_sync(room_name, audio_data, sample_rate, is_mp3)


def _send_audio_to_simli_sync(
    room_name: str,
    audio_data: bytes,
    sample_rate: int,
    is_mp3: bool
) -> bool:
    """Synchronous implementation of send_audio_to_simli."""
    sender = get_livekit_audio_sender()

    if not sender.is_configured:
        logger.warning("LiveKit not configured for Simli audio")
        return False

    # Connect if not already connected to this room
    if not sender.is_connected or sender._room_name != room_name:
        if sender.is_connected:
            sender.disconnect()
        if not sender.connect(room_name):
            logger.warning(f"Failed to connect to room {room_name} for Simli audio")
            return False

    # Send audio
    if is_mp3:
        return sender.send_audio_mp3(audio_data, sample_rate)
    else:
        return sender.send_audio(audio_data, sample_rate)
