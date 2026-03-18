"""
LiveKit room manager for avatar sessions.

Manages LiveKit rooms, generates access tokens, and coordinates
the avatar agent lifecycle.
"""
import asyncio
import logging
import os
import time
import threading
from typing import Dict, Optional, Callable

# LiveKit imports
try:
    from livekit import api
    from livekit.agents import WorkerOptions, cli
    LIVEKIT_AVAILABLE = True
except ImportError:
    LIVEKIT_AVAILABLE = False
    api = None

logger = logging.getLogger("qa_agent.livekit_manager")


class LiveKitRoomManager:
    """
    Manages LiveKit rooms for avatar sessions.

    Responsibilities:
    - Create/delete rooms for meetings
    - Generate access tokens for avatar page
    - Start avatar agents in rooms
    - Track active sessions
    """

    def __init__(
        self,
        livekit_url: str = None,
        api_key: str = None,
        api_secret: str = None,
    ):
        """
        Initialize LiveKit room manager.

        Args:
            livekit_url: LiveKit server URL (or LIVEKIT_URL env var)
            api_key: LiveKit API key (or LIVEKIT_API_KEY env var)
            api_secret: LiveKit API secret (or LIVEKIT_API_SECRET env var)
        """
        self.livekit_url = livekit_url or os.getenv("LIVEKIT_URL")
        self.api_key = api_key or os.getenv("LIVEKIT_API_KEY")
        self.api_secret = api_secret or os.getenv("LIVEKIT_API_SECRET")

        # Validate configuration
        if not all([self.livekit_url, self.api_key, self.api_secret]):
            logger.warning("LiveKit not fully configured")
            self._configured = False
        else:
            self._configured = True
            logger.info(f"LiveKit manager initialized: {self.livekit_url}")

        # Track active rooms: room_name -> session_info
        self._rooms: Dict[str, dict] = {}
        self._rooms_lock = threading.Lock()

        # Avatar agent reference (GLOBAL - one agent serves all rooms)
        self._agent_thread: Optional[threading.Thread] = None
        self._agent_running = False
        self._agent_process = None  # Global agent subprocess
        self._agent_start_time: float = 0  # When agent was started
        self._agent_lock = threading.Lock()  # Prevent concurrent agent starts
        self._MIN_AGENT_UPTIME = 5.0  # Seconds to wait before restart allowed

    @property
    def is_configured(self) -> bool:
        """Check if LiveKit is properly configured."""
        return self._configured and LIVEKIT_AVAILABLE

    def generate_token(
        self,
        room_name: str,
        participant_name: str = "avatar-viewer",
        can_publish: bool = False,
        can_subscribe: bool = True,
        ttl_seconds: int = 3600,
    ) -> Optional[str]:
        """
        Generate a LiveKit access token.

        Args:
            room_name: Name of the room to join
            participant_name: Display name for the participant
            can_publish: Whether participant can publish tracks
            can_subscribe: Whether participant can subscribe to tracks
            ttl_seconds: Token validity duration

        Returns:
            JWT token string or None if not configured
        """
        if not self.is_configured:
            logger.error("LiveKit not configured, cannot generate token")
            return None

        try:
            from datetime import timedelta

            # Create access token with grants
            token = api.AccessToken(self.api_key, self.api_secret)
            token.with_identity(participant_name)
            token.with_name(participant_name)
            token.with_ttl(timedelta(seconds=ttl_seconds))

            # Add room grant
            grant = api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=can_publish,
                can_subscribe=can_subscribe,
            )
            token.with_grants(grant)

            jwt = token.to_jwt()
            logger.debug(f"Generated token for {participant_name} in room {room_name}")
            return jwt

        except Exception as e:
            logger.error(f"Failed to generate token: {e}")
            return None

    def create_room(
        self,
        room_name: str,
        meeting_id: str = None,
        empty_timeout: int = 300,
    ) -> bool:
        """
        Create a LiveKit room for an avatar session.

        Args:
            room_name: Name for the room
            meeting_id: Associated meeting ID
            empty_timeout: Seconds to keep room alive when empty

        Returns:
            True if room created successfully
        """
        if not self.is_configured:
            return False

        with self._rooms_lock:
            if room_name in self._rooms:
                logger.info(f"Room {room_name} already exists")
                return True

            self._rooms[room_name] = {
                "meeting_id": meeting_id,
                "created_at": time.time(),
                "agent_started": False,
            }
            logger.info(f"Created room: {room_name} for meeting {meeting_id}")
            return True

    def delete_room(self, room_name: str) -> bool:
        """
        Delete a LiveKit room.

        Args:
            room_name: Name of room to delete

        Returns:
            True if deleted
        """
        with self._rooms_lock:
            if room_name in self._rooms:
                del self._rooms[room_name]
                logger.info(f"Deleted room: {room_name}")
                return True
            return False

    def get_room_for_meeting(self, meeting_id: str) -> Optional[str]:
        """
        Get the room name for a meeting.

        Args:
            meeting_id: Meeting identifier

        Returns:
            Room name or None
        """
        with self._rooms_lock:
            for room_name, info in self._rooms.items():
                if info.get("meeting_id") == meeting_id:
                    return room_name
            return None

    def get_or_create_room(self, meeting_id: str) -> str:
        """
        Get existing room or create new one for meeting.

        Args:
            meeting_id: Meeting identifier

        Returns:
            Room name
        """
        existing = self.get_room_for_meeting(meeting_id)
        if existing:
            return existing

        # Create new room with meeting ID as name
        room_name = f"qa-bot-{meeting_id}"
        self.create_room(room_name, meeting_id)
        return room_name

    def _is_agent_healthy(self) -> bool:
        """
        Check if the global agent process is healthy.

        Returns:
            True if agent is running and healthy
        """
        if not self._agent_process:
            return False

        # Check if process is alive
        if self._agent_process.poll() is not None:
            return False

        # If within startup grace period, assume healthy
        elapsed = time.time() - self._agent_start_time
        if elapsed < self._MIN_AGENT_UPTIME:
            logger.debug(f"Agent in startup grace period ({elapsed:.1f}s < {self._MIN_AGENT_UPTIME}s)")
            return True

        return True

    def _kill_agent_process(self) -> None:
        """Kill any existing agent process."""
        if self._agent_process:
            try:
                self._agent_process.terminate()
                self._agent_process.wait(timeout=5)
                logger.info(f"Terminated agent process (pid={self._agent_process.pid})")
            except Exception as e:
                logger.warning(f"Failed to terminate agent gracefully: {e}")
                try:
                    self._agent_process.kill()
                    logger.info("Force killed agent process")
                except Exception:
                    pass
            finally:
                self._agent_process = None
                self._agent_running = False
                self._agent_start_time = 0

    def start_avatar_agent(
        self,
        room_name: str,
        query_handler: Callable[[str], str],
    ) -> bool:
        """
        Start the avatar agent in a room.

        The agent is GLOBAL - one instance serves all rooms via auto-dispatch.
        This method ensures only one agent process runs at a time.

        The agent will:
        - Join the room
        - Listen for speech via Deepgram STT
        - Process queries via the handler
        - Respond via Cartesia TTS
        - Animate Simli avatar

        Args:
            room_name: Room to join
            query_handler: Function to process user queries

        Returns:
            True if agent started or already running
        """
        if not self.is_configured:
            logger.error("LiveKit not configured")
            return False

        # Validate room exists
        with self._rooms_lock:
            if room_name not in self._rooms:
                logger.error(f"Room {room_name} does not exist")
                return False

        # Use agent lock to prevent concurrent starts
        with self._agent_lock:
            # Check if agent is already healthy
            if self._is_agent_healthy():
                logger.info(f"Agent already running (pid={self._agent_process.pid}), dispatching to {room_name}")
                self._dispatch_agent_to_room(room_name)
                return True

            # Kill any zombie process
            if self._agent_process:
                logger.info("Previous agent process is not healthy, killing...")
                self._kill_agent_process()

            try:
                import subprocess
                import sys

                # Start agent as a subprocess (required because LiveKit plugins must register on main thread)
                agent_script = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "platform",
                    "livekit_avatar.py"
                )

                # Start the subprocess (LiveKit agent auto-dispatches to rooms)
                logger.info(f"Starting avatar agent subprocess for room {room_name}")

                # Write subprocess output to log file for debugging
                log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
                os.makedirs(log_dir, exist_ok=True)
                log_file = os.path.join(log_dir, f"avatar_agent_{room_name}.log")
                log_handle = open(log_file, "w")
                logger.info(f"Avatar agent logs will be written to: {log_file}")

                process = subprocess.Popen(
                    [sys.executable, agent_script, "start"],
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,  # Combine stderr with stdout
                    cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    env={**os.environ},  # Pass environment variables
                )

                self._agent_process = process
                self._agent_running = True
                self._agent_start_time = time.time()

                with self._rooms_lock:
                    self._rooms[room_name]["agent_started"] = True

                logger.info(f"Avatar agent subprocess started (pid={process.pid})")

                # NOTE: Do NOT manually dispatch - LiveKit auto-dispatches when agent registers
                # Manual dispatch was causing duplicate agents and hitting Simli rate limits
                # self._dispatch_agent_to_room(room_name)

                return True

            except ImportError as e:
                logger.error(f"LiveKit agent import failed: {e}")
                return False
            except Exception as e:
                logger.error(f"Failed to start avatar agent: {e}")
                return False

    def _dispatch_agent_to_room(self, room_name: str):
        """
        Explicitly dispatch an agent to a room via LiveKit API.

        This is needed when the room exists before the agent registers.
        Prevents duplicate dispatches to the same room.
        """
        import asyncio
        import threading

        # Check if already dispatched to this room
        with self._rooms_lock:
            if room_name in self._rooms:
                if self._rooms[room_name].get("dispatch_pending") or self._rooms[room_name].get("dispatched"):
                    logger.info(f"Dispatch already pending/done for room {room_name}, skipping")
                    return
                self._rooms[room_name]["dispatch_pending"] = True

        def dispatch_async():
            try:
                # Wait for agent to register
                import time
                time.sleep(3)

                # Create dispatch request via LiveKit API
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._do_dispatch(room_name))
                    # Mark as dispatched
                    with self._rooms_lock:
                        if room_name in self._rooms:
                            self._rooms[room_name]["dispatched"] = True
                            self._rooms[room_name]["dispatch_pending"] = False
                finally:
                    loop.close()
            except Exception as e:
                logger.error(f"Failed to dispatch agent to room {room_name}: {e}")
                with self._rooms_lock:
                    if room_name in self._rooms:
                        self._rooms[room_name]["dispatch_pending"] = False

        # Run dispatch in background thread
        thread = threading.Thread(target=dispatch_async, daemon=True)
        thread.start()

    async def _do_dispatch(self, room_name: str):
        """Perform the actual agent dispatch via LiveKit API."""
        try:
            lk_api = api.LiveKitAPI(
                self.livekit_url.replace("wss://", "https://"),
                self.api_key,
                self.api_secret,
            )

            # Create agent dispatch request
            dispatch = await lk_api.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    room=room_name,
                    # No agent_name means dispatch to any available agent
                )
            )
            logger.info(f"Agent dispatched to room {room_name}: {dispatch.id}")

        except Exception as e:
            logger.error(f"Agent dispatch error: {e}")

    def stop_avatar_agent(self, room_name: str = None, force_kill: bool = False) -> bool:
        """
        Stop the avatar agent.

        Since the agent is global, this stops it for all rooms.
        Use force_kill=True to immediately terminate the process.

        Args:
            room_name: Room name (optional, for logging)
            force_kill: Whether to immediately kill the process

        Returns:
            True if stopped
        """
        with self._agent_lock:
            with self._rooms_lock:
                # Clear agent_started flag for all rooms
                for room in self._rooms.values():
                    room["agent_started"] = False

            if force_kill:
                self._kill_agent_process()
                logger.info(f"Avatar agent force killed (room: {room_name})")
            else:
                # Mark as not running, let process finish naturally
                self._agent_running = False
                logger.info(f"Avatar agent stop requested (room: {room_name})")

        return True

    def get_room_info(self, room_name: str) -> Optional[dict]:
        """
        Get information about a room.

        Args:
            room_name: Room name

        Returns:
            Room info dict or None
        """
        with self._rooms_lock:
            return self._rooms.get(room_name)

    def list_rooms(self) -> list:
        """List all active rooms."""
        with self._rooms_lock:
            return list(self._rooms.keys())

    def get_connection_info(self, room_name: str) -> dict:
        """
        Get connection info for a room.

        Args:
            room_name: Room name

        Returns:
            Dict with url and token for connecting
        """
        token = self.generate_token(room_name)
        return {
            "url": self.livekit_url,
            "token": token,
            "room": room_name,
        }

    def generate_viewer_token(self, room_name: str) -> Optional[dict]:
        """
        Generate a viewer-only token for the avatar page.

        This token allows the avatar page (loaded by Recall.ai) to:
        - Join the LiveKit room
        - Subscribe to the agent's video track
        - NOT publish any tracks

        Args:
            room_name: Room to join

        Returns:
            Dict with url, token, and room, or None if error
        """
        if not self.is_configured:
            logger.error("LiveKit not configured")
            return None

        # Generate unique viewer identity
        viewer_identity = f"avatar-viewer-{room_name}-{int(time.time())}"

        token = self.generate_token(
            room_name=room_name,
            participant_name=viewer_identity,
            can_publish=False,  # Viewer only - no publishing
            can_subscribe=True,  # Can subscribe to agent's video
            ttl_seconds=3600,  # 1 hour validity
        )

        if not token:
            return None

        return {
            "url": self.livekit_url,
            "token": token,
            "room": room_name,
        }


# Singleton instance
_livekit_manager: Optional[LiveKitRoomManager] = None


def get_livekit_manager() -> LiveKitRoomManager:
    """Get or create the LiveKit manager singleton."""
    global _livekit_manager
    if _livekit_manager is None:
        _livekit_manager = LiveKitRoomManager()
    return _livekit_manager
