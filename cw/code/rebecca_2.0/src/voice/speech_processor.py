"""
Speech processing for voice interactions.

Handles:
- Speech-to-text (ASR) using OpenAI Whisper
- Voice activity detection (VAD)
- Audio preprocessing
"""
import io
import logging
import time
from typing import Optional, Callable
from dataclasses import dataclass

import requests


@dataclass
class TranscriptionResult:
    """Result of speech-to-text processing."""
    text: str
    confidence: float
    language: str
    duration_seconds: float
    processing_time_ms: float


class SpeechProcessor:
    """
    Process speech audio to text using OpenAI Whisper API.

    Whisper is chosen for its accuracy and language support.
    Alternative: Use local Whisper model for lower latency.
    """

    WHISPER_API_URL = "https://api.openai.com/v1/audio/transcriptions"

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
        language: str = "en",
        prompt: str = None,
        logger: logging.Logger = None
    ):
        """
        Initialize speech processor.

        Args:
            api_key: OpenAI API key
            model: Whisper model to use
            language: Default language code (ISO 639-1)
            prompt: Optional prompt to guide transcription
            logger: Logger instance
        """
        self.api_key = api_key
        self.model = model
        self.language = language
        self.prompt = prompt or "QA Bot, GitHub, issues, interns, Cloud Warriors"
        self.logger = logger or logging.getLogger("qa_agent")

    def transcribe(
        self,
        audio_data: bytes,
        audio_format: str = "webm",
        language: str = None
    ) -> TranscriptionResult:
        """
        Transcribe audio to text.

        Args:
            audio_data: Raw audio bytes
            audio_format: Audio format (webm, wav, mp3, etc.)
            language: Override default language

        Returns:
            TranscriptionResult with text and metadata
        """
        start_time = time.time()

        try:
            # Prepare audio file for upload
            audio_file = io.BytesIO(audio_data)
            audio_file.name = f"audio.{audio_format}"

            # Call Whisper API
            response = requests.post(
                self.WHISPER_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}"
                },
                files={
                    "file": (audio_file.name, audio_file, f"audio/{audio_format}")
                },
                data={
                    "model": self.model,
                    "language": language or self.language,
                    "prompt": self.prompt,
                    "response_format": "verbose_json"
                },
                timeout=30
            )

            response.raise_for_status()
            result = response.json()

            processing_time = (time.time() - start_time) * 1000

            return TranscriptionResult(
                text=result.get("text", "").strip(),
                confidence=1.0,  # Whisper doesn't return confidence
                language=result.get("language", self.language),
                duration_seconds=result.get("duration", 0),
                processing_time_ms=processing_time
            )

        except requests.RequestException as e:
            self.logger.error(f"Whisper API error: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Transcription error: {e}")
            raise

    def transcribe_stream(
        self,
        audio_stream,
        chunk_duration_ms: int = 3000,
        on_partial: Callable[[str], None] = None
    ):
        """
        Transcribe streaming audio with partial results.

        This is a simplified implementation. For production,
        consider using a streaming ASR service like Deepgram.

        Args:
            audio_stream: Audio stream (generator of bytes)
            chunk_duration_ms: Process audio in chunks of this size
            on_partial: Callback for partial transcription results

        Yields:
            TranscriptionResult for each chunk
        """
        buffer = bytearray()
        chunk_size = int(16000 * 2 * (chunk_duration_ms / 1000))  # 16kHz, 16-bit

        for audio_chunk in audio_stream:
            buffer.extend(audio_chunk)

            if len(buffer) >= chunk_size:
                # Process accumulated audio
                result = self.transcribe(bytes(buffer), "wav")

                if on_partial and result.text:
                    on_partial(result.text)

                yield result
                buffer.clear()

        # Process remaining audio
        if buffer:
            result = self.transcribe(bytes(buffer), "wav")
            yield result


class SileroVAD:
    """
    ML-based Voice Activity Detection using Silero VAD.

    Silero VAD provides:
    - 95%+ accuracy in noisy environments
    - <1ms processing per 30ms audio chunk on CPU
    - Low false positive rate compared to energy-based detection

    Falls back to energy-based detection if Silero unavailable.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 500,
        logger: logging.Logger = None
    ):
        """
        Initialize Silero VAD.

        Args:
            sample_rate: Audio sample rate (8000 or 16000 supported)
            threshold: Speech probability threshold (0.0-1.0)
            min_speech_duration_ms: Minimum speech duration to trigger
            min_silence_duration_ms: Silence duration to end speech
            logger: Logger instance
        """
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.logger = logger or logging.getLogger("qa_agent")

        self._model = None
        self._utils = None
        self._silero_available = False

        # State tracking
        self.speech_start_time = None
        self.silence_start_time = None
        self.is_speaking = False
        self._last_probability = 0.0

        # Try to load Silero VAD
        self._load_silero()

    def _load_silero(self):
        """Load Silero VAD model if available."""
        try:
            import torch

            # Load Silero VAD from torch hub
            model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=True  # Use ONNX for faster inference
            )

            self._model = model
            self._utils = utils
            self._silero_available = True
            self.logger.info("Silero VAD loaded successfully (ONNX mode)")

        except ImportError:
            self.logger.warning("PyTorch not installed, falling back to energy-based VAD")
        except Exception as e:
            self.logger.warning(f"Silero VAD load failed, falling back to energy-based VAD: {e}")

    def process_frame(self, audio_frame: bytes) -> bool:
        """
        Process audio frame and detect speech.

        Args:
            audio_frame: Raw audio bytes (16-bit PCM)

        Returns:
            True if speech is currently detected
        """
        if self._silero_available:
            return self._process_silero(audio_frame)
        else:
            return self._process_energy(audio_frame)

    def _process_silero(self, audio_frame: bytes) -> bool:
        """Process frame using Silero VAD model."""
        import struct
        import torch
        import numpy as np

        current_time = time.time() * 1000  # ms

        # Convert bytes to float tensor
        samples = struct.unpack(f"<{len(audio_frame)//2}h", audio_frame)
        audio_tensor = torch.tensor(samples, dtype=torch.float32) / 32768.0

        # Get speech probability from model
        try:
            speech_prob = self._model(audio_tensor, self.sample_rate).item()
            self._last_probability = speech_prob
        except Exception as e:
            self.logger.debug(f"Silero inference error: {e}")
            return self._process_energy(audio_frame)

        # State machine for speech detection
        if speech_prob >= self.threshold:
            # Speech detected
            self.silence_start_time = None

            if not self.is_speaking:
                if self.speech_start_time is None:
                    self.speech_start_time = current_time
                elif current_time - self.speech_start_time >= self.min_speech_duration_ms:
                    self.is_speaking = True
                    self.logger.debug(f"Speech started (prob={speech_prob:.2f})")
        else:
            # Silence detected
            self.speech_start_time = None

            if self.is_speaking:
                if self.silence_start_time is None:
                    self.silence_start_time = current_time
                elif current_time - self.silence_start_time >= self.min_silence_duration_ms:
                    self.is_speaking = False
                    self.logger.debug(f"Speech ended (prob={speech_prob:.2f})")

        return self.is_speaking

    def _process_energy(self, audio_frame: bytes) -> bool:
        """Fallback to energy-based detection."""
        import struct

        current_time = time.time() * 1000
        energy_threshold = 0.01

        # Calculate frame energy (RMS)
        samples = struct.unpack(f"<{len(audio_frame)//2}h", audio_frame)
        energy = sum(s**2 for s in samples) / len(samples) if samples else 0
        rms = (energy ** 0.5) / 32768  # Normalize

        if rms > energy_threshold:
            self.silence_start_time = None
            if not self.is_speaking:
                if self.speech_start_time is None:
                    self.speech_start_time = current_time
                elif current_time - self.speech_start_time >= self.min_speech_duration_ms:
                    self.is_speaking = True
        else:
            self.speech_start_time = None
            if self.is_speaking:
                if self.silence_start_time is None:
                    self.silence_start_time = current_time
                elif current_time - self.silence_start_time >= self.min_silence_duration_ms:
                    self.is_speaking = False

        return self.is_speaking

    def get_speech_probability(self) -> float:
        """Get the last computed speech probability (0.0-1.0)."""
        return self._last_probability

    def is_silero_available(self) -> bool:
        """Check if Silero VAD is available."""
        return self._silero_available

    def reset(self):
        """Reset detector state."""
        self.speech_start_time = None
        self.silence_start_time = None
        self.is_speaking = False
        self._last_probability = 0.0

        # Reset Silero model state if available
        if self._silero_available and self._model is not None:
            try:
                self._model.reset_states()
            except Exception:
                pass


class VoiceActivityDetector:
    """
    Detect voice activity in audio stream.

    Uses simple energy-based detection. For production,
    consider using SileroVAD instead for higher accuracy.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        energy_threshold: float = 0.01,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 500
    ):
        """
        Initialize voice activity detector.

        Args:
            sample_rate: Audio sample rate in Hz
            frame_duration_ms: Frame size for analysis
            energy_threshold: Energy threshold for speech detection
            min_speech_duration_ms: Minimum speech duration to trigger
            min_silence_duration_ms: Silence duration to end speech
        """
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.energy_threshold = energy_threshold
        self.min_speech_frames = min_speech_duration_ms // frame_duration_ms
        self.min_silence_frames = min_silence_duration_ms // frame_duration_ms

        self.speech_frames = 0
        self.silence_frames = 0
        self.is_speaking = False

    def process_frame(self, audio_frame: bytes) -> bool:
        """
        Process audio frame and detect speech.

        Args:
            audio_frame: Raw audio bytes (16-bit PCM)

        Returns:
            True if speech is currently detected
        """
        # Calculate frame energy (RMS)
        import struct
        samples = struct.unpack(f"<{len(audio_frame)//2}h", audio_frame)
        energy = sum(s**2 for s in samples) / len(samples)
        rms = (energy ** 0.5) / 32768  # Normalize

        if rms > self.energy_threshold:
            self.speech_frames += 1
            self.silence_frames = 0

            if self.speech_frames >= self.min_speech_frames:
                self.is_speaking = True
        else:
            self.silence_frames += 1

            if self.is_speaking and self.silence_frames >= self.min_silence_frames:
                self.is_speaking = False
                self.speech_frames = 0

        return self.is_speaking

    def reset(self):
        """Reset detector state."""
        self.speech_frames = 0
        self.silence_frames = 0
        self.is_speaking = False


def create_vad(use_silero: bool = True, **kwargs) -> VoiceActivityDetector:
    """
    Factory function to create the best available VAD.

    Args:
        use_silero: If True, try to use Silero VAD (recommended)
        **kwargs: Arguments passed to VAD constructor

    Returns:
        VAD instance (SileroVAD or VoiceActivityDetector)
    """
    if use_silero:
        vad = SileroVAD(**kwargs)
        if vad.is_silero_available():
            return vad

    # Fallback to energy-based VAD
    # VoiceActivityDetector doesn't accept logger, filter it out
    energy_kwargs = {k: v for k, v in kwargs.items() if k != 'logger'}
    return VoiceActivityDetector(**energy_kwargs)
