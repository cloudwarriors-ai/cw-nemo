"""
LiveKit Text Sender for routing queries to avatar agent.

Sends text queries to the LiveKit room where the Simli avatar agent
can process them and generate synced audio + video.

Uses the LiveKit Server API (HTTP) to send data, avoiding the need
for a full WebRTC connection from Flask.
"""
import asyncio
import json
import logging
import os
import threading
import time
from typing import Optional

try:
    from livekit import api
    LIVEKIT_AVAILABLE = True
except ImportError:
    LIVEKIT_AVAILABLE = False
    api = None


logger = logging.getLogger("qa_agent.livekit_text_sender")

# Topic for text queries to avatar agent
QUERY_TOPIC = "qa.query"


class LiveKitTextSender:
    """
    Sends text queries to avatar agent via LiveKit DataChannel.

    This allows the Flask voice pipeline to route queries through
    LiveKit for synced audio + avatar response.
    """

    def __init__(
        self,
        livekit_url: str = None,
        api_key: str = None,
        api_secret: str = None,
    ):
        self.livekit_url = livekit_url or os.getenv("LIVEKIT_URL")
        self.api_key = api_key or os.getenv("LIVEKIT_API_KEY")
        self.api_secret = api_secret or os.getenv("LIVEKIT_API_SECRET")

        self._room: Optional[rtc.Room] = None
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
            time.sleep(0.1)

    def _run_loop(self):
        """Run the event loop in background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _generate_token(self, room_name: str, identity: str) -> str:
        """Generate a LiveKit access token."""
        token = api.AccessToken(self.api_key, self.api_secret)
        token.with_identity(identity)
        token.with_name("Flask Query Sender")
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_publish_data=True,
            can_subscribe=False,
        ))
        return token.to_jwt()

    def connect(self, room_name: str) -> bool:
        """Connect to a LiveKit room."""
        if not self.is_configured:
            logger.error("LiveKit not configured")
            return False

        self._ensure_loop()

        future = asyncio.run_coroutine_threadsafe(
            self._connect_async(room_name),
            self._loop
        )
        try:
            return future.result(timeout=10)
        except Exception as e:
            logger.error(f"Connect error: {e}")
            return False

    async def _connect_async(self, room_name: str) -> bool:
        """Connect to LiveKit room asynchronously."""
        try:
            identity = f"flask-query-sender-{int(time.time())}"
            token = self._generate_token(room_name, identity)

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
        """Disconnect from the room."""
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
        if self._room:
            await self._room.disconnect()
            self._room = None
        self._connected = False
        logger.info(f"Disconnected from room {self._room_name}")

    def send_query(
        self,
        query: str,
        speaker: str = "User",
        context: dict = None
    ) -> bool:
        """
        Send a text query to the avatar agent.

        Args:
            query: The text query to process
            speaker: Name of the speaker
            context: Optional context data (conversation history, etc)

        Returns:
            True if query was sent successfully
        """
        if not self.is_connected:
            logger.warning("Not connected to room, cannot send query")
            return False

        future = asyncio.run_coroutine_threadsafe(
            self._send_query_async(query, speaker, context),
            self._loop
        )
        try:
            return future.result(timeout=5)
        except Exception as e:
            logger.error(f"Send query failed: {e}")
            return False

    async def _send_query_async(
        self,
        query: str,
        speaker: str,
        context: dict
    ) -> bool:
        """Send query via DataChannel asynchronously."""
        try:
            if not self._room or not self._room.isconnected():
                logger.error("Room not connected")
                return False

            # Build query message
            message = {
                "type": "query",
                "query": query,
                "speaker": speaker,
                "timestamp": time.time(),
                "context": context or {}
            }

            # Send via DataChannel (broadcast to all participants)
            data = json.dumps(message).encode("utf-8")
            await self._room.local_participant.publish_data(
                data,
                topic=QUERY_TOPIC,
                reliable=True
            )

            logger.info(f"Sent query to LiveKit room: {query[:50]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to send query: {e}")
            return False


# Singleton instance
_text_sender: Optional[LiveKitTextSender] = None
_sender_lock = threading.Lock()


def get_livekit_text_sender() -> LiveKitTextSender:
    """Get or create the LiveKit text sender singleton."""
    global _text_sender
    with _sender_lock:
        if _text_sender is None:
            _text_sender = LiveKitTextSender()
        return _text_sender


def send_query_to_livekit(
    room_name: str,
    query: str,
    speaker: str = "User",
    context: dict = None,
    async_send: bool = True
) -> bool:
    """
    Convenience function to send query to LiveKit avatar agent.

    Args:
        room_name: LiveKit room name
        query: Text query to send
        speaker: Speaker name
        context: Optional context data
        async_send: If True, send in background thread

    Returns:
        True if query was queued/sent successfully
    """
    if async_send:
        thread = threading.Thread(
            target=_send_query_sync,
            args=(room_name, query, speaker, context),
            daemon=True
        )
        thread.start()
        logger.debug(f"Queued query for LiveKit (async) in room {room_name}")
        return True
    else:
        return _send_query_sync(room_name, query, speaker, context)


def _send_query_sync(
    room_name: str,
    query: str,
    speaker: str,
    context: dict
) -> bool:
    """Synchronous implementation of send_query_to_livekit."""
    sender = get_livekit_text_sender()

    if not sender.is_configured:
        logger.warning("LiveKit not configured for text queries")
        return False

    # Connect if not already connected to this room
    if not sender.is_connected or sender._room_name != room_name:
        if sender.is_connected:
            sender.disconnect()
        if not sender.connect(room_name):
            logger.warning(f"Failed to connect to room {room_name}")
            return False

    return sender.send_query(query, speaker, context)
