"""
Zoom Team Chat channel adapter.

Handles formatting and delivery of messages to Zoom Team Chat.
"""

import logging
import time
from datetime import datetime
from typing import Any

from .base import ChannelAdapter, ChannelType, Message, DeliveryResult


class ZoomChannelAdapter(ChannelAdapter):
    """
    Adapter for Zoom Team Chat delivery.

    Formats messages for Zoom's markdown subset and handles
    delivery with automatic retry logic.
    """

    def __init__(
        self,
        chatbot,
        account_id: str,
        max_retries: int = 3,
        retry_delay_base: float = 2.0,
        logger: logging.Logger = None
    ):
        """
        Initialize the Zoom adapter.

        Args:
            chatbot: ZoomChatbot instance
            account_id: Zoom account ID
            max_retries: Maximum delivery attempts
            retry_delay_base: Base delay for exponential backoff
            logger: Logger instance
        """
        self._chatbot = chatbot
        self._account_id = account_id
        self._max_retries = max_retries
        self._retry_delay_base = retry_delay_base
        self.logger = logger or logging.getLogger("qa_agent")

    @property
    def channel_type(self) -> ChannelType:
        """Return ZOOM channel type."""
        return ChannelType.ZOOM

    def format(self, message: Message) -> str:
        """
        Format message for Zoom Team Chat.

        Zoom supports a subset of markdown:
        - **bold**, *italic*
        - Bullet lists with -
        - Limited table support

        Args:
            message: Channel-agnostic Message object

        Returns:
            Formatted string for Zoom
        """
        lines = []

        # Add title if present
        if message.title:
            lines.append(f"**{message.title}**")
            lines.append("")

        # Add content
        lines.append(message.content)

        # Add footer for high priority messages
        if message.priority == "urgent":
            lines.append("")
            lines.append("*This message requires immediate attention.*")

        return "\n".join(lines)

    def send(self, formatted: str, destination: str, **kwargs) -> DeliveryResult:
        """
        Send formatted message to Zoom with retry logic.

        Args:
            formatted: Formatted message string
            destination: Zoom JID (channel or user)
            **kwargs: Additional options
                - user_jid: User JID (required by Zoom API)

        Returns:
            DeliveryResult with delivery status
        """
        # Zoom API requires user_jid - use provided one or destination as fallback
        user_jid = kwargs.get("user_jid") or destination

        for attempt in range(self._max_retries):
            try:
                success = self._chatbot.send_message(
                    message=formatted,
                    to_jid=destination,
                    account_id=self._account_id,
                    user_jid=user_jid
                )

                if success:
                    return DeliveryResult(
                        success=True,
                        channel=self.channel_type,
                        retry_count=attempt,
                        delivered_at=datetime.now()
                    )
                else:
                    self.logger.warning(
                        f"Zoom send attempt {attempt + 1}/{self._max_retries} returned False"
                    )

            except Exception as e:
                self.logger.warning(
                    f"Zoom send attempt {attempt + 1}/{self._max_retries} failed: {e}"
                )

                if attempt < self._max_retries - 1:
                    delay = self._retry_delay_base ** attempt
                    time.sleep(delay)

        return DeliveryResult(
            success=False,
            channel=self.channel_type,
            error=f"Failed after {self._max_retries} attempts",
            retry_count=self._max_retries
        )

    def is_available(self) -> bool:
        """Check if Zoom chatbot is configured."""
        return self._chatbot is not None
