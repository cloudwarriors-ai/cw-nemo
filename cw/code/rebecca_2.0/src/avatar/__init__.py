"""
Avatar module for AI QA Lead.

Provides animated avatar capabilities using Simli for
real-time lip-synced video in meetings via Recall.ai.
"""
from .simli_client import SimliClient, SimliSession
from .avatar_session import AvatarSessionManager

__all__ = ["SimliClient", "SimliSession", "AvatarSessionManager"]
