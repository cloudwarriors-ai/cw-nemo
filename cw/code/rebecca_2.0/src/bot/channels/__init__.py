"""
Channel abstraction layer for QA Bot.

Provides a pluggable architecture for message delivery to
multiple channels (Zoom, Slack, Email, etc.).

Usage:
    from .channels import ChannelManager, ChannelType, Message, ZoomChannelAdapter

    # Initialize
    manager = ChannelManager()
    manager.register_adapter(ZoomChannelAdapter(chatbot, account_id))

    # Send message
    message = Message(content="Hello!", title="Test")
    result = manager.send(message, ChannelType.ZOOM, destination="jid@...")
"""

from .base import ChannelAdapter, ChannelType, Message, DeliveryResult
from .manager import ChannelManager
from .zoom_adapter import ZoomChannelAdapter

__all__ = [
    "ChannelAdapter",
    "ChannelType",
    "Message",
    "DeliveryResult",
    "ChannelManager",
    "ZoomChannelAdapter",
]
