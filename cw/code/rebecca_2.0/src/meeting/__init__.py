"""
Meeting presence module for Recall.ai integration.

Handles meeting bot management, real-time transcription, and meeting notes.
"""
from .recall_client import RecallClient, BotStatus
from .meeting_handler import MeetingHandler
from .transcription import TranscriptionProcessor

__all__ = [
    "RecallClient",
    "BotStatus",
    "MeetingHandler",
    "TranscriptionProcessor",
]
