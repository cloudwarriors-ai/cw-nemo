"""
Text-to-Speech clients for voice output.

Supports:
- Cartesia (primary - 40ms latency)
- OpenAI TTS (fallback)
"""
import io
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Generator, Callable

import requests


@dataclass
class TTSResult:
    """Result of text-to-speech synthesis."""
    audio_data: bytes
    audio_format: str
    sample_rate: int
    duration_ms: float
    processing_time_ms: float


class TTSClient(ABC):
    """Abstract base class for TTS clients."""

    @abstractmethod
    def synthesize(self, text: str) -> TTSResult:
        """Synthesize text to audio."""
        pass

    @abstractmethod
    def synthesize_stream(
        self,
        text: str,
        on_chunk: Callable[[bytes], None] = None
    ) -> Generator[bytes, None, None]:
        """Synthesize text to streaming audio."""
        pass


class CartesiaTTS(TTSClient):
    """
    Cartesia TTS client for ultra-low latency speech synthesis.

    Features:
    - 40ms time-to-first-audio
    - WebSocket streaming support
    - Multiple voice options
    - Natural sounding output
    """

    API_URL = "https://api.cartesia.ai/tts/bytes"
    STREAM_URL = "wss://api.cartesia.ai/tts/websocket"

    # Recommended voices for professional QA bot
    VOICES = {
        "professional_male": "a0e99841-438c-4a64-b679-ae501e7d6091",  # Marcus
        "professional_female": "248be419-c632-4f23-adf1-5324ed7dbf1d",  # Samantha
        "friendly_male": "63ff761f-c1e8-414b-b969-d1833d1c870c",  # Morgan
        "friendly_female": "71a7ad14-091c-4e8e-a314-022ece01c121",  # Sophie
    }

    def __init__(
        self,
        api_key: str,
        voice_id: str = None,
        model_id: str = "sonic-2",
        sample_rate: int = 44100,  # 44.1kHz CD quality - Zoom compatible
        output_format: str = "mp3",
        logger: logging.Logger = None
    ):
        """
        Initialize Cartesia TTS client.

        Args:
            api_key: Cartesia API key
            voice_id: Voice ID (use VOICES dict for preset options)
            model_id: TTS model (sonic-english, sonic-multilingual)
            sample_rate: Audio sample rate
            output_format: Output format (pcm_s16le, mp3, wav)
            logger: Logger instance
        """
        self.api_key = api_key
        self.voice_id = voice_id or self.VOICES["professional_female"]
        self.model_id = model_id
        self.sample_rate = sample_rate
        self.output_format = output_format
        self.logger = logger or logging.getLogger("qa_agent")

    def synthesize(self, text: str) -> TTSResult:
        """
        Synthesize text to audio.

        Args:
            text: Text to convert to speech

        Returns:
            TTSResult with audio data
        """
        if not text.strip():
            return TTSResult(
                audio_data=b"",
                audio_format=self.output_format,
                sample_rate=self.sample_rate,
                duration_ms=0,
                processing_time_ms=0
            )

        start_time = time.time()

        try:
            # Build output format based on container type
            if self.output_format == "mp3":
                output_fmt = {
                    "container": "mp3",
                    "bit_rate": 128000,
                    "sample_rate": self.sample_rate
                }
            else:
                # PCM/raw format
                output_fmt = {
                    "container": "raw",
                    "encoding": self.output_format,
                    "sample_rate": self.sample_rate
                }

            response = requests.post(
                self.API_URL,
                headers={
                    "Cartesia-Version": "2024-06-10",
                    "X-API-Key": self.api_key,
                    "Content-Type": "application/json"
                },
                json={
                    "model_id": self.model_id,
                    "transcript": text,
                    "voice": {
                        "mode": "id",
                        "id": self.voice_id
                    },
                    "language": "en",  # Required for sonic-2/sonic-3 models
                    "output_format": output_fmt
                },
                timeout=30
            )

            response.raise_for_status()
            audio_data = response.content

            processing_time = (time.time() - start_time) * 1000

            # Estimate duration from audio length
            if self.output_format == "mp3":
                # MP3 at 128kbps: bits = bytes * 8, seconds = bits / bitrate
                duration_ms = (len(audio_data) * 8 / 128000) * 1000
            else:
                # For PCM s16le: 2 bytes per sample
                duration_ms = (len(audio_data) / 2 / self.sample_rate) * 1000

            return TTSResult(
                audio_data=audio_data,
                audio_format=self.output_format,
                sample_rate=self.sample_rate,
                duration_ms=duration_ms,
                processing_time_ms=processing_time
            )

        except requests.RequestException as e:
            self.logger.error(f"Cartesia API error: {e}")
            raise

    def synthesize_stream(
        self,
        text: str,
        on_chunk: Callable[[bytes], None] = None
    ) -> Generator[bytes, None, None]:
        """
        Synthesize text with streaming audio output.

        Uses WebSocket for ultra-low latency streaming.

        Args:
            text: Text to convert to speech
            on_chunk: Callback for each audio chunk

        Yields:
            Audio chunks as bytes
        """
        try:
            import websocket
            import json

            ws = websocket.create_connection(
                f"{self.STREAM_URL}?cartesia_version=2024-06-10&api_key={self.api_key}"
            )

            # Send synthesis request
            import uuid
            request = {
                "model_id": self.model_id,
                "transcript": text,
                "voice": {
                    "mode": "id",
                    "id": self.voice_id
                },
                "language": "en",  # Required for sonic-2/sonic-3 models
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_f32le",  # Streaming requires PCM format
                    "sample_rate": self.sample_rate
                },
                "context_id": str(uuid.uuid4()).replace("-", "")  # Required by Cartesia API
            }
            ws.send(json.dumps(request))

            # Receive audio chunks
            import base64
            while True:
                result = ws.recv()

                if isinstance(result, bytes):
                    # Raw binary audio data
                    if on_chunk:
                        on_chunk(result)
                    yield result
                else:
                    # JSON message - may contain base64-encoded audio
                    data = json.loads(result)
                    if data.get("done"):
                        break
                    if data.get("error"):
                        raise Exception(f"Cartesia error: {data['error']}")
                    # Handle base64-encoded audio chunks
                    if data.get("type") == "chunk" and data.get("data"):
                        audio_bytes = base64.b64decode(data["data"])
                        if on_chunk:
                            on_chunk(audio_bytes)
                        yield audio_bytes

            ws.close()

        except ImportError:
            self.logger.warning(
                "websocket-client not installed, falling back to non-streaming"
            )
            result = self.synthesize(text)
            if on_chunk:
                on_chunk(result.audio_data)
            yield result.audio_data


class OpenAITTS(TTSClient):
    """
    OpenAI TTS client as fallback option.

    Features:
    - High quality voices
    - Simple API
    - Slightly higher latency than Cartesia
    """

    API_URL = "https://api.openai.com/v1/audio/speech"

    VOICES = {
        "alloy": "alloy",      # Neutral
        "echo": "echo",        # Male
        "fable": "fable",      # British
        "onyx": "onyx",        # Deep male
        "nova": "nova",        # Female
        "shimmer": "shimmer",  # Female soft
    }

    def __init__(
        self,
        api_key: str,
        voice: str = "nova",
        model: str = "tts-1",  # or tts-1-hd for higher quality
        speed: float = 1.0,
        logger: logging.Logger = None
    ):
        """
        Initialize OpenAI TTS client.

        Args:
            api_key: OpenAI API key
            voice: Voice name (alloy, echo, fable, onyx, nova, shimmer)
            model: TTS model (tts-1, tts-1-hd)
            speed: Speech speed (0.25 to 4.0)
            logger: Logger instance
        """
        self.api_key = api_key
        self.voice = voice
        self.model = model
        self.speed = speed
        self.logger = logger or logging.getLogger("qa_agent")

    def synthesize(self, text: str) -> TTSResult:
        """
        Synthesize text to audio.

        Args:
            text: Text to convert to speech

        Returns:
            TTSResult with audio data (mp3 format)
        """
        if not text.strip():
            return TTSResult(
                audio_data=b"",
                audio_format="mp3",
                sample_rate=24000,
                duration_ms=0,
                processing_time_ms=0
            )

        start_time = time.time()

        try:
            response = requests.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "input": text,
                    "voice": self.voice,
                    "speed": self.speed,
                    "response_format": "mp3"
                },
                timeout=30
            )

            response.raise_for_status()
            audio_data = response.content

            processing_time = (time.time() - start_time) * 1000

            return TTSResult(
                audio_data=audio_data,
                audio_format="mp3",
                sample_rate=24000,
                duration_ms=0,  # Would need to decode to get actual duration
                processing_time_ms=processing_time
            )

        except requests.RequestException as e:
            self.logger.error(f"OpenAI TTS API error: {e}")
            raise

    def synthesize_stream(
        self,
        text: str,
        on_chunk: Callable[[bytes], None] = None
    ) -> Generator[bytes, None, None]:
        """
        Synthesize with streaming (OpenAI doesn't support true streaming).

        Falls back to non-streaming synthesis.
        """
        result = self.synthesize(text)
        if on_chunk:
            on_chunk(result.audio_data)
        yield result.audio_data
