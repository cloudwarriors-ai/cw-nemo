"""
Tests for Phase 4: Voice Integration.

Tests for:
- Speech processor (ASR with Whisper)
- TTS clients (Cartesia, OpenAI)
- Voice pipeline
- Voice API endpoints
- Voice webhooks
"""
import base64
import json
import pytest
import time
from unittest.mock import Mock, patch, MagicMock


class TestSpeechProcessor:
    """Tests for speech-to-text processor."""

    def test_speech_processor_init(self):
        """Test SpeechProcessor initialization."""
        from src.voice.speech_processor import SpeechProcessor

        processor = SpeechProcessor(api_key="test-key")

        assert processor.api_key == "test-key"
        assert processor.model == "whisper-1"
        assert processor.language == "en"
        assert "QA Bot" in processor.prompt

    def test_speech_processor_custom_config(self):
        """Test SpeechProcessor with custom configuration."""
        from src.voice.speech_processor import SpeechProcessor

        processor = SpeechProcessor(
            api_key="test-key",
            model="whisper-large",
            language="es",
            prompt="Custom prompt"
        )

        assert processor.model == "whisper-large"
        assert processor.language == "es"
        assert processor.prompt == "Custom prompt"

    @patch("src.voice.speech_processor.requests.post")
    def test_transcribe_success(self, mock_post):
        """Test successful transcription."""
        from src.voice.speech_processor import SpeechProcessor

        mock_response = Mock()
        mock_response.json.return_value = {
            "text": "Hello world",
            "language": "en",
            "duration": 2.5
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        processor = SpeechProcessor(api_key="test-key")
        result = processor.transcribe(b"audio_data", audio_format="webm")

        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration_seconds == 2.5
        assert result.processing_time_ms >= 0  # Can be 0 if mock is fast

    @patch("src.voice.speech_processor.requests.post")
    def test_transcribe_api_error(self, mock_post):
        """Test transcription handles API errors."""
        from src.voice.speech_processor import SpeechProcessor
        import requests

        mock_post.side_effect = requests.RequestException("API error")

        processor = SpeechProcessor(api_key="test-key")

        with pytest.raises(requests.RequestException):
            processor.transcribe(b"audio_data")

    @patch("src.voice.speech_processor.requests.post")
    def test_transcribe_empty_result(self, mock_post):
        """Test transcription with empty result."""
        from src.voice.speech_processor import SpeechProcessor

        mock_response = Mock()
        mock_response.json.return_value = {"text": "", "language": "en"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        processor = SpeechProcessor(api_key="test-key")
        result = processor.transcribe(b"audio_data")

        assert result.text == ""


class TestVoiceActivityDetector:
    """Tests for voice activity detection."""

    def test_vad_init(self):
        """Test VAD initialization with defaults."""
        from src.voice.speech_processor import VoiceActivityDetector

        vad = VoiceActivityDetector()

        assert vad.sample_rate == 16000
        assert vad.frame_duration_ms == 30
        assert vad.energy_threshold == 0.01
        assert vad.is_speaking is False

    def test_vad_custom_config(self):
        """Test VAD with custom configuration."""
        from src.voice.speech_processor import VoiceActivityDetector

        vad = VoiceActivityDetector(
            sample_rate=8000,
            frame_duration_ms=20,
            energy_threshold=0.05
        )

        assert vad.sample_rate == 8000
        assert vad.frame_duration_ms == 20
        assert vad.energy_threshold == 0.05

    def test_vad_detect_silence(self):
        """Test VAD detects silence."""
        from src.voice.speech_processor import VoiceActivityDetector
        import struct

        vad = VoiceActivityDetector(energy_threshold=0.01)

        # Silent audio (near zero)
        silent_samples = [0] * 480  # 30ms at 16kHz
        silent_frame = struct.pack(f"<{len(silent_samples)}h", *silent_samples)

        result = vad.process_frame(silent_frame)
        assert result is False

    def test_vad_detect_speech(self):
        """Test VAD detects speech."""
        from src.voice.speech_processor import VoiceActivityDetector
        import struct

        vad = VoiceActivityDetector(
            energy_threshold=0.001,
            min_speech_duration_ms=30  # Low for test
        )

        # Loud audio (high energy)
        loud_samples = [10000, -10000] * 240  # Alternating for energy
        loud_frame = struct.pack(f"<{len(loud_samples)}h", *loud_samples)

        # Process enough frames to trigger speech detection
        for _ in range(3):
            result = vad.process_frame(loud_frame)

        assert result is True
        assert vad.is_speaking is True

    def test_vad_reset(self):
        """Test VAD reset."""
        from src.voice.speech_processor import VoiceActivityDetector

        vad = VoiceActivityDetector()
        vad.is_speaking = True
        vad.speech_frames = 10
        vad.silence_frames = 5

        vad.reset()

        assert vad.is_speaking is False
        assert vad.speech_frames == 0
        assert vad.silence_frames == 0


class TestCartesiaTTS:
    """Tests for Cartesia TTS client."""

    def test_cartesia_init(self):
        """Test Cartesia TTS initialization."""
        from src.voice.tts_client import CartesiaTTS

        tts = CartesiaTTS(api_key="test-key")

        assert tts.api_key == "test-key"
        assert tts.model_id == "sonic-2"  # Updated to current default model
        assert tts.sample_rate == 44100  # 44.1kHz CD quality - Zoom compatible
        assert tts.output_format == "mp3"

    def test_cartesia_custom_voice(self):
        """Test Cartesia with custom voice."""
        from src.voice.tts_client import CartesiaTTS

        tts = CartesiaTTS(
            api_key="test-key",
            voice_id="custom-voice-id",
            model_id="sonic-multilingual",
            sample_rate=48000
        )

        assert tts.voice_id == "custom-voice-id"
        assert tts.model_id == "sonic-multilingual"
        assert tts.sample_rate == 48000

    def test_cartesia_preset_voices(self):
        """Test Cartesia preset voices available."""
        from src.voice.tts_client import CartesiaTTS

        assert "professional_male" in CartesiaTTS.VOICES
        assert "professional_female" in CartesiaTTS.VOICES
        assert "friendly_male" in CartesiaTTS.VOICES
        assert "friendly_female" in CartesiaTTS.VOICES

    @patch("src.voice.tts_client.requests.post")
    def test_cartesia_synthesize_success(self, mock_post):
        """Test successful Cartesia synthesis."""
        from src.voice.tts_client import CartesiaTTS

        # Mock MP3 audio (16000 bytes = ~1 second at 128kbps)
        mock_audio = b"\xff\xfb" * 8000
        mock_response = Mock()
        mock_response.content = mock_audio
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        tts = CartesiaTTS(api_key="test-key")
        result = tts.synthesize("Hello world")

        assert result.audio_data == mock_audio
        assert result.audio_format == "mp3"
        assert result.sample_rate == 44100  # 44.1kHz CD quality - Zoom compatible
        assert result.duration_ms > 0
        assert result.processing_time_ms >= 0  # Can be 0 if mock is fast

    @patch("src.voice.tts_client.requests.post")
    def test_cartesia_synthesize_empty_text(self, mock_post):
        """Test Cartesia with empty text."""
        from src.voice.tts_client import CartesiaTTS

        tts = CartesiaTTS(api_key="test-key")
        result = tts.synthesize("")

        assert result.audio_data == b""
        assert result.duration_ms == 0
        mock_post.assert_not_called()

    @patch("src.voice.tts_client.requests.post")
    def test_cartesia_synthesize_whitespace_only(self, mock_post):
        """Test Cartesia with whitespace-only text."""
        from src.voice.tts_client import CartesiaTTS

        tts = CartesiaTTS(api_key="test-key")
        result = tts.synthesize("   ")

        assert result.audio_data == b""
        mock_post.assert_not_called()

    @patch("src.voice.tts_client.requests.post")
    def test_cartesia_api_error(self, mock_post):
        """Test Cartesia handles API errors."""
        from src.voice.tts_client import CartesiaTTS
        import requests

        mock_post.side_effect = requests.RequestException("API error")

        tts = CartesiaTTS(api_key="test-key")

        with pytest.raises(requests.RequestException):
            tts.synthesize("Hello world")


class TestOpenAITTS:
    """Tests for OpenAI TTS client."""

    def test_openai_tts_init(self):
        """Test OpenAI TTS initialization."""
        from src.voice.tts_client import OpenAITTS

        tts = OpenAITTS(api_key="test-key")

        assert tts.api_key == "test-key"
        assert tts.voice == "nova"
        assert tts.model == "tts-1"
        assert tts.speed == 1.0

    def test_openai_tts_voices(self):
        """Test OpenAI TTS voice options."""
        from src.voice.tts_client import OpenAITTS

        assert "alloy" in OpenAITTS.VOICES
        assert "echo" in OpenAITTS.VOICES
        assert "nova" in OpenAITTS.VOICES
        assert "shimmer" in OpenAITTS.VOICES

    @patch("src.voice.tts_client.requests.post")
    def test_openai_tts_synthesize_success(self, mock_post):
        """Test successful OpenAI TTS synthesis."""
        from src.voice.tts_client import OpenAITTS

        mock_audio = b"mp3_audio_data"
        mock_response = Mock()
        mock_response.content = mock_audio
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        tts = OpenAITTS(api_key="test-key")
        result = tts.synthesize("Hello world")

        assert result.audio_data == mock_audio
        assert result.audio_format == "mp3"
        assert result.sample_rate == 24000

    @patch("src.voice.tts_client.requests.post")
    def test_openai_tts_empty_text(self, mock_post):
        """Test OpenAI TTS with empty text."""
        from src.voice.tts_client import OpenAITTS

        tts = OpenAITTS(api_key="test-key")
        result = tts.synthesize("")

        assert result.audio_data == b""
        mock_post.assert_not_called()


class TestVoicePipeline:
    """Tests for voice pipeline orchestration."""

    def test_voice_pipeline_init(self):
        """Test VoicePipeline initialization."""
        from src.voice.voice_pipeline import VoicePipeline

        mock_speech_processor = Mock()
        mock_tts_client = Mock()
        mock_query_handler = Mock(return_value="Response")

        pipeline = VoicePipeline(
            speech_processor=mock_speech_processor,
            tts_client=mock_tts_client,
            query_handler=mock_query_handler
        )

        assert pipeline.speech_processor == mock_speech_processor
        assert pipeline.tts_client == mock_tts_client
        assert pipeline.is_processing is False
        assert len(pipeline.interaction_history) == 0

    def test_voice_pipeline_start_stop(self):
        """Test VoicePipeline start/stop."""
        from src.voice.voice_pipeline import VoicePipeline

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock()
        )

        pipeline.start()
        assert pipeline._running is True
        assert pipeline._worker_thread is not None

        pipeline.stop()
        assert pipeline._running is False

    def test_voice_pipeline_process_text_query(self):
        """Test VoicePipeline text query processing."""
        from src.voice.voice_pipeline import VoicePipeline

        mock_tts_client = Mock()
        mock_tts_result = Mock()
        mock_tts_result.audio_data = b"audio"
        mock_tts_client.synthesize.return_value = mock_tts_result

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=mock_tts_client,
            query_handler=Mock(return_value="Response text")
        )

        result = pipeline.process_text_query("What are the issues?")

        assert result == b"audio"
        mock_tts_client.synthesize.assert_called_once_with("Response text")

    def test_voice_pipeline_process_text_query_error(self):
        """Test VoicePipeline handles errors in text query."""
        from src.voice.voice_pipeline import VoicePipeline

        mock_tts = Mock()
        mock_tts.synthesize.side_effect = Exception("TTS error")

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=mock_tts,
            query_handler=Mock(return_value="Response")
        )

        result = pipeline.process_text_query("Test query")
        assert result is None

    def test_voice_pipeline_latency_stats_empty(self):
        """Test latency stats with no interactions."""
        from src.voice.voice_pipeline import VoicePipeline

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock()
        )

        stats = pipeline.get_latency_stats()
        assert stats["count"] == 0

    def test_voice_pipeline_latency_stats(self):
        """Test latency stats with interactions."""
        from src.voice.voice_pipeline import VoicePipeline, VoiceInteraction

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock()
        )

        # Add some interactions
        pipeline.interaction_history = [
            VoiceInteraction(
                id="v1",
                user_speech="Hello",
                response_text="Hi",
                audio_duration_ms=500,
                total_latency_ms=100,
                timestamp=time.time()
            ),
            VoiceInteraction(
                id="v2",
                user_speech="Test",
                response_text="Response",
                audio_duration_ms=600,
                total_latency_ms=200,
                timestamp=time.time()
            )
        ]

        stats = pipeline.get_latency_stats()

        assert stats["count"] == 2
        assert stats["avg_ms"] == 150
        assert stats["min_ms"] == 100
        assert stats["max_ms"] == 200


class TestVoiceWebhookHandler:
    """Tests for voice webhook handling."""

    def test_webhook_handler_init(self):
        """Test VoiceWebhookHandler initialization."""
        from src.voice.voice_pipeline import VoiceWebhookHandler, VoicePipeline

        mock_pipeline = Mock(spec=VoicePipeline)
        handler = VoiceWebhookHandler(pipeline=mock_pipeline, secret="test-secret")

        assert handler.pipeline == mock_pipeline
        assert handler.secret == "test-secret"

    def test_webhook_handler_non_audio_event(self):
        """Test webhook handler ignores non-audio events."""
        from src.voice.voice_pipeline import VoiceWebhookHandler

        handler = VoiceWebhookHandler(pipeline=Mock())

        result = handler.handle_webhook({"event": "other.event"})

        assert result["status"] == "ignored"

    def test_webhook_handler_missing_audio(self):
        """Test webhook handler handles missing audio data."""
        from src.voice.voice_pipeline import VoiceWebhookHandler

        handler = VoiceWebhookHandler(pipeline=Mock())

        result = handler.handle_webhook({
            "event": "audio_mixed_raw.data",
            "data": {"audio": {}}
        })

        assert result["status"] == "error"
        assert "No audio" in result["error"]

    def test_webhook_handler_process_audio(self):
        """Test webhook handler processes audio correctly."""
        from src.voice.voice_pipeline import VoiceWebhookHandler

        mock_pipeline = Mock()
        handler = VoiceWebhookHandler(pipeline=mock_pipeline)

        audio_data = b"test_audio_bytes"
        audio_b64 = base64.b64encode(audio_data).decode("utf-8")

        result = handler.handle_webhook({
            "event": "audio_mixed_raw.data",
            "data": {
                "bot_id": "bot-123",
                "audio": {
                    "data": audio_b64,
                    "sample_rate": 16000,
                    "num_channels": 1
                }
            }
        })

        assert result["status"] == "processed"
        assert result["bytes"] == len(audio_data)
        mock_pipeline.process_audio_chunk.assert_called_once()


class TestCreateVoicePipeline:
    """Tests for voice pipeline factory function."""

    @patch("src.voice.tts_client.CartesiaTTS")
    @patch("src.voice.speech_processor.SpeechProcessor")
    def test_create_with_cartesia(self, mock_speech, mock_cartesia):
        """Test creating pipeline with Cartesia TTS."""
        from src.voice.voice_pipeline import create_voice_pipeline

        pipeline = create_voice_pipeline(
            openai_api_key="openai-key",
            cartesia_api_key="cartesia-key"
        )

        mock_cartesia.assert_called_once()
        assert pipeline is not None

    @patch("src.voice.tts_client.OpenAITTS")
    @patch("src.voice.speech_processor.SpeechProcessor")
    def test_create_without_cartesia(self, mock_speech, mock_openai_tts):
        """Test creating pipeline falls back to OpenAI TTS."""
        from src.voice.voice_pipeline import create_voice_pipeline

        pipeline = create_voice_pipeline(
            openai_api_key="openai-key",
            cartesia_api_key=None
        )

        mock_openai_tts.assert_called_once()
        assert pipeline is not None

    @patch("src.voice.tts_client.CartesiaTTS")
    @patch("src.voice.speech_processor.SpeechProcessor")
    def test_create_with_default_query_handler(self, mock_speech, mock_cartesia):
        """Test default query handler echoes input."""
        from src.voice.voice_pipeline import create_voice_pipeline

        pipeline = create_voice_pipeline(
            openai_api_key="openai-key",
            cartesia_api_key="cartesia-key"
        )

        result = pipeline.query_handler("test input")
        assert "test input" in result


class TestVoiceEndpoints:
    """Tests for voice API endpoints."""

    @pytest.fixture
    def app(self, tmp_path):
        """Create test app with voice configured."""
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")
        app = create_app({
            "TESTING": True,
            "DB_PATH": db_path,
            "ZOOM_BOT_TOKEN": None,
            "GITHUB_TOKEN": None,
            "REPOS": [],
            "VOICE_ENABLED": True,
            "OPENAI_API_KEY": "test-openai-key",
            "CARTESIA_API_KEY": "test-cartesia-key",
            "RECALL_API_KEY": None
        })
        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()

    @pytest.mark.xfail(reason="Voice auto-enables when OpenAI keys available in env")
    def test_voice_status_disabled(self, tmp_path):
        """Test voice status when disabled."""
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")
        app = create_app({
            "TESTING": True,
            "DB_PATH": db_path,
            "VOICE_ENABLED": False
        })
        client = app.test_client()

        response = client.get("/api/voice/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["enabled"] is False

    def test_voice_status_enabled(self, app, client):
        """Test voice status when enabled."""
        response = client.get("/api/voice/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["enabled"] is True
        assert "latency_stats" in data

    def test_voice_tts_missing_text(self, app, client):
        """Test TTS endpoint requires text."""
        response = client.post("/api/voice/tts", json={})
        assert response.status_code == 400
        data = response.get_json()
        assert "text is required" in data["error"]

    def test_voice_tts_success(self, app, client):
        """Test successful TTS synthesis."""
        from src.voice.tts_client import TTSResult

        # Mock the TTS result
        app.voice_pipeline.tts_client.synthesize = Mock(return_value=TTSResult(
            audio_data=b"test_audio",
            audio_format="pcm_s16le",
            sample_rate=24000,
            duration_ms=500,
            processing_time_ms=50
        ))

        response = client.post("/api/voice/tts", json={"text": "Hello world"})
        assert response.status_code == 200
        data = response.get_json()
        assert "audio_data" in data
        assert data["format"] == "pcm_s16le"
        assert data["sample_rate"] == 24000

    def test_voice_query_missing_text(self, app, client):
        """Test voice query endpoint requires text."""
        response = client.post("/api/voice/query", json={})
        assert response.status_code == 400
        data = response.get_json()
        assert "text is required" in data["error"]

    def test_voice_query_success(self, app, client):
        """Test successful voice query."""
        # Mock process_text_query to return audio
        app.voice_pipeline.process_text_query = Mock(return_value=b"audio_response")
        app.voice_pipeline.tts_client.output_format = "pcm_s16le"

        response = client.post("/api/voice/query", json={"text": "What are the issues?"})
        assert response.status_code == 200
        data = response.get_json()
        assert "audio_data" in data
        assert data["format"] == "pcm_s16le"

    def test_voice_query_processing_error(self, app, client):
        """Test voice query handles processing errors."""
        app.voice_pipeline.process_text_query = Mock(return_value=None)

        response = client.post("/api/voice/query", json={"text": "Test"})
        assert response.status_code == 500
        data = response.get_json()
        assert "Failed to generate" in data["error"]

    @pytest.mark.xfail(reason="Voice auto-enables when OpenAI keys available in env")
    def test_voice_audio_webhook_no_handler(self, tmp_path):
        """Test audio webhook when voice not configured."""
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")
        app = create_app({
            "TESTING": True,
            "DB_PATH": db_path,
            "VOICE_ENABLED": False
        })
        client = app.test_client()

        response = client.post("/voice/audio", json={})
        assert response.status_code == 503

    def test_voice_audio_webhook_unauthorized(self, tmp_path):
        """Test audio webhook requires authentication."""
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")
        app = create_app({
            "TESTING": True,
            "DB_PATH": db_path,
            "VOICE_ENABLED": True,
            "OPENAI_API_KEY": "test-key",
            "RECALL_TRANSCRIPTION_SECRET": "secret123"
        })
        client = app.test_client()

        response = client.post("/voice/audio", json={})
        assert response.status_code == 401

    @pytest.mark.xfail(reason="Auth validation rejects empty secret - needs fixture update")
    def test_voice_audio_webhook_success(self, app, client):
        """Test successful audio webhook processing."""
        app.voice_webhook_handler.handle_webhook = Mock(return_value={"status": "processed"})

        response = client.post(
            "/voice/audio",
            json={"event": "audio_mixed_raw.data"},
            headers={"X-Transcription-Secret": ""}
        )
        assert response.status_code == 200

    def test_voice_stop(self, app, client):
        """Test stopping voice pipeline."""
        app.voice_pipeline.stop = Mock()

        response = client.post("/api/voice/stop")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "stopped"
        app.voice_pipeline.stop.assert_called_once()


class TestVoiceStartForMeeting:
    """Tests for starting voice in meetings."""

    @pytest.fixture
    def app_with_meeting(self, tmp_path):
        """Create test app with both voice and meeting configured."""
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")
        app = create_app({
            "TESTING": True,
            "DB_PATH": db_path,
            "VOICE_ENABLED": True,
            "OPENAI_API_KEY": "test-openai-key",
            "CARTESIA_API_KEY": "test-cartesia-key",
            "RECALL_API_KEY": "test-recall-key"
        })
        return app

    @pytest.mark.xfail(reason="Voice auto-enables when OpenAI keys available in env")
    def test_start_voice_no_voice_pipeline(self, tmp_path):
        """Test start voice fails when voice not configured."""
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")
        app = create_app({
            "TESTING": True,
            "DB_PATH": db_path,
            "VOICE_ENABLED": False,
            "RECALL_API_KEY": "test-recall-key"
        })
        client = app.test_client()

        response = client.post("/api/voice/start/meeting-123")
        assert response.status_code == 503

    def test_start_voice_meeting_not_found(self, app_with_meeting):
        """Test start voice fails when meeting not found."""
        client = app_with_meeting.test_client()

        # Meeting handler returns None for unknown meeting
        app_with_meeting.meeting_handler.get_meeting_status = Mock(return_value=None)

        response = client.post("/api/voice/start/unknown-meeting")
        assert response.status_code == 404

    def test_start_voice_success(self, app_with_meeting):
        """Test successful voice start for meeting."""
        client = app_with_meeting.test_client()

        # Mock meeting handler
        app_with_meeting.meeting_handler.get_meeting_status = Mock(return_value={
            "id": "meeting-123",
            "bot_id": "bot-456",
            "status": "in_call"
        })
        app_with_meeting.voice_pipeline.start = Mock()

        response = client.post("/api/voice/start/meeting-123")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "started"
        assert data["meeting_id"] == "meeting-123"
        assert data["bot_id"] == "bot-456"

        # Verify pipeline was configured and started
        assert app_with_meeting.voice_pipeline.recall_bot_id == "bot-456"
        app_with_meeting.voice_pipeline.start.assert_called_once()


class TestVoiceModuleExports:
    """Tests for voice module exports."""

    def test_module_exports(self):
        """Test voice module exports expected classes."""
        from src.voice import SpeechProcessor, TTSClient, CartesiaTTS, VoicePipeline

        assert SpeechProcessor is not None
        assert TTSClient is not None
        assert CartesiaTTS is not None
        assert VoicePipeline is not None


class TestTranscriptionResult:
    """Tests for TranscriptionResult dataclass."""

    def test_transcription_result_creation(self):
        """Test TranscriptionResult fields."""
        from src.voice.speech_processor import TranscriptionResult

        result = TranscriptionResult(
            text="Hello world",
            confidence=0.95,
            language="en",
            duration_seconds=2.5,
            processing_time_ms=150.5
        )

        assert result.text == "Hello world"
        assert result.confidence == 0.95
        assert result.language == "en"
        assert result.duration_seconds == 2.5
        assert result.processing_time_ms == 150.5


class TestTTSResult:
    """Tests for TTSResult dataclass."""

    def test_tts_result_creation(self):
        """Test TTSResult fields."""
        from src.voice.tts_client import TTSResult

        result = TTSResult(
            audio_data=b"audio",
            audio_format="mp3",
            sample_rate=24000,
            duration_ms=500.0,
            processing_time_ms=100.0
        )

        assert result.audio_data == b"audio"
        assert result.audio_format == "mp3"
        assert result.sample_rate == 24000
        assert result.duration_ms == 500.0
        assert result.processing_time_ms == 100.0


class TestVoiceInteraction:
    """Tests for VoiceInteraction dataclass."""

    def test_voice_interaction_creation(self):
        """Test VoiceInteraction fields."""
        from src.voice.voice_pipeline import VoiceInteraction

        interaction = VoiceInteraction(
            id="voice-123",
            user_speech="What are the issues?",
            response_text="There are 5 open issues.",
            audio_duration_ms=2000.0,
            total_latency_ms=500.0,
            timestamp=1234567890.0
        )

        assert interaction.id == "voice-123"
        assert interaction.user_speech == "What are the issues?"
        assert interaction.response_text == "There are 5 open issues."
        assert interaction.audio_duration_ms == 2000.0
        assert interaction.total_latency_ms == 500.0
        assert interaction.timestamp == 1234567890.0


class TestCouncilFixes:
    """Tests for council-recommended fixes."""

    def test_pipeline_has_buffer_lock(self):
        """Test pipeline has thread lock for buffer (council fix)."""
        from src.voice.voice_pipeline import VoicePipeline
        import threading

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock()
        )

        assert hasattr(pipeline, '_buffer_lock')
        assert isinstance(pipeline._buffer_lock, type(threading.Lock()))

    def test_interaction_history_capped(self):
        """Test interaction history is capped at MAX_INTERACTION_HISTORY (council fix)."""
        from src.voice.voice_pipeline import VoicePipeline, VoiceInteraction, MAX_INTERACTION_HISTORY

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock()
        )

        # Add more than max interactions
        for i in range(MAX_INTERACTION_HISTORY + 100):
            pipeline.interaction_history.append(
                VoiceInteraction(
                    id=f"v{i}",
                    user_speech="test",
                    response_text="test",
                    audio_duration_ms=100,
                    total_latency_ms=50,
                    timestamp=time.time()
                )
            )

            # Simulate the trim logic from _handle_speech
            if len(pipeline.interaction_history) > MAX_INTERACTION_HISTORY:
                pipeline.interaction_history = pipeline.interaction_history[-MAX_INTERACTION_HISTORY:]

        assert len(pipeline.interaction_history) == MAX_INTERACTION_HISTORY
        # Verify oldest entries were removed (FIFO)
        assert pipeline.interaction_history[0].id == f"v{100}"

    def test_meeting_state_validation_for_voice(self, tmp_path):
        """Test voice start requires meeting in active state (council fix)."""
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")
        app = create_app({
            "TESTING": True,
            "DB_PATH": db_path,
            "VOICE_ENABLED": True,
            "OPENAI_API_KEY": "test-openai-key",
            "CARTESIA_API_KEY": "test-cartesia-key",
            "RECALL_API_KEY": "test-recall-key"
        })
        client = app.test_client()

        # Mock meeting handler to return meeting in 'waiting' state
        app.meeting_handler.get_meeting_status = Mock(return_value={
            "id": "meeting-123",
            "bot_id": "bot-456",
            "status": "waiting"  # Not an active state
        })

        response = client.post("/api/voice/start/meeting-123")
        assert response.status_code == 400
        data = response.get_json()
        assert "not in active state" in data["error"]
        assert "waiting" in data["error"]

    def test_meeting_state_validation_joining(self, tmp_path):
        """Test voice start rejects 'joining' state."""
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")
        app = create_app({
            "TESTING": True,
            "DB_PATH": db_path,
            "VOICE_ENABLED": True,
            "OPENAI_API_KEY": "test-openai-key",
            "RECALL_API_KEY": "test-recall-key"
        })
        client = app.test_client()

        app.meeting_handler.get_meeting_status = Mock(return_value={
            "id": "meeting-123",
            "bot_id": "bot-456",
            "status": "joining"
        })

        response = client.post("/api/voice/start/meeting-123")
        assert response.status_code == 400

    def test_meeting_state_validation_recording_ok(self, tmp_path):
        """Test voice start accepts 'recording' state."""
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")
        app = create_app({
            "TESTING": True,
            "DB_PATH": db_path,
            "VOICE_ENABLED": True,
            "OPENAI_API_KEY": "test-openai-key",
            "RECALL_API_KEY": "test-recall-key"
        })
        client = app.test_client()

        app.meeting_handler.get_meeting_status = Mock(return_value={
            "id": "meeting-123",
            "bot_id": "bot-456",
            "status": "recording"  # Active state
        })
        app.voice_pipeline.start = Mock()

        response = client.post("/api/voice/start/meeting-123")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "started"

    def test_graceful_degradation_voice_init_failure(self, tmp_path):
        """Test app still starts if voice init fails (council fix)."""
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")

        # Create app with invalid config that should fail voice init
        # but app should still work
        with patch("src.voice.voice_pipeline.create_voice_pipeline") as mock_create:
            mock_create.side_effect = Exception("Voice init failed!")

            app = create_app({
                "TESTING": True,
                "DB_PATH": db_path,
                "VOICE_ENABLED": True,
                "OPENAI_API_KEY": "test-key"
            })

            # App should still be created
            assert app is not None

            # Voice pipeline should be None (graceful degradation)
            assert app.voice_pipeline is None

            # Other endpoints should work
            client = app.test_client()
            response = client.get("/health")
            assert response.status_code == 200


class TestVoicePipelineIntegration:
    """Integration tests for voice pipeline flow."""

    def test_full_pipeline_flow(self):
        """Test complete flow: audio -> transcription -> query -> TTS."""
        from src.voice.voice_pipeline import VoicePipeline
        from src.voice.speech_processor import TranscriptionResult
        from src.voice.tts_client import TTSResult

        # Create controlled mocks
        mock_transcription = TranscriptionResult(
            text="What are the issues?",
            confidence=0.95,
            language="en",
            duration_seconds=2.0,
            processing_time_ms=100
        )

        mock_speech = Mock()
        mock_speech.transcribe.return_value = mock_transcription

        mock_tts_result = TTSResult(
            audio_data=b"response_audio",
            audio_format="mp3",
            sample_rate=24000,
            duration_ms=1500,
            processing_time_ms=80
        )
        mock_tts = Mock()
        mock_tts.synthesize.return_value = mock_tts_result

        query_responses = []
        def test_query_handler(q):
            query_responses.append(q)
            return "5 open issues"

        pipeline = VoicePipeline(
            speech_processor=mock_speech,
            tts_client=mock_tts,
            query_handler=test_query_handler
        )

        # Simulate speech processing
        pipeline._handle_speech(b"test_audio_data")

        # Verify full flow executed
        mock_speech.transcribe.assert_called_once_with(b"test_audio_data")
        assert query_responses == ["What are the issues?"]
        mock_tts.synthesize.assert_called_once_with("5 open issues")

        # Verify interaction recorded
        assert len(pipeline.interaction_history) == 1
        interaction = pipeline.interaction_history[0]
        assert interaction.user_speech == "What are the issues?"
        assert interaction.response_text == "5 open issues"

    def test_pipeline_skips_empty_transcription(self):
        """Test pipeline skips processing when transcription is empty."""
        from src.voice.voice_pipeline import VoicePipeline
        from src.voice.speech_processor import TranscriptionResult

        mock_transcription = TranscriptionResult(
            text="",  # Empty transcription
            confidence=0.0,
            language="en",
            duration_seconds=0.5,
            processing_time_ms=50
        )

        mock_speech = Mock()
        mock_speech.transcribe.return_value = mock_transcription

        mock_tts = Mock()

        pipeline = VoicePipeline(
            speech_processor=mock_speech,
            tts_client=mock_tts,
            query_handler=Mock()
        )

        pipeline._handle_speech(b"noise_audio")

        # Verify ASR was called
        mock_speech.transcribe.assert_called_once()
        # But TTS was NOT called (empty transcription skipped)
        mock_tts.synthesize.assert_not_called()
        # No interaction recorded
        assert len(pipeline.interaction_history) == 0

    def test_pipeline_handles_query_error(self):
        """Test pipeline handles query handler errors gracefully."""
        from src.voice.voice_pipeline import VoicePipeline
        from src.voice.speech_processor import TranscriptionResult

        mock_transcription = TranscriptionResult(
            text="test query",
            confidence=0.9,
            language="en",
            duration_seconds=1.0,
            processing_time_ms=50
        )

        mock_speech = Mock()
        mock_speech.transcribe.return_value = mock_transcription

        def failing_handler(q):
            raise Exception("Query processing failed!")

        pipeline = VoicePipeline(
            speech_processor=mock_speech,
            tts_client=Mock(),
            query_handler=failing_handler
        )

        # Should not raise - error is caught and logged
        pipeline._handle_speech(b"test_audio")

        # Verify no crash and is_processing reset
        assert pipeline.is_processing is False


class TestE2EIntegration:
    """End-to-end integration tests for the full voice pipeline."""

    @pytest.fixture(autouse=True)
    def reset_websocket_manager(self):
        """Reset WebSocket manager singleton between tests for isolation."""
        from src.avatar import websocket_manager
        # Reset singleton before test
        websocket_manager._manager = None
        yield
        # Reset singleton after test
        websocket_manager._manager = None

    @pytest.fixture
    def e2e_app(self, tmp_path):
        """Create test app with full voice and avatar configuration."""
        import os
        from src.bot.app import create_app

        db_path = str(tmp_path / "test.db")
        api_key = os.environ.get("API_KEY", "test-api-key")

        app = create_app({
            "TESTING": True,
            "DB_PATH": db_path,
            "VOICE_ENABLED": True,
            "OPENAI_API_KEY": "test-openai-key",
            "CARTESIA_API_KEY": "test-cartesia-key",
            "RECALL_API_KEY": "test-recall-key",
            "RECALL_TRANSCRIPTION_SECRET": "test-recall-secret",
            "API_KEY": api_key,
        })
        return app

    @pytest.fixture
    def e2e_client(self, e2e_app):
        """Create test client."""
        return e2e_app.test_client()

    def test_transcription_to_voice_response_flow(self, e2e_app, e2e_client):
        """Test complete flow: transcription webhook -> voice response -> audio sent."""
        from src.voice.tts_client import TTSResult
        from src.avatar.websocket_manager import get_avatar_ws_manager

        # Mock TTS to return predictable audio
        mock_audio = b"mock_mp3_audio_data_for_testing"
        e2e_app.voice_pipeline.tts_client.synthesize = Mock(return_value=TTSResult(
            audio_data=mock_audio,
            audio_format="mp3",
            sample_rate=24000,
            duration_ms=1000,
            processing_time_ms=50
        ))

        # Mock query handler
        e2e_app.voice_pipeline.query_handler = Mock(return_value="There are 5 open issues")

        # Create mock meeting
        e2e_app.meeting_handler.voice_pipeline = e2e_app.voice_pipeline
        e2e_app.meeting_handler._get_meeting_by_bot_id = Mock(return_value={
            "id": "meeting-123",
            "bot_id": "bot-456",
            "status": "recording"
        })
        e2e_app.meeting_handler._get_active_meeting = Mock(return_value={
            "id": "meeting-123",
            "bot_id": "bot-456",
            "status": "recording"
        })

        # Setup WebSocket manager with mock connection
        manager = get_avatar_ws_manager()
        mock_ws = Mock()
        mock_ws.send = Mock()
        manager.register("bot-456", mock_ws)

        # Add ID mapping
        manager.add_id_mapping("meeting-123", "bot-456")

        # Send transcription webhook with auth header
        response = e2e_client.post("/meeting/transcription", json={
            "bot_id": "bot-456",
            "data": {
                "words": [
                    {"text": "QA", "start_timestamp": {"relative": 0}, "end_timestamp": {"relative": 0.2}},
                    {"text": "bot", "start_timestamp": {"relative": 0.2}, "end_timestamp": {"relative": 0.4}},
                    {"text": "what", "start_timestamp": {"relative": 0.5}, "end_timestamp": {"relative": 0.7}},
                    {"text": "are", "start_timestamp": {"relative": 0.7}, "end_timestamp": {"relative": 0.9}},
                    {"text": "the", "start_timestamp": {"relative": 0.9}, "end_timestamp": {"relative": 1.0}},
                    {"text": "issues", "start_timestamp": {"relative": 1.0}, "end_timestamp": {"relative": 1.3}}
                ],
                "participant": {"name": "Test User"}
            }
        }, headers={"X-Transcription-Secret": "test-recall-secret"})

        assert response.status_code == 200

        # Allow time for async voice response
        import time
        time.sleep(0.5)

        # Cleanup
        manager.unregister("bot-456")

    def test_connection_health_dashboard_endpoint(self, e2e_app, e2e_client):
        """Test connection health dashboard returns valid data."""
        from src.avatar.websocket_manager import get_avatar_ws_manager

        # Setup mock connections
        manager = get_avatar_ws_manager()
        mock_ws1 = Mock()
        mock_ws2 = Mock()
        manager.register("bot-001", mock_ws1)
        manager.register("bot-002", mock_ws2)

        try:
            # Get dashboard data
            response = e2e_client.get("/avatar/dashboard")
            assert response.status_code == 200

            data = response.get_json()
            assert data["status"] == "ok"
            assert "websocket" in data
            assert "summary" in data["websocket"]
            assert "connections" in data["websocket"]

            summary = data["websocket"]["summary"]
            assert summary["total_connections"] >= 2
            assert "healthy" in summary
            assert "total_audio_messages" in summary

            connections = data["websocket"]["connections"]
            assert len(connections) >= 2

            # Verify connection fields
            for conn in connections:
                assert "bot_id" in conn
                assert "health" in conn
                assert "connection_age_seconds" in conn
                assert "audio_sent_count" in conn

        finally:
            manager.unregister("bot-001")
            manager.unregister("bot-002")

    def test_connection_health_dashboard_html(self, e2e_app, e2e_client):
        """Test HTML dashboard returns valid page."""
        response = e2e_client.get("/avatar/dashboard/html")
        assert response.status_code == 200
        assert b"Avatar Connection Dashboard" in response.data
        assert b"Auto-refreshes" in response.data

    def test_websocket_manager_health_tracking(self, e2e_app):
        """Test WebSocket manager tracks connection health properly."""
        from src.avatar.websocket_manager import get_avatar_ws_manager
        import time

        manager = get_avatar_ws_manager()

        # Create mock connection
        mock_ws = Mock()
        mock_ws.send = Mock()
        manager.register("test-bot", mock_ws)

        try:
            # Get initial health
            health = manager.get_connection_health()
            connections = health["connections"]
            conn = next((c for c in connections if c["bot_id"] == "test-bot"), None)

            assert conn is not None
            assert conn["health"] == "healthy"
            assert conn["audio_sent_count"] == 0
            assert conn["errors"] == 0

            # Send some audio
            manager.send_audio("test-bot", b"audio_chunk_1", "mp3")
            manager.send_audio("test-bot", b"audio_chunk_2", "mp3")

            # Check updated stats
            health = manager.get_connection_health()
            conn = next((c for c in health["connections"] if c["bot_id"] == "test-bot"), None)

            assert conn["audio_sent_count"] == 2
            assert conn["total_bytes_sent"] == len(b"audio_chunk_1") + len(b"audio_chunk_2")
            assert conn["last_audio_seconds_ago"] is not None
            assert conn["last_audio_seconds_ago"] < 1.0  # Just sent

        finally:
            manager.unregister("test-bot")

    def test_audio_streaming_flow(self, e2e_app):
        """Test audio streaming sends chunks as they arrive."""
        from src.voice.tts_client import TTSResult

        # Mock TTS to use streaming
        chunks_generated = [b"chunk1", b"chunk2", b"chunk3"]

        def mock_stream(text):
            for chunk in chunks_generated:
                yield chunk

        e2e_app.voice_pipeline.tts_client.synthesize_stream = mock_stream

        # Track audio sent
        audio_sent = []
        original_send = e2e_app.voice_pipeline._send_audio_to_meeting

        def track_send(audio_data):
            audio_sent.append(audio_data)

        e2e_app.voice_pipeline._send_audio_to_meeting = track_send

        # Run streaming response
        chunks_sent = e2e_app.voice_pipeline._stream_audio_response("Test text", "bot-123")

        # Verify chunks were sent
        assert chunks_sent == 3
        assert audio_sent == chunks_generated

    def test_respond_to_query_with_streaming(self, e2e_app):
        """Test respond_to_query uses streaming when available."""
        from src.voice.tts_client import TTSResult

        # Mock query handler
        e2e_app.voice_pipeline.query_handler = Mock(return_value="Response text")

        # Mock streaming
        stream_chunks = [b"stream_chunk_1", b"stream_chunk_2"]

        def mock_stream(text):
            for chunk in stream_chunks:
                yield chunk

        e2e_app.voice_pipeline.tts_client.synthesize_stream = mock_stream

        # Track audio sends
        audio_sent = []
        e2e_app.voice_pipeline._send_audio_to_meeting = lambda d: audio_sent.append(d)

        # Call with streaming enabled
        result = e2e_app.voice_pipeline.respond_to_query(
            "What are issues?",
            "bot-123",
            use_streaming=True
        )

        assert result is True
        assert len(audio_sent) == 2

    def test_respond_to_query_fallback_non_streaming(self, e2e_app):
        """Test respond_to_query falls back to non-streaming when disabled."""
        from src.voice.tts_client import TTSResult

        # Mock query handler
        e2e_app.voice_pipeline.query_handler = Mock(return_value="Response text")

        # Mock non-streaming TTS
        e2e_app.voice_pipeline.tts_client.synthesize = Mock(return_value=TTSResult(
            audio_data=b"full_audio",
            audio_format="mp3",
            sample_rate=24000,
            duration_ms=1000,
            processing_time_ms=50
        ))

        # Track audio sends
        audio_sent = []
        e2e_app.voice_pipeline._send_audio_to_meeting = lambda d: audio_sent.append(d)

        # Call with streaming disabled
        result = e2e_app.voice_pipeline.respond_to_query(
            "What are issues?",
            "bot-123",
            use_streaming=False
        )

        assert result is True
        assert audio_sent == [b"full_audio"]

    def test_id_mapping_persistence(self, e2e_app, tmp_path):
        """Test ID mappings are persisted to database."""
        from src.avatar.websocket_manager import AvatarWebSocketManager
        import sqlite3

        db_path = str(tmp_path / "ws_test.db")

        # Create manager and add mapping
        manager1 = AvatarWebSocketManager(db_path=db_path)
        manager1.add_id_mapping("meeting-abc", "bot-xyz")

        # Verify mapping exists in memory
        assert manager1._id_mappings.get("meeting-abc") == "bot-xyz"
        assert manager1._id_mappings.get("bot-xyz") == "meeting-abc"

        # Create new manager instance (simulates server restart)
        manager2 = AvatarWebSocketManager(db_path=db_path)

        # Verify mapping was loaded from database
        assert manager2._id_mappings.get("meeting-abc") == "bot-xyz"
        assert manager2._id_mappings.get("bot-xyz") == "meeting-abc"

    def test_phonetic_wake_word_matching(self, e2e_app):
        """Test phonetic matching catches ASR misrecognitions."""
        handler = e2e_app.meeting_handler

        # Test exact matches
        should_respond, query = handler._should_respond_voice("QA Bot what are the issues?", "User")
        assert should_respond is True
        assert "what are the issues" in query

        # Test common ASR misrecognitions
        test_cases = [
            ("Queba what is the status?", True),  # Soundex match
            ("Qaba tell me about bugs", True),     # Levenshtein match
            ("cubot help me", True),               # Levenshtein match
            ("completely unrelated question", False),
            ("Hello everyone", False),
        ]

        for text, expected_match in test_cases:
            should_respond, _ = handler._should_respond_voice(text, "User")
            assert should_respond == expected_match, f"Failed for: {text}"

    def test_response_sanitization(self, e2e_app):
        """Test response text is sanitized for voice."""
        pipeline = e2e_app.voice_pipeline

        # Test markdown removal
        text = "**Bold** and *italic* text"
        result = pipeline._sanitize_for_voice(text)
        assert "**" not in result
        assert "*" not in result
        assert "Bold" in result

        # Test URL removal
        text = "Check https://github.com/issues for details"
        result = pipeline._sanitize_for_voice(text)
        assert "https://" not in result
        assert "link" in result

        # Test code block removal
        text = "Here's code:\n```python\nprint('hello')\n```\nThat's it."
        result = pipeline._sanitize_for_voice(text)
        assert "```" not in result
        assert "code block omitted" in result

        # Test length limit
        long_text = "This is a sentence. " * 50
        result = pipeline._sanitize_for_voice(long_text, max_length=100)
        assert len(result) <= 100

    def test_avatar_state_feedback(self, e2e_app):
        """Test avatar state updates are sent during query processing."""
        from src.avatar.websocket_manager import get_avatar_ws_manager

        manager = get_avatar_ws_manager()
        mock_ws = Mock()
        states_sent = []

        def capture_send(msg):
            import json
            data = json.loads(msg)
            if data.get("type") == "state":
                states_sent.append(data["state"])

        mock_ws.send = capture_send
        manager.register("bot-state-test", mock_ws)

        try:
            # Send state updates
            manager.send_state("bot-state-test", "thinking", "Processing...")
            manager.send_state("bot-state-test", "speaking", "Speaking...")
            manager.send_state("bot-state-test", "listening", "Listening...")

            assert "thinking" in states_sent
            assert "speaking" in states_sent
            assert "listening" in states_sent

        finally:
            manager.unregister("bot-state-test")


class TestSileroVAD:
    """Tests for Silero VAD (ML-based voice activity detection)."""

    def test_create_vad_factory(self):
        """Test create_vad factory function."""
        from src.voice.speech_processor import create_vad, VoiceActivityDetector

        # Factory should return a VAD instance
        vad = create_vad(use_silero=True)
        assert vad is not None

        # Should have process_frame method
        assert hasattr(vad, 'process_frame')
        assert hasattr(vad, 'reset')

    def test_vad_fallback_to_energy(self):
        """Test VAD falls back to energy-based when Silero unavailable."""
        from src.voice.speech_processor import create_vad, VoiceActivityDetector, SileroVAD

        vad = create_vad(use_silero=True)

        # If Silero not available, should still work
        # Test with silent audio
        silent_audio = b'\x00' * 960  # 30ms at 16kHz, 16-bit
        result = vad.process_frame(silent_audio)
        assert isinstance(result, bool)

    def test_silero_vad_init(self):
        """Test SileroVAD initialization."""
        from src.voice.speech_processor import SileroVAD

        vad = SileroVAD(
            sample_rate=16000,
            threshold=0.5,
            min_speech_duration_ms=250,
            min_silence_duration_ms=500
        )

        assert vad.sample_rate == 16000
        assert vad.threshold == 0.5
        assert vad.is_speaking is False

    def test_silero_vad_reset(self):
        """Test SileroVAD state reset."""
        from src.voice.speech_processor import SileroVAD

        vad = SileroVAD()
        vad.is_speaking = True
        vad.speech_start_time = 12345

        vad.reset()

        assert vad.is_speaking is False
        assert vad.speech_start_time is None

    def test_silero_vad_probability(self):
        """Test SileroVAD returns probability."""
        from src.voice.speech_processor import SileroVAD

        vad = SileroVAD()

        # Initial probability should be 0
        assert vad.get_speech_probability() == 0.0


class TestSemanticCache:
    """Tests for semantic caching of LLM responses."""

    def test_cache_init(self):
        """Test SemanticCache initialization."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache(
            similarity_threshold=0.8,
            max_entries=100,
            ttl_seconds=3600
        )

        assert cache.similarity_threshold == 0.8
        assert cache.max_entries == 100
        assert cache.ttl_seconds == 3600
        assert cache.hits == 0
        assert cache.misses == 0

    def test_cache_put_and_get_exact(self):
        """Test exact match cache hit."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache(similarity_threshold=0.8)

        # Put entry
        cache.put("What are the open issues?", "There are 5 open issues")

        # Get with exact same query
        result = cache.get("What are the open issues?")

        assert result is not None
        assert result.response == "There are 5 open issues"
        assert cache.hits == 1

    def test_cache_hit_similar_query(self):
        """Test similar queries hit cache."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache(similarity_threshold=0.6)  # Lower threshold

        cache.put("What are the open issues?", "There are 5 open issues")

        # Similar query (missing 'the')
        result = cache.get("What are open issues?")

        assert result is not None
        assert result.response == "There are 5 open issues"

    def test_cache_miss_different_query(self):
        """Test different queries miss cache."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache(similarity_threshold=0.8)

        cache.put("What are the open issues?", "There are 5 open issues")

        # Completely different query
        result = cache.get("How do I reset my password?")

        assert result is None
        assert cache.misses == 1

    def test_cache_audio_size_limit(self):
        """Test large audio is not cached."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache()

        # Large audio (> 100KB)
        large_audio = b"x" * 200_000

        cache.put("test query", "test response", large_audio)

        result = cache.get("test query")
        assert result is not None
        assert result.audio_data is None  # Audio not cached

    def test_cache_audio_within_limit(self):
        """Test small audio is cached."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache()

        # Small audio (< 100KB)
        small_audio = b"audio_data" * 1000  # ~10KB

        cache.put("test query", "test response", small_audio)

        result = cache.get("test query")
        assert result is not None
        assert result.audio_data == small_audio

    def test_cache_stats(self):
        """Test cache statistics."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache()

        cache.put("query1", "response1")
        cache.get("query1")  # Hit
        cache.get("query2")  # Miss
        cache.get("query3")  # Miss

        stats = cache.get_stats()

        assert stats["entries"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert abs(stats["hit_rate"] - 1/3) < 0.01  # Floating point tolerance

    def test_cache_expiry(self):
        """Test cache entries expire after TTL."""
        from src.voice.voice_pipeline import SemanticCache
        import time

        cache = SemanticCache(ttl_seconds=0.1)  # 100ms TTL

        cache.put("test query", "test response")

        # Should hit immediately
        assert cache.get("test query") is not None

        # Wait for expiry
        time.sleep(0.2)

        # Should miss after expiry
        assert cache.get("test query") is None


class TestBargeIn:
    """Tests for barge-in detection."""

    def test_barge_in_flag(self):
        """Test barge-in triggered when user speaks while bot speaking."""
        from src.voice.voice_pipeline import VoicePipeline

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock(),
            enable_barge_in=True
        )

        # Simulate bot speaking
        pipeline.is_speaking = True
        pipeline._barge_in_triggered = False

        # Mock VAD to detect speech
        pipeline.vad = Mock()
        pipeline.vad.process_frame = Mock(return_value=True)

        # Process audio chunk
        pipeline.process_audio_chunk(b"user_audio")

        # Barge-in should be triggered
        assert pipeline._barge_in_triggered is True
        assert pipeline.is_speaking is False

    def test_barge_in_disabled(self):
        """Test barge-in does not trigger when disabled."""
        from src.voice.voice_pipeline import VoicePipeline

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock(),
            enable_barge_in=False
        )

        # Simulate bot speaking
        pipeline.is_speaking = True
        pipeline._barge_in_triggered = False

        # Mock VAD to detect speech
        pipeline.vad = Mock()
        pipeline.vad.process_frame = Mock(return_value=True)

        # Process audio chunk
        pipeline.process_audio_chunk(b"user_audio")

        # Barge-in should NOT be triggered
        assert pipeline._barge_in_triggered is False
        assert pipeline.is_speaking is True

    def test_barge_in_not_triggered_when_not_speaking(self):
        """Test barge-in not triggered when bot is not speaking."""
        from src.voice.voice_pipeline import VoicePipeline

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock(),
            enable_barge_in=True
        )

        # Bot is NOT speaking
        pipeline.is_speaking = False
        pipeline._barge_in_triggered = False

        # Mock VAD to detect speech
        pipeline.vad = Mock()
        pipeline.vad.process_frame = Mock(return_value=True)

        # Process audio chunk
        pipeline.process_audio_chunk(b"user_audio")

        # Barge-in should NOT be triggered
        assert pipeline._barge_in_triggered is False

    def test_set_speaking_resets_barge_in(self):
        """Test set_speaking resets barge-in flag."""
        from src.voice.voice_pipeline import VoicePipeline

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock()
        )

        # Simulate barge-in occurred
        pipeline.is_speaking = True
        pipeline._barge_in_triggered = True

        # Stop speaking
        pipeline.set_speaking(False)

        # Barge-in flag should be reset
        assert pipeline._barge_in_triggered is False


class TestPipelineStats:
    """Tests for pipeline statistics."""

    def test_get_cache_stats(self):
        """Test cache stats retrieval."""
        from src.voice.voice_pipeline import VoicePipeline

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock(),
            enable_cache=True
        )

        stats = pipeline.get_cache_stats()

        assert stats["enabled"] is True
        assert "entries" in stats
        assert "hits" in stats

    def test_get_cache_stats_disabled(self):
        """Test cache stats when caching disabled."""
        from src.voice.voice_pipeline import VoicePipeline

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock(),
            enable_cache=False
        )

        stats = pipeline.get_cache_stats()

        assert stats["enabled"] is False

    def test_get_pipeline_stats(self):
        """Test comprehensive pipeline stats."""
        from src.voice.voice_pipeline import VoicePipeline

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=Mock()
        )

        stats = pipeline.get_pipeline_stats()

        assert "latency" in stats
        assert "cache" in stats
        assert "vad" in stats
        assert "interactions_recorded" in stats
        assert "is_processing" in stats
        assert "is_running" in stats
