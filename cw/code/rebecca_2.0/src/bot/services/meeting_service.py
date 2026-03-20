"""
Meeting Service for centralized meeting join operations.

Consolidates meeting joining logic previously duplicated across:
- routes/avatar.py (join_meeting_with_avatar)
- routes/zoom.py (_handle_meeting_join_request)
"""

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Optional, Any


@dataclass
class AvatarConfig:
    """Configuration for avatar page URL generation."""
    mode: str  # 'websocket', 'livekit', or 'auto'
    bot_id: str
    page_url: str
    room_name: Optional[str] = None


@dataclass
class MeetingJoinResult:
    """Result of a meeting join operation."""
    success: bool
    message: str
    bot_id: Optional[str] = None
    meeting_id: Optional[str] = None
    avatar_enabled: bool = False
    avatar_mode: Optional[str] = None
    avatar_page_url: Optional[str] = None
    livekit_room: Optional[str] = None
    error: Optional[str] = None


class MeetingService:
    """
    Centralized service for meeting join operations.

    Handles:
    - Avatar page URL generation
    - Bot ID generation
    - Meeting handler invocation
    - WebSocket ID mapping registration
    """

    def __init__(
        self,
        meeting_handler: Optional[Any] = None,
        ws_manager: Optional[Any] = None,
        public_url: Optional[str] = None,
        default_bot_name: str = "QA Bot",
        logger: Optional[logging.Logger] = None
    ):
        self.meeting_handler = meeting_handler
        self.ws_manager = ws_manager
        self.public_url = public_url
        self.default_bot_name = default_bot_name
        self.logger = logger or logging.getLogger("qa_agent")

    def generate_bot_id(self, meeting_url: str) -> str:
        """
        Generate a unique bot ID for a meeting.

        Uses meeting URL hash + timestamp to ensure uniqueness
        and force fresh WebSocket connections.

        Args:
            meeting_url: The meeting URL

        Returns:
            Unique bot ID string
        """
        meeting_hash = hashlib.md5(meeting_url.encode()).hexdigest()[:8]
        timestamp = int(time.time()) % 10000
        return f"qa-bot-{meeting_hash}-{timestamp}"

    def build_avatar_config(
        self,
        meeting_url: str,
        mode: str = "websocket",
        base_url: Optional[str] = None
    ) -> AvatarConfig:
        """
        Build avatar configuration including page URL.

        Args:
            meeting_url: Meeting URL for ID generation
            mode: Avatar mode ('websocket', 'livekit', or 'auto')
            base_url: Base URL for avatar page (defaults to public_url)

        Returns:
            AvatarConfig with bot_id, page_url, and mode
        """
        base_url = base_url or self.public_url
        if not base_url:
            raise ValueError("No base URL configured for avatar page")

        bot_id = self.generate_bot_id(meeting_url)
        timestamp = int(time.time()) % 10000
        room_name = None

        # Check LiveKit availability if mode is auto or livekit
        livekit_available = False
        if mode in ("auto", "livekit"):
            try:
                from ...avatar.livekit_manager import get_livekit_manager
                livekit_manager = get_livekit_manager()
                livekit_available = livekit_manager.is_configured
            except ImportError:
                pass

        # Determine actual mode
        # NOTE: LiveKit/Simli disabled for reliability - using pulsing orb
        actual_mode = "websocket"  # Force websocket mode for now

        # Build page URL based on mode
        meeting_hash = hashlib.md5(meeting_url.encode()).hexdigest()[:8]
        if actual_mode == "livekit" and livekit_available:
            room_name = f"avatar-{meeting_hash}-{timestamp}"
            page_url = f"{base_url}/avatar/page?mode=livekit&room={room_name}&bot_id={bot_id}&t={timestamp}"
        else:
            page_url = f"{base_url}/avatar/page?mode=websocket&bot_id={bot_id}&t={timestamp}"

        self.logger.debug(f"Avatar config: mode={actual_mode}, url={page_url}")

        return AvatarConfig(
            mode=actual_mode,
            bot_id=bot_id,
            page_url=page_url,
            room_name=room_name
        )

    def join_meeting(
        self,
        meeting_url: str,
        requested_by: str,
        bot_name: Optional[str] = None,
        channel_id: Optional[str] = None,
        with_avatar: bool = True,
        avatar_mode: str = "websocket"
    ) -> MeetingJoinResult:
        """
        Join a meeting with optional avatar support.

        Args:
            meeting_url: Meeting URL to join
            requested_by: User/API requesting the join
            bot_name: Display name for the bot
            channel_id: Channel ID for callbacks
            with_avatar: Whether to enable avatar
            avatar_mode: Avatar mode if enabled

        Returns:
            MeetingJoinResult with join status and details
        """
        if not self.meeting_handler:
            return MeetingJoinResult(
                success=False,
                message="Meeting integration not configured",
                error="meeting_handler_not_configured"
            )

        bot_name = bot_name or self.default_bot_name
        avatar_config = None
        output_media_url = None
        variant = None

        # Build avatar config if enabled and public URL available
        if with_avatar and self.public_url:
            try:
                avatar_config = self.build_avatar_config(
                    meeting_url=meeting_url,
                    mode=avatar_mode,
                    base_url=self.public_url
                )
                output_media_url = avatar_config.page_url
                variant = "web_gpu"
                self.logger.info(f"Avatar page URL: {output_media_url}")
            except Exception as e:
                self.logger.warning(f"Failed to build avatar config: {e}")
                avatar_config = None

        try:
            # Join the meeting
            result = self.meeting_handler.join_meeting(
                meeting_url=meeting_url,
                requested_by=requested_by,
                channel_id=channel_id,
                bot_name=bot_name,
                output_media_url=output_media_url,
                variant=variant,
                audio_bot_id=avatar_config.bot_id if avatar_config else None,
                livekit_room=avatar_config.room_name if avatar_config else None,
            )

            if result.get("status") == "error":
                return MeetingJoinResult(
                    success=False,
                    message=f"Failed to join: {result.get('error', 'Unknown error')}",
                    error=result.get("error")
                )

            # Register WebSocket ID mapping if avatar enabled
            recall_bot_id = result.get("bot_id")
            if recall_bot_id and avatar_config and self.ws_manager:
                self.ws_manager.add_id_mapping(recall_bot_id, avatar_config.bot_id)
                self.logger.info(
                    f"ID mapping added: {recall_bot_id[:8]}... <-> {avatar_config.bot_id}"
                )

            return MeetingJoinResult(
                success=True,
                message="Bot joining meeting",
                bot_id=recall_bot_id,
                meeting_id=result.get("meeting_id"),
                avatar_enabled=avatar_config is not None,
                avatar_mode=avatar_config.mode if avatar_config else None,
                avatar_page_url=avatar_config.page_url if avatar_config else None,
                livekit_room=avatar_config.room_name if avatar_config else None,
            )

        except Exception as e:
            self.logger.error(f"Meeting join error: {e}", exc_info=True)
            return MeetingJoinResult(
                success=False,
                message=f"Error joining meeting: {e}",
                error=str(e)
            )

    def join_meeting_for_chat(
        self,
        meeting_url: str,
        user_id: str,
        user_name: str,
        request_id: str
    ) -> str:
        """
        Join a meeting from a chat command.

        Returns a human-readable response message.

        Args:
            meeting_url: Meeting URL to join
            user_id: User who requested the join
            user_name: User's display name
            request_id: Request ID for logging

        Returns:
            Response message for the user
        """
        result = self.join_meeting(
            meeting_url=meeting_url,
            requested_by=user_id,
            with_avatar=True,
            avatar_mode="websocket"
        )

        if not result.success:
            return result.message

        # Build success message
        bot_status = "joining" if result.bot_id else "requested"
        message = f"I'm {bot_status} the meeting"

        if result.avatar_enabled:
            message += " with avatar enabled"
        message += ". I'll be ready to assist shortly!"

        return message
