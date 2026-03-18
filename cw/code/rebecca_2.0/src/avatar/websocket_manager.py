"""
WebSocket manager for avatar audio streaming.

Manages WebSocket connections between the backend and avatar webpages.
Each bot has its own WebSocket channel for real-time audio delivery.
"""
import base64
from collections import OrderedDict
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Dict, Optional, Any
from dataclasses import dataclass, field


@dataclass
class AvatarConnection:
    """Represents a connected avatar webpage."""
    bot_id: str
    ws: Any  # WebSocket connection
    connected_at: float = field(default_factory=time.time)
    last_ping: float = field(default_factory=time.time)
    last_audio_sent: float = 0
    audio_sent_count: int = 0
    total_bytes_sent: int = 0
    last_state: str = "connected"
    errors: int = 0


class AvatarWebSocketManager:
    """
    Manages WebSocket connections for avatar audio streaming.

    Thread-safe manager that routes audio to the correct avatar webpage
    based on bot_id or meeting_id. Supports multiple concurrent bot sessions.

    Connections can be registered with either:
    - bot_id: The Recall.ai bot ID (used by voice pipeline)
    - meeting_id: Our internal meeting ID (used by avatar page URL)

    The manager maintains mappings between them for proper routing.
    ID mappings are persisted in SQLite to survive server restarts.
    """

    # Ping interval for keepalive
    PING_INTERVAL_SECONDS = 30

    # Mapping expiry time (24 hours)
    MAPPING_EXPIRY_SECONDS = 86400

    # Memory safety: Max concurrent connections and mappings
    MAX_CONNECTIONS = 100
    MAX_INMEMORY_MAPPINGS = 1000  # 500 bidirectional pairs

    # Stale connection cleanup settings
    STALE_CONNECTION_SECONDS = 300  # 5 minutes without ping
    MAX_ERRORS_BEFORE_EVICT = 10

    def __init__(self, logger: logging.Logger = None, db_path: str = None):
        """
        Initialize the WebSocket manager.

        Args:
            logger: Logger instance
            db_path: Path to SQLite database for persistent mappings
        """
        self.logger = logger or logging.getLogger("qa_agent")
        # Use OrderedDict for LRU eviction when max connections reached
        self._connections: OrderedDict[str, AvatarConnection] = OrderedDict()
        self._lock = threading.RLock()

        # In-memory cache of ID mappings (loaded from DB)
        # Uses OrderedDict for LRU eviction when max mappings reached
        self._id_mappings: OrderedDict[str, str] = OrderedDict()

        # Database path for persistent mappings
        self._db_path = db_path or os.environ.get("DB_PATH", "data/state.db")

        # Initialize database table
        self._init_db()

        # Load existing mappings from database
        self._load_mappings_from_db()

        # Metrics
        self._total_connections = 0
        self._total_audio_sent = 0

        # Start background cleanup thread for stale connections
        self._cleanup_thread = None
        self._shutdown_cleanup = False
        self._start_cleanup_thread()

    def _init_db(self):
        """Initialize the ID mappings table in SQLite."""
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS avatar_id_mappings (
                    meeting_id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            # Create index for bot_id lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_avatar_mappings_bot_id
                ON avatar_id_mappings(bot_id)
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.error(f"Failed to initialize avatar_id_mappings table: {e}")

    def _load_mappings_from_db(self):
        """Load ID mappings from database into memory cache."""
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            # Clean up expired mappings
            expiry_time = time.time() - self.MAPPING_EXPIRY_SECONDS
            cursor.execute(
                "DELETE FROM avatar_id_mappings WHERE created_at < ?",
                (expiry_time,)
            )
            conn.commit()

            # Load active mappings
            cursor.execute("SELECT meeting_id, bot_id FROM avatar_id_mappings")
            rows = cursor.fetchall()
            conn.close()

            with self._lock:
                self._id_mappings.clear()
                for meeting_id, bot_id in rows:
                    # Only load up to max mappings
                    if len(self._id_mappings) < self.MAX_INMEMORY_MAPPINGS:
                        self._id_mappings[meeting_id] = bot_id
                        self._id_mappings[bot_id] = meeting_id

            self.logger.debug(f"Loaded {len(rows)} ID mappings from database")
        except Exception as e:
            self.logger.error(f"Failed to load ID mappings from database: {e}")

    def _start_cleanup_thread(self):
        """Start background thread for periodic cleanup of stale connections."""
        def cleanup_loop():
            while not self._shutdown_cleanup:
                time.sleep(60)  # Run every minute
                if not self._shutdown_cleanup:
                    self._cleanup_stale_connections()

        self._cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        self.logger.debug("Started WebSocket cleanup thread")

    def _cleanup_stale_connections(self):
        """Remove stale or unhealthy connections.

        Memory safety: Removes connections that haven't pinged in 5 minutes
        or have exceeded error threshold.
        """
        now = time.time()
        with self._lock:
            to_remove = []
            for bot_id, conn in self._connections.items():
                # Remove if stale (no ping in STALE_CONNECTION_SECONDS)
                if now - conn.last_ping > self.STALE_CONNECTION_SECONDS:
                    to_remove.append(bot_id)
                    self.logger.info(f"Removing stale connection: {bot_id}")
                # Remove if too many errors
                elif conn.errors >= self.MAX_ERRORS_BEFORE_EVICT:
                    to_remove.append(bot_id)
                    self.logger.info(f"Removing error-prone connection: {bot_id}")

            for bot_id in to_remove:
                try:
                    self._connections[bot_id].ws.close()
                except Exception:
                    pass
                del self._connections[bot_id]

            if to_remove:
                self.logger.info(f"Cleaned up {len(to_remove)} stale connections")

    def get_bot_id(self, meeting_id: str) -> str | None:
        """
        Get the bot_id for a given meeting_id.

        Args:
            meeting_id: Our internal meeting ID

        Returns:
            The Recall.ai bot_id, or None if not found
        """
        with self._lock:
            bot_id = self._id_mappings.get(meeting_id)
            # Only return if it looks like a bot_id (UUID format)
            if bot_id and '-' in bot_id:
                return bot_id
            return None

    def add_id_mapping(self, meeting_id: str, bot_id: str):
        """
        Add a mapping between meeting_id and bot_id.

        This allows connections registered with meeting_id to receive
        audio sent to bot_id, and vice versa. Mappings are persisted
        to SQLite to survive server restarts.

        Memory safety: Bounded to MAX_INMEMORY_MAPPINGS entries with LRU eviction.

        Args:
            meeting_id: Our internal meeting ID
            bot_id: Recall.ai bot ID
        """
        with self._lock:
            # Evict oldest mappings if at capacity (need room for 2 entries)
            while len(self._id_mappings) >= self.MAX_INMEMORY_MAPPINGS - 1:
                self._id_mappings.popitem(last=False)

            self._id_mappings[meeting_id] = bot_id
            self._id_mappings[bot_id] = meeting_id

        # Persist to database
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO avatar_id_mappings (meeting_id, bot_id, created_at)
                VALUES (?, ?, ?)
            """, (meeting_id, bot_id, time.time()))
            conn.commit()
            conn.close()
            self.logger.debug(f"ID mapping added and persisted: {meeting_id} <-> {bot_id}")
        except Exception as e:
            self.logger.error(f"Failed to persist ID mapping: {e}")
            # Still works in-memory even if DB fails

    def _resolve_id(self, session_id: str) -> str:
        """
        Resolve a session ID to find connected socket.

        Checks both direct connection and mapped IDs.

        Args:
            session_id: bot_id or meeting_id

        Returns:
            The ID that has an active connection, or original ID if not found
        """
        # Direct connection
        if session_id in self._connections:
            return session_id

        # Check mapped ID
        mapped_id = self._id_mappings.get(session_id)
        if mapped_id and mapped_id in self._connections:
            return mapped_id

        return session_id

    def register(self, bot_id: str, ws: Any) -> bool:
        """
        Register a new WebSocket connection for a bot.

        Memory safety: Bounded to MAX_CONNECTIONS with oldest eviction.

        Args:
            bot_id: Bot ID for routing
            ws: WebSocket connection object

        Returns:
            True if registered successfully
        """
        with self._lock:
            # Close existing connection if any
            if bot_id in self._connections:
                self.logger.warning(f"Replacing existing connection for bot {bot_id}")
                try:
                    old_ws = self._connections[bot_id].ws
                    old_ws.close()
                except Exception:
                    pass
                del self._connections[bot_id]

            # Enforce max connections
            if len(self._connections) >= self.MAX_CONNECTIONS:
                # First try to clean stale connections
                self._cleanup_stale_connections()

                # If still at limit, evict oldest connection
                if len(self._connections) >= self.MAX_CONNECTIONS:
                    oldest_id, oldest_conn = self._connections.popitem(last=False)
                    try:
                        oldest_conn.ws.close()
                    except Exception:
                        pass
                    self.logger.warning(f"Evicted oldest connection: {oldest_id}")

            self._connections[bot_id] = AvatarConnection(
                bot_id=bot_id,
                ws=ws
            )
            self._total_connections += 1

            self.logger.info(f"Avatar WebSocket registered: bot_id={bot_id}")
            return True

    def unregister(self, bot_id: str) -> bool:
        """
        Unregister a WebSocket connection.

        Args:
            bot_id: Bot ID to unregister

        Returns:
            True if unregistered successfully
        """
        with self._lock:
            if bot_id in self._connections:
                conn = self._connections.pop(bot_id)
                self.logger.info(
                    f"Avatar WebSocket unregistered: bot_id={bot_id}, "
                    f"audio_sent={conn.audio_sent_count}, "
                    f"bytes_sent={conn.total_bytes_sent}"
                )
                return True
            return False

    def is_connected(self, session_id: str) -> bool:
        """Check if a bot/meeting has an active WebSocket connection."""
        with self._lock:
            resolved_id = self._resolve_id(session_id)
            return resolved_id in self._connections

    def send_audio(
        self,
        session_id: str,
        audio_data: bytes,
        audio_format: str = "mp3"
    ) -> bool:
        """
        Send audio data to an avatar webpage.

        Args:
            session_id: Bot ID or meeting ID to send to
            audio_data: Raw audio bytes
            audio_format: Audio format (mp3, wav, etc.)

        Returns:
            True if sent successfully
        """
        with self._lock:
            resolved_id = self._resolve_id(session_id)
            conn = self._connections.get(resolved_id)
            if not conn:
                self.logger.warning(f"No WebSocket connection for {session_id} (resolved: {resolved_id})")
                return False

        try:
            # Encode audio as base64 for JSON transport
            b64_audio = base64.b64encode(audio_data).decode('utf-8')

            message = json.dumps({
                "type": "audio",
                "data": b64_audio,
                "format": audio_format,
                "timestamp": time.time()
            })

            # Council fix: send inside try block, handle connection errors
            conn.ws.send(message)

            # Update metrics
            with self._lock:
                conn.audio_sent_count += 1
                conn.total_bytes_sent += len(audio_data)
                conn.last_audio_sent = time.time()
                self._total_audio_sent += 1

            self.logger.debug(
                f"Audio sent to {session_id}: "
                f"{len(audio_data)} bytes, format={audio_format}"
            )
            return True

        except (ConnectionError, BrokenPipeError, OSError) as e:
            # Connection closed - unregister and return False
            self.logger.warning(f"Connection closed for {session_id}: {e}")
            self.unregister(resolved_id)
            return False
        except Exception as e:
            self.logger.error(f"Failed to send audio to {session_id}: {e}")
            # Connection might be dead, unregister it
            self.unregister(resolved_id)
            return False

    def send_state(self, session_id: str, state: str, message: str = None) -> bool:
        """
        Send state update to avatar webpage.

        Args:
            session_id: Bot ID or meeting ID to send to
            state: State name (listening, speaking, thinking, error)
            message: Optional status message

        Returns:
            True if sent successfully
        """
        with self._lock:
            resolved_id = self._resolve_id(session_id)
            conn = self._connections.get(resolved_id)
            if not conn:
                return False

        try:
            msg = json.dumps({
                "type": "state",
                "state": state,
                "message": message or state.replace("_", " ").title()
            })
            conn.ws.send(msg)
            return True
        except Exception as e:
            self.logger.error(f"Failed to send state to {session_id}: {e}")
            return False

    def send_video_frame(
        self,
        session_id: str,
        frame: bytes,
        frame_format: str = "jpeg"
    ) -> bool:
        """
        Send video frame to avatar webpage for rendering.

        Council fix: Implements complete video frame protocol.

        Args:
            session_id: Bot ID or meeting ID to send to
            frame: Raw frame bytes (JPEG or PNG)
            frame_format: Frame format (jpeg, png)

        Returns:
            True if sent successfully
        """
        with self._lock:
            resolved_id = self._resolve_id(session_id)
            conn = self._connections.get(resolved_id)
            if not conn:
                self.logger.debug(f"No connection for video frame: {session_id}")
                return False

        try:
            # Base64 encode for JSON transport
            # Council note: For higher performance, consider binary WebSocket messages
            b64_frame = base64.b64encode(frame).decode('utf-8')

            message = json.dumps({
                "type": "video_frame",
                "data": b64_frame,
                "format": frame_format,
                "timestamp": time.time()
            })

            conn.ws.send(message)

            # Update metrics
            with self._lock:
                conn.audio_sent_count += 1  # Reusing counter for frames
                conn.total_bytes_sent += len(frame)
                conn.last_audio_sent = time.time()

            self.logger.debug(
                f"Video frame sent to {session_id}: "
                f"{len(frame)} bytes, format={frame_format}"
            )
            return True

        except (ConnectionError, BrokenPipeError, OSError) as e:
            self.logger.warning(f"Connection closed for {session_id}: {e}")
            self.unregister(resolved_id)
            return False
        except Exception as e:
            self.logger.error(f"Failed to send video frame to {session_id}: {e}")
            return False

    def get_connection_count(self) -> int:
        """Get number of active connections."""
        with self._lock:
            return len(self._connections)

    def get_stats(self) -> dict:
        """Get manager statistics."""
        with self._lock:
            return {
                "active_connections": len(self._connections),
                "total_connections": self._total_connections,
                "total_audio_sent": self._total_audio_sent,
                "connected_bots": list(self._connections.keys())
            }

    def get_connection_health(self) -> dict:
        """
        Get detailed health information for all connections.

        Returns:
            Dictionary with connection health details for dashboard display
        """
        now = time.time()
        with self._lock:
            connections = []
            for bot_id, conn in self._connections.items():
                connection_age = now - conn.connected_at
                time_since_audio = now - conn.last_audio_sent if conn.last_audio_sent > 0 else None
                time_since_ping = now - conn.last_ping

                # Determine health status
                if conn.errors > 5:
                    health = "unhealthy"
                elif time_since_ping > 60:
                    health = "stale"
                elif time_since_audio and time_since_audio > 300:
                    health = "idle"
                else:
                    health = "healthy"

                connections.append({
                    "bot_id": bot_id,
                    "health": health,
                    "connected_at": conn.connected_at,
                    "connection_age_seconds": round(connection_age, 1),
                    "last_ping_seconds_ago": round(time_since_ping, 1),
                    "last_audio_seconds_ago": round(time_since_audio, 1) if time_since_audio is not None else None,
                    "audio_sent_count": conn.audio_sent_count,
                    "total_bytes_sent": conn.total_bytes_sent,
                    "total_kb_sent": round(conn.total_bytes_sent / 1024, 2),
                    "last_state": conn.last_state,
                    "errors": conn.errors
                })

            # Calculate summary stats
            healthy_count = sum(1 for c in connections if c["health"] == "healthy")
            total_bytes = sum(c["total_bytes_sent"] for c in connections)

            return {
                "timestamp": now,
                "summary": {
                    "total_connections": len(connections),
                    "healthy": healthy_count,
                    "unhealthy": len(connections) - healthy_count,
                    "total_lifetime_connections": self._total_connections,
                    "total_audio_messages": self._total_audio_sent,
                    "total_bytes_sent": total_bytes,
                    "total_mb_sent": round(total_bytes / (1024 * 1024), 2)
                },
                "connections": connections,
                "id_mappings_count": len(self._id_mappings) // 2  # Each mapping stored twice
            }

    def update_connection_state(self, session_id: str, state: str) -> None:
        """Update the last known state for a connection."""
        with self._lock:
            resolved_id = self._resolve_id(session_id)
            conn = self._connections.get(resolved_id)
            if conn:
                conn.last_state = state

    def record_error(self, session_id: str) -> None:
        """Record an error for a connection."""
        with self._lock:
            resolved_id = self._resolve_id(session_id)
            conn = self._connections.get(resolved_id)
            if conn:
                conn.errors += 1


# Global singleton instance
_manager: Optional[AvatarWebSocketManager] = None
_manager_lock = threading.Lock()


def get_avatar_ws_manager(logger: logging.Logger = None) -> AvatarWebSocketManager:
    """
    Get or create the global WebSocket manager instance.

    Args:
        logger: Logger instance (only used on first call)

    Returns:
        AvatarWebSocketManager singleton
    """
    global _manager

    with _manager_lock:
        if _manager is None:
            _manager = AvatarWebSocketManager(logger=logger)
        return _manager
