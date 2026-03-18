"""
Channel abstraction layer base classes.

Defines the interfaces for channel adapters following the Strategy pattern.
Enables modular, pluggable delivery channels (Zoom, Slack, Email, etc.).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Any


class ChannelType(Enum):
    """Supported delivery channels."""
    ZOOM = "zoom"
    SLACK = "slack"
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"


@dataclass
class Message:
    """
    Channel-agnostic message representation.

    This is the unified format that services produce.
    Channel adapters transform this into channel-specific formats.
    """
    content: str
    title: Optional[str] = None
    priority: str = "normal"  # normal, high, urgent
    source_service: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "content": self.content,
            "title": self.title,
            "priority": self.priority,
            "source_service": self.source_service,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class DeliveryResult:
    """Result of message delivery attempt."""
    success: bool
    channel: ChannelType
    message_id: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    delivered_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "channel": self.channel.value,
            "message_id": self.message_id,
            "error": self.error,
            "retry_count": self.retry_count,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
        }


class ChannelAdapter(ABC):
    """
    Base class for channel adapters (Strategy pattern).

    Each adapter handles formatting and delivery for a specific channel.
    Subclasses must implement format(), send(), and is_available().
    """

    @property
    @abstractmethod
    def channel_type(self) -> ChannelType:
        """Return the channel type this adapter handles."""
        pass

    @abstractmethod
    def format(self, message: Message) -> Any:
        """
        Format message for this specific channel.

        Args:
            message: Channel-agnostic Message object

        Returns:
            Channel-specific formatted content (str, dict, etc.)
        """
        pass

    @abstractmethod
    def send(self, formatted: Any, destination: str, **kwargs) -> DeliveryResult:
        """
        Send formatted message to destination.

        Args:
            formatted: Output from format() method
            destination: Channel-specific destination (JID, channel ID, email, etc.)
            **kwargs: Additional channel-specific options

        Returns:
            DeliveryResult with success status and metadata
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this channel is configured and available.

        Returns:
            True if the channel can accept messages
        """
        pass
