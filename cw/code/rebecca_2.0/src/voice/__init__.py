"""
Voice and Avatar module for AI QA Lead (Phase 4).

Provides:
- Speech-to-text (ASR) for understanding spoken queries
- Text-to-speech (TTS) for voice responses
- Audio pipeline integration with Recall.ai
"""
from .speech_processor import SpeechProcessor
from .tts_client import TTSClient, CartesiaTTS
from .voice_pipeline import VoicePipeline
