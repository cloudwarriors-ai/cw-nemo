"""
Platform connectors for multi-platform meeting support.

This package provides platform-specific implementations for:
- Zoom (native Meeting SDK for <100ms latency)
- Teams/Meet (via MeetingBaas - future)
"""

from .zoom_bot import ZoomMeetingBot

# LiveKit imports are optional - may not be installed
try:
    from .livekit_avatar import LiveKitAvatarAgent
    _LIVEKIT_AVAILABLE = True
except ImportError:
    LiveKitAvatarAgent = None
    _LIVEKIT_AVAILABLE = False

__all__ = [
    "ZoomMeetingBot",
    "LiveKitAvatarAgent",
]
