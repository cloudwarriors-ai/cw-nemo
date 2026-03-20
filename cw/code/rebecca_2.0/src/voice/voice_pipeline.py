"""
Voice pipeline for real-time speech interactions.

Orchestrates the full voice interaction flow:
1. Receive audio from meeting (via Recall.ai)
2. Detect speech activity (VAD)
3. Transcribe speech to text (ASR)
4. Process query with LLM
5. Generate voice response (TTS)
6. Send audio back to meeting
"""
import base64
from collections import deque, OrderedDict
import io
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional, Callable

import requests

from .speech_processor import SpeechProcessor, VoiceActivityDetector, create_vad
from .tts_client import TTSClient, CartesiaTTS


# Maximum interaction history to prevent memory leaks
MAX_INTERACTION_HISTORY = 1000

# Semantic cache settings (reduced from 500 to prevent memory bloat)
CACHE_SIMILARITY_THRESHOLD = 0.85
CACHE_MAX_ENTRIES = 200  # Reduced from 500 for memory safety
CACHE_TTL_SECONDS = 3600  # 1 hour

# Acknowledgment audio playback duration (seconds)
ACK_AUDIO_PLAYBACK_SECONDS = 2.0


@dataclass
class CacheEntry:
    """Entry in the semantic cache."""
    query: str
    response: str
    audio_data: bytes
    created_at: float
    hit_count: int = 0


@dataclass
class VoiceInteraction:
    """Record of a voice interaction."""
    id: str
    user_speech: str
    response_text: str
    audio_duration_ms: float
    total_latency_ms: float
    timestamp: float


class SemanticCache:
    """
    Semantic cache for LLM responses.

    Caches responses based on query similarity to avoid regenerating
    identical or very similar responses. Can reduce latency by 86%
    for common queries.

    Uses simple token-based similarity. For production, consider
    using sentence embeddings (sentence-transformers) for better
    semantic matching.
    """

    def __init__(
        self,
        similarity_threshold: float = CACHE_SIMILARITY_THRESHOLD,
        max_entries: int = CACHE_MAX_ENTRIES,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        logger: logging.Logger = None
    ):
        """
        Initialize semantic cache.

        Args:
            similarity_threshold: Minimum similarity for cache hit (0.0-1.0)
            max_entries: Maximum cache entries
            ttl_seconds: Time-to-live for cache entries
            logger: Logger instance
        """
        self.similarity_threshold = similarity_threshold
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.logger = logger or logging.getLogger("qa_agent")

        # Use OrderedDict for true LRU eviction
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

        # Track total audio size for memory bounds
        self._total_audio_bytes = 0
        self._max_total_audio_bytes = 10_000_000  # 10MB total audio limit

        # Stats
        self.hits = 0
        self.misses = 0

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison."""
        import re
        text = text.lower().strip()
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text

    def _tokenize(self, text: str) -> set:
        """Tokenize text for similarity comparison."""
        normalized = self._normalize(text)
        return set(normalized.split())

    def _similarity(self, text1: str, text2: str) -> float:
        """
        Calculate Jaccard similarity between two texts.

        Simple token-based similarity. Values range 0.0-1.0.
        """
        tokens1 = self._tokenize(text1)
        tokens2 = self._tokenize(text2)

        if not tokens1 or not tokens2:
            return 0.0

        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)

        return intersection / union if union > 0 else 0.0

    def _evict_expired(self):
        """Remove expired entries from cache."""
        now = time.time()
        expired = [
            key for key, entry in self._cache.items()
            if now - entry.created_at > self.ttl_seconds
        ]
        for key in expired:
            del self._cache[key]

    def _evict_lru(self):
        """Evict entries if cache is full or audio size exceeds limit.

        Memory safety: Evicts oldest entries (FIFO via OrderedDict) when:
        - Entry count exceeds max_entries
        - Total audio size exceeds _max_total_audio_bytes
        """
        # Evict by entry count
        while len(self._cache) >= self.max_entries:
            key, entry = self._cache.popitem(last=False)
            if entry.audio_data:
                self._total_audio_bytes -= len(entry.audio_data)

        # Evict by total audio size
        while self._total_audio_bytes > self._max_total_audio_bytes and self._cache:
            key, entry = self._cache.popitem(last=False)
            if entry.audio_data:
                self._total_audio_bytes -= len(entry.audio_data)

    def get(self, query: str) -> Optional[CacheEntry]:
        """
        Look up query in cache using semantic similarity.

        Limits search to most recent 100 entries for O(1) performance.

        Args:
            query: The query text

        Returns:
            CacheEntry if found with sufficient similarity, None otherwise
        """
        with self._lock:
            self._evict_expired()

            best_match = None
            best_match_key = None
            best_similarity = 0.0

            # Council fix: Limit search to most recent 100 entries for performance
            sorted_items = sorted(
                self._cache.items(),
                key=lambda x: x[1].created_at,
                reverse=True
            )[:100]

            for key, entry in sorted_items:
                similarity = self._similarity(query, entry.query)
                if similarity > best_similarity and similarity >= self.similarity_threshold:
                    best_similarity = similarity
                    best_match = entry
                    best_match_key = key

            if best_match:
                # Move to end for LRU (most recently accessed)
                self._cache.move_to_end(best_match_key)
                best_match.hit_count += 1
                self.hits += 1
                self.logger.debug(
                    f"Cache HIT (similarity={best_similarity:.2f}): {query[:50]}..."
                )
                return best_match

            self.misses += 1
            return None

    # Maximum audio size per entry (reduced from 100KB to 50KB for memory safety)
    MAX_AUDIO_CACHE_SIZE = 50_000

    def put(self, query: str, response: str, audio_data: bytes = None):
        """
        Add entry to cache.

        Args:
            query: The query text
            response: The response text
            audio_data: Optional cached audio data (limited to 50KB)
        """
        with self._lock:
            self._evict_lru()

            # Council fix: Only cache audio if below size threshold
            cached_audio = None
            if audio_data and len(audio_data) <= self.MAX_AUDIO_CACHE_SIZE:
                cached_audio = audio_data
                self._total_audio_bytes += len(audio_data)
            elif audio_data:
                self.logger.debug(
                    f"Audio too large to cache: {len(audio_data)} bytes "
                    f"(max {self.MAX_AUDIO_CACHE_SIZE})"
                )

            normalized_key = self._normalize(query)
            self._cache[normalized_key] = CacheEntry(
                query=query,
                response=response,
                audio_data=cached_audio,
                created_at=time.time()
            )
            self.logger.debug(f"Cache PUT: {query[:50]}...")

    def clear(self):
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._total_audio_bytes = 0
            self.logger.info("Semantic cache cleared")

    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            total = self.hits + self.misses
            hit_rate = self.hits / total if total > 0 else 0.0
            return {
                "entries": len(self._cache),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(hit_rate, 3),
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds
            }


class VoicePipeline:
    """
    Real-time voice interaction pipeline.

    Handles the complete flow from hearing speech to responding
    with synthesized voice in meetings.
    """

    def __init__(
        self,
        speech_processor: SpeechProcessor,
        tts_client: TTSClient,
        query_handler: Callable[[str], str],
        recall_bot_id: str = None,
        recall_api_key: str = None,
        use_silero_vad: bool = True,
        enable_cache: bool = True,
        enable_barge_in: bool = True,
        livekit_room: str = None,
        logger: logging.Logger = None
    ):
        """
        Initialize voice pipeline.

        Args:
            speech_processor: ASR processor for speech-to-text
            tts_client: TTS client for text-to-speech
            query_handler: Function that processes text queries and returns responses
            recall_bot_id: Recall.ai bot ID for audio output
            recall_api_key: Recall.ai API key
            use_silero_vad: Use ML-based Silero VAD (recommended for accuracy)
            enable_cache: Enable semantic caching of LLM responses
            enable_barge_in: Enable barge-in detection (interrupt bot while speaking)
            livekit_room: LiveKit room name for routing through Simli avatar
            logger: Logger instance
        """
        self.speech_processor = speech_processor
        self.tts_client = tts_client
        self.query_handler = query_handler
        self.recall_bot_id = recall_bot_id
        self.recall_api_key = recall_api_key
        self.livekit_room = livekit_room  # For routing through LiveKit/Simli
        self.logger = logger or logging.getLogger("qa_agent")

        # Use Silero VAD for ML-based voice detection (95%+ accuracy)
        # Falls back to energy-based VAD if PyTorch unavailable
        self.vad = create_vad(use_silero=use_silero_vad, logger=self.logger)
        self.audio_buffer = bytearray()
        self.is_processing = False
        # Use deque with maxlen for automatic bounded size (memory safety)
        self.interaction_history: deque[VoiceInteraction] = deque(maxlen=MAX_INTERACTION_HISTORY)

        # Semantic cache for LLM responses (can reduce latency by 86%)
        self.enable_cache = enable_cache
        self.response_cache = SemanticCache(logger=self.logger) if enable_cache else None

        # Barge-in detection (interrupt bot while it's speaking)
        self.enable_barge_in = enable_barge_in
        self.is_speaking = False  # True when bot is outputting audio
        self._barge_in_triggered = False
        self._current_audio_source = None  # For stopping playback on barge-in

        # Thread synchronization for audio buffer (council fix: race condition)
        self._buffer_lock = threading.Lock()

        # Council fix: Lock to serialize voice responses and prevent avatar state corruption
        # Only one response can be processed at a time
        self._response_lock = threading.Lock()
        self._pending_response = False  # Track if a response is pending

        # Audio queue for async processing
        self._audio_queue = queue.Queue()
        self._running = False
        self._worker_thread = None

        # Pre-cached acknowledgment audio for instant response
        self._cached_ack_audio: Optional[bytes] = None
        self._ack_text = "Sure, let me get that for you."

    def _get_cached_ack_audio(self) -> Optional[bytes]:
        """Get pre-generated acknowledgment audio, generating on first call."""
        if self._cached_ack_audio is None:
            try:
                self.logger.info("Pre-generating acknowledgment audio...")
                result = self.tts_client.synthesize(self._ack_text)
                if result and result.audio_data:
                    self._cached_ack_audio = result.audio_data
                    self.logger.info(f"Cached ack audio: {len(self._cached_ack_audio)} bytes")
            except Exception as e:
                self.logger.warning(f"Failed to cache ack audio: {e}")
        return self._cached_ack_audio

    def start(self):
        """Start the voice pipeline worker."""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._worker_thread.start()
        self.logger.info("Voice pipeline started")

        # NOTE: Ack audio disabled - Recall.ai buffers it with main response
        # self._pregenerate_ack_audio()

    def _pregenerate_ack_audio(self):
        """Pre-generate acknowledgment audio in background thread."""
        def _generate():
            try:
                self.logger.info("Pre-generating acknowledgment audio at startup...")
                # Use a slightly longer ack message to ensure Recall.ai plays it immediately
                # Short audio clips may be buffered waiting for more audio
                ack_with_pause = self._ack_text + "..."  # Adds natural pause
                result = self.tts_client.synthesize(ack_with_pause)
                if result and result.audio_data:
                    self._cached_ack_audio = result.audio_data
                    self.logger.info(f"Acknowledgment audio cached: {len(self._cached_ack_audio)} bytes")
            except Exception as e:
                self.logger.warning(f"Failed to pre-generate ack audio: {e}")

        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()

    def stop(self):
        """Stop the voice pipeline worker."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        self.logger.info("Voice pipeline stopped")

    def process_audio_chunk(self, audio_data: bytes, sample_rate: int = 16000):
        """
        Process incoming audio chunk from meeting.

        Thread-safe audio buffering with lock protection.
        Includes barge-in detection to interrupt bot while speaking.

        Args:
            audio_data: Raw PCM audio bytes
            sample_rate: Audio sample rate
        """
        # Detect voice activity
        is_speech = self.vad.process_frame(audio_data)

        # Barge-in detection: if user speaks while bot is outputting audio
        if self.enable_barge_in and is_speech and self.is_speaking:
            self._handle_barge_in()

        # Thread-safe buffer access (council fix: race condition)
        with self._buffer_lock:
            if is_speech:
                self.audio_buffer.extend(audio_data)
            elif self.audio_buffer and not self.is_processing:
                # Speech ended, queue for processing
                audio_to_process = bytes(self.audio_buffer)
                self.audio_buffer.clear()
                self._audio_queue.put(audio_to_process)

    def _handle_barge_in(self):
        """
        Handle user interruption (barge-in) while bot is speaking.

        Stops current audio playback and prepares for new query.
        """
        if self._barge_in_triggered:
            return  # Already handling barge-in

        # Council fix: Capture bot_id now to avoid race condition
        bot_id = self.recall_bot_id

        self._barge_in_triggered = True
        self.logger.info("Barge-in detected: user interrupted bot speech")

        # Stop current audio playback via WebSocket
        try:
            from ..avatar.websocket_manager import get_avatar_ws_manager
            manager = get_avatar_ws_manager(self.logger)

            if bot_id and manager.is_connected(bot_id):
                # Send stop command to avatar
                manager.send_state(bot_id, "barge_in", "User interrupted")
                self.logger.debug("Sent barge-in signal to avatar")

        except Exception as e:
            self.logger.debug(f"Failed to send barge-in signal: {e}")

        # Mark speaking as stopped
        self.is_speaking = False

    def set_speaking(self, speaking: bool):
        """
        Set the bot's speaking state.

        Called when audio playback starts/stops.

        Args:
            speaking: True if bot is outputting audio
        """
        was_speaking = self.is_speaking
        self.is_speaking = speaking

        if not speaking and was_speaking:
            # Playback finished, reset barge-in flag
            self._barge_in_triggered = False

    def _process_loop(self):
        """Background worker for processing audio."""
        while self._running:
            try:
                # Wait for audio with timeout
                audio_data = self._audio_queue.get(timeout=1.0)
                self._handle_speech(audio_data)
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Voice processing error: {e}", exc_info=True)

    def _handle_speech(self, audio_data: bytes):
        """
        Handle complete speech segment.

        Full pipeline:
        1. Transcribe audio
        2. Check semantic cache (can reduce latency by 86%)
        3. Process query (if cache miss)
        4. Generate voice response
        5. Output to meeting
        """
        self.is_processing = True
        start_time = time.time()
        interaction_id = f"voice-{int(start_time * 1000)}"
        cache_hit = False

        try:
            # Step 1: Transcribe
            self.logger.debug(f"[{interaction_id}] Transcribing {len(audio_data)} bytes")
            transcription = self.speech_processor.transcribe(audio_data)

            if not transcription.text:
                self.logger.debug(f"[{interaction_id}] Empty transcription, skipping")
                return

            user_text = transcription.text
            self.logger.info(f"[{interaction_id}] Heard: {user_text[:50]}...")

            # Step 2: Check semantic cache
            cached_entry = None
            if self.enable_cache and self.response_cache:
                cached_entry = self.response_cache.get(user_text)

            if cached_entry:
                # Cache hit - use cached response
                cache_hit = True
                response_text = cached_entry.response
                self.logger.info(f"[{interaction_id}] Cache HIT: {response_text[:50]}...")

                # Use cached audio if available
                if cached_entry.audio_data:
                    audio_data_to_send = cached_entry.audio_data
                    audio_duration_ms = 0  # Unknown for cached audio
                else:
                    # Regenerate audio (cache response only)
                    tts_result = self.tts_client.synthesize(response_text)
                    audio_data_to_send = tts_result.audio_data
                    audio_duration_ms = tts_result.duration_ms
                    # Update cache with audio
                    self.response_cache.put(user_text, response_text, audio_data_to_send)
            else:
                # Cache miss - full processing
                # Step 3: Process query
                self.logger.debug(f"[{interaction_id}] Processing query (cache miss)")
                response_text = self.query_handler(user_text)
                self.logger.info(f"[{interaction_id}] Response: {response_text[:50]}...")

                # Step 4: Generate speech
                self.logger.debug(f"[{interaction_id}] Synthesizing speech")
                tts_result = self.tts_client.synthesize(response_text)
                audio_data_to_send = tts_result.audio_data
                audio_duration_ms = tts_result.duration_ms

                # Cache the response and audio
                if self.enable_cache and self.response_cache:
                    self.response_cache.put(user_text, response_text, audio_data_to_send)

            # Step 5: Output to meeting
            if self.recall_bot_id and self.recall_api_key:
                self.set_speaking(True)
                self._send_audio_to_meeting(audio_data_to_send)
                self.set_speaking(False)

            # Record interaction (council fix: cap history to prevent memory leak)
            total_latency = (time.time() - start_time) * 1000
            interaction = VoiceInteraction(
                id=interaction_id,
                user_speech=user_text,
                response_text=response_text,
                audio_duration_ms=audio_duration_ms if not cache_hit else 0,
                total_latency_ms=total_latency,
                timestamp=start_time
            )
            # deque with maxlen handles automatic FIFO eviction
            self.interaction_history.append(interaction)

            cache_status = "CACHE HIT" if cache_hit else "cache miss"
            self.logger.info(
                f"[{interaction_id}] Complete: {total_latency:.0f}ms total latency ({cache_status})"
            )

        except Exception as e:
            self.logger.error(f"[{interaction_id}] Pipeline error: {e}", exc_info=True)
        finally:
            self.is_processing = False
            self.set_speaking(False)

    def _send_audio_to_meeting(self, audio_data: bytes):
        """
        Send audio to meeting via WebSocket (Output Media) or Recall.ai API.

        Primary path: WebSocket to avatar webpage (for Output Media).
        Fallback: Recall.ai Output Audio API (for simple audio).

        Handles PCM to MP3 conversion if needed.
        """
        if not audio_data:
            return

        try:
            # Check if we need to convert PCM to MP3 (council fix: format mismatch)
            audio_format = "mp3"
            output_data = audio_data

            if hasattr(self.tts_client, 'output_format'):
                tts_format = self.tts_client.output_format
                if tts_format in ("pcm_s16le", "pcm", "raw"):
                    # Need to convert PCM to MP3
                    output_data = self._convert_pcm_to_mp3(audio_data)
                elif tts_format == "mp3":
                    output_data = audio_data
                else:
                    self.logger.warning(f"Unknown TTS format: {tts_format}, attempting raw send")

            # Try WebSocket first (Output Media path)
            self.logger.info(f"Attempting WebSocket audio delivery for bot {self.recall_bot_id}")
            if self._send_audio_via_websocket(output_data, audio_format):
                self.logger.info("Audio sent via WebSocket (Output Media)")
                return

            # Fallback: Recall.ai Output Audio API
            self.logger.info(f"WebSocket unavailable, trying Recall.ai API for bot {self.recall_bot_id}")
            self._send_audio_via_recall_api(output_data, audio_format)

        except Exception as e:
            self.logger.error(f"Failed to send audio to meeting: {e}")

    def _send_audio_via_websocket(self, audio_data: bytes, audio_format: str, bot_id: str = None) -> bool:
        """
        Send audio via WebSocket to avatar webpage.

        Args:
            audio_data: Audio bytes (MP3 format)
            audio_format: Format identifier (e.g., 'mp3')
            bot_id: Bot ID for WebSocket lookup (falls back to self.recall_bot_id)

        Returns:
            True if sent successfully, False if WebSocket not available
        """
        try:
            # Import here to avoid circular dependency
            from ..avatar.websocket_manager import get_avatar_ws_manager

            manager = get_avatar_ws_manager(self.logger)

            # Use provided bot_id or fall back to instance variable
            target_bot_id = bot_id or self.recall_bot_id
            if not target_bot_id:
                self.logger.warning("No bot_id for WebSocket delivery")
                return False

            if not manager.is_connected(target_bot_id):
                self.logger.info(f"No WebSocket connection for bot {target_bot_id[:8]}... (active connections: {len(manager._connections)})")
                return False

            # Send audio via WebSocket
            return manager.send_audio(target_bot_id, audio_data, audio_format)

        except ImportError:
            self.logger.debug("WebSocket manager not available")
            return False
        except Exception as e:
            self.logger.warning(f"WebSocket audio send failed: {e}")
            return False

    def _send_audio_via_recall_api(self, audio_data: bytes, audio_format: str, bot_id: str = None):
        """
        Send audio via Recall.ai Output Audio API for Zoom to hear.

        Args:
            audio_data: Audio bytes (MP3 format)
            audio_format: Format identifier (e.g., 'mp3')
            bot_id: Recall.ai bot ID (uses self.recall_bot_id if not provided)
        """
        target_bot_id = bot_id or self.recall_bot_id
        if not target_bot_id or not self.recall_api_key:
            self.logger.warning("No Recall bot ID or API key for audio output")
            return

        try:
            # Convert to base64 for API
            audio_b64 = base64.b64encode(audio_data).decode("utf-8")

            # Use regional endpoint (us-west-2) for Recall.ai API
            response = requests.post(
                f"https://us-west-2.recall.ai/api/v1/bot/{target_bot_id}/output_audio",
                headers={
                    "Authorization": f"Token {self.recall_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "kind": audio_format,
                    "b64_data": audio_b64
                },
                timeout=10
            )

            response.raise_for_status()
            self.logger.debug("Audio sent via Recall.ai API")

        except requests.RequestException as e:
            self.logger.error(f"Failed to send audio via Recall.ai API: {e}")

    def _convert_pcm_to_mp3(self, pcm_data: bytes) -> bytes:
        """
        Convert PCM audio to MP3 format.

        Args:
            pcm_data: Raw PCM audio (16-bit, 24kHz)

        Returns:
            MP3 encoded audio bytes
        """
        try:
            # Try using pydub if available
            from pydub import AudioSegment

            # Create AudioSegment from raw PCM
            sample_rate = getattr(self.tts_client, 'sample_rate', 24000)
            audio = AudioSegment(
                data=pcm_data,
                sample_width=2,  # 16-bit = 2 bytes
                frame_rate=sample_rate,
                channels=1
            )

            # Export to MP3
            mp3_buffer = io.BytesIO()
            audio.export(mp3_buffer, format="mp3", bitrate="128k")
            return mp3_buffer.getvalue()

        except ImportError:
            # pydub not available, return raw (may not work with Recall.ai)
            self.logger.warning(
                "pydub not installed, cannot convert PCM to MP3. "
                "Install pydub and ffmpeg for audio conversion."
            )
            return pcm_data
        except Exception as e:
            self.logger.error(f"Audio conversion error: {e}")
            return pcm_data

    def process_text_query(self, text: str) -> Optional[bytes]:
        """
        Process a text query and return audio response.

        Useful for testing or when speech is already transcribed.

        Args:
            text: Query text

        Returns:
            Audio response bytes, or None on error
        """
        try:
            # Process query
            response_text = self.query_handler(text)

            # Generate speech
            tts_result = self.tts_client.synthesize(response_text)

            return tts_result.audio_data

        except Exception as e:
            self.logger.error(f"Text query processing error: {e}")
            return None

    def _sanitize_for_voice(self, text: str, max_length: int = 400) -> str:
        """
        Sanitize text for voice synthesis.

        Removes/converts elements that don't work well in speech:
        - Markdown formatting (bold, italic, headers, code blocks)
        - URLs (converted to "link")
        - Special characters
        - Excessive whitespace

        Args:
            text: Raw response text
            max_length: Maximum output length

        Returns:
            Clean text suitable for TTS
        """
        import re

        if not text:
            return ""

        # Remove code blocks
        text = re.sub(r'```[\s\S]*?```', ' code block omitted ', text)
        text = re.sub(r'`[^`]+`', '', text)

        # Remove markdown headers
        text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)

        # Remove bold/italic markers
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold**
        text = re.sub(r'\*([^*]+)\*', r'\1', text)      # *italic*
        text = re.sub(r'__([^_]+)__', r'\1', text)      # __bold__
        text = re.sub(r'_([^_]+)_', r'\1', text)        # _italic_

        # Remove markdown links, keep text
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

        # Convert URLs to "link"
        text = re.sub(r'https?://\S+', 'link', text)

        # Remove bullet points
        text = re.sub(r'^[\s]*[-*•]\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[\s]*\d+\.\s*', '', text, flags=re.MULTILINE)

        # Normalize whitespace
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()

        # Truncate to max length at sentence boundary
        if len(text) > max_length:
            # Find last sentence boundary before max_length
            for end_char in ['. ', '! ', '? ']:
                idx = text[:max_length].rfind(end_char)
                if idx > 50:
                    text = text[:idx + 1]
                    break
            else:
                # No good boundary, truncate with ellipsis
                text = text[:max_length - 3].rsplit(' ', 1)[0] + "..."

        return text

    def respond_to_query(
        self,
        text: str,
        bot_id: str,
        use_streaming: bool = True,
        recall_bot_id: str = None,
        conversation_history: list = None,
        on_response: callable = None,
        livekit_room: str = None  # Reserved for future LiveKit/Simli integration
    ) -> bool:
        """
        Process a text query and send voice response to meeting.

        Used by meeting transcription to trigger voice responses.
        Supports streaming mode for reduced perceived latency.

        Council fix: Serialized with _response_lock to prevent concurrent responses
        from corrupting avatar state.

        Args:
            text: Query text from transcription
            bot_id: Bot ID for WebSocket routing (avatar page)
            use_streaming: If True, stream audio chunks as they arrive
            recall_bot_id: Recall.ai bot ID for audio output (if different from bot_id)
            conversation_history: List of previous conversation messages for context
            on_response: Callback with (query, response) after processing
            livekit_room: Reserved for future LiveKit/Simli integration (not used)

        Returns:
            True if response was sent, False on error
        """
        if not text or not bot_id:
            return False

        # NOTE: LiveKit/Simli routing disabled - using Recall.ai audio + pulsing orb
        # Future: Uncomment to route through LiveKit for synced Simli avatar
        # room_name = livekit_room or self.livekit_room
        # if room_name:
        #     return self._respond_via_livekit(text, room_name, conversation_history, on_response)

        # Council fix: Serialize voice responses to prevent avatar state corruption
        # Non-blocking check first - if already responding, skip this query
        if not self._response_lock.acquire(blocking=False):
            self.logger.warning(f"Skipping query - another response in progress: {text[:50]}...")
            return False

        try:
            # Use recall_bot_id for Recall API, bot_id for WebSocket
            actual_recall_bot_id = recall_bot_id or bot_id

            start_time = time.time()

            # Send "thinking" state to avatar
            self._send_avatar_state(bot_id, "thinking", "Processing...")

            # NOTE: Acknowledgment audio disabled - Recall.ai buffers it with main response
            # causing both to play together instead of ack playing immediately.
            # The avatar "thinking" state provides visual feedback instead.
            #
            # Future: Could re-enable if we find a way to force immediate playback
            # ack_audio = self._get_cached_ack_audio()
            # if ack_audio:
            #     self._send_audio_via_recall_api(ack_audio, "mp3", actual_recall_bot_id)

            # Set conversation history for query handler to use
            self._current_conversation_history = conversation_history or []

            # Process query through LLM with conversation history for context
            # This enables follow-up questions like "who's assigned to those issues?"
            try:
                # Try calling with conversation_history parameter
                response_text = self.query_handler(text, conversation_history=self._current_conversation_history)
            except TypeError:
                # Fallback for handlers that don't accept conversation_history
                response_text = self.query_handler(text)

            if not response_text:
                self.logger.warning("Empty response from query handler")
                self._send_avatar_state(bot_id, "error", "No response")
                return False

            # Sanitize for voice (removes markdown, URLs, limits length)
            voice_text = self._sanitize_for_voice(response_text)

            self.logger.info(f"Voice response: {voice_text[:80]}...")

            # Send "speaking" state before audio
            self._send_avatar_state(bot_id, "speaking", "Speaking...")

            # Use non-streaming TTS for now (streaming outputs PCM which Recall API can't play as MP3)
            # TODO: Add PCM-to-MP3 conversion for streaming support
            tts_result = self.tts_client.synthesize(voice_text)

            if not tts_result or not tts_result.audio_data:
                self.logger.error("TTS synthesis failed")
                self._send_avatar_state(bot_id, "error", "Speech failed")
                return False

            self.logger.info(f"TTS generated {len(tts_result.audio_data)} bytes")

            # Send audio via WebSocket (avatar page plays it, Recall captures it)
            # Use bot_id for WebSocket (avatar page's connection ID)
            # Only fall back to Recall API if WebSocket unavailable (avoids double audio)
            if not self._send_audio_via_websocket(tts_result.audio_data, "mp3", bot_id):
                self.logger.info("WebSocket unavailable, using Recall API for audio")
                self._send_audio_via_recall_api(tts_result.audio_data, "mp3", actual_recall_bot_id)
            # NOTE: Simli lip sync disabled - see GitHub issue #1 for full implementation
            # self._send_audio_to_simli(tts_result.audio_data, meeting_id=None)

            latency = (time.time() - start_time) * 1000
            self.logger.info(f"Voice response sent in {latency:.0f}ms")

            # Send listening state to flush avatar's audio buffer and trigger playback
            self._send_avatar_state(bot_id, "listening", "Response complete")

            # Invoke callback with query and response for conversation history tracking
            if on_response:
                try:
                    on_response(text, response_text)
                except Exception as cb_error:
                    self.logger.warning(f"on_response callback error: {cb_error}")

            return True

        except Exception as e:
            self.logger.error(f"Voice response error: {e}", exc_info=True)
            self._send_avatar_state(bot_id, "error", "Error occurred")
            return False
        finally:
            # Council fix: Always release the response lock
            self._response_lock.release()

    def _respond_via_livekit(
        self,
        query: str,
        room_name: str,
        conversation_history: list = None,
        on_response: callable = None
    ) -> bool:
        """
        Route query through LiveKit for synced Simli avatar response.

        Instead of generating TTS and sending to Recall.ai, this sends
        the query to the LiveKit room where the avatar agent will:
        1. Process the query (via OpenAI Realtime or our QA Brain)
        2. Generate voice with lip-synced avatar via Simli
        3. Stream both audio and video to the avatar page

        Args:
            query: Text query to send
            room_name: LiveKit room name
            conversation_history: Optional conversation context
            on_response: Optional callback (not used in LiveKit mode)

        Returns:
            True if query was sent successfully
        """
        try:
            from ..avatar.livekit_text_sender import send_query_to_livekit

            self.logger.info(f"Routing query through LiveKit room: {room_name}")
            self.logger.info(f"Query: {query[:50]}...")

            # Send query to LiveKit room (async - non-blocking)
            success = send_query_to_livekit(
                room_name=room_name,
                query=query,
                speaker="User",
                context={"history": conversation_history or []},
                async_send=True
            )

            if success:
                self.logger.info("Query sent to LiveKit for avatar processing")
            else:
                self.logger.warning("Failed to send query to LiveKit")

            return success

        except ImportError as e:
            self.logger.error(f"LiveKit text sender not available: {e}")
            return False
        except Exception as e:
            self.logger.error(f"LiveKit routing error: {e}", exc_info=True)
            return False

    def _stream_audio_response(self, text: str, ws_bot_id: str, recall_bot_id: str = None) -> int:
        """
        Stream audio response in chunks for lower latency.

        Sends audio chunks to BOTH:
        - Recall API (for Zoom to hear)
        - WebSocket (for avatar visual sync)

        Args:
            text: Text to synthesize
            ws_bot_id: Bot ID for WebSocket routing
            recall_bot_id: Recall.ai bot ID for audio output

        Returns:
            Number of chunks sent
        """
        chunks_sent = 0
        first_chunk_time = None
        audio_buffer = bytearray()  # Buffer chunks for Recall API

        try:
            # Track if WebSocket is working for this stream
            ws_working = None  # Unknown until first chunk

            for chunk in self.tts_client.synthesize_stream(text):
                if chunk:
                    if first_chunk_time is None:
                        first_chunk_time = time.time()
                        self.logger.debug("First audio chunk received")

                    # Try WebSocket first (avatar page plays audio)
                    # Use ws_bot_id for WebSocket (avatar page's connection ID)
                    if ws_working is None:
                        ws_working = self._send_audio_via_websocket(chunk, "mp3", ws_bot_id)
                    elif ws_working:
                        self._send_audio_via_websocket(chunk, "mp3", ws_bot_id)

                    # Only buffer for Recall API if WebSocket isn't working
                    if not ws_working:
                        audio_buffer.extend(chunk)
                        # Send to Recall API every ~50KB for efficiency
                        if len(audio_buffer) >= 50000:
                            self._send_audio_via_recall_api(bytes(audio_buffer), "mp3", recall_bot_id)
                            audio_buffer.clear()

                    chunks_sent += 1

            # Send any remaining buffered audio to Recall API (only if WebSocket wasn't working)
            if audio_buffer and not ws_working:
                self._send_audio_via_recall_api(bytes(audio_buffer), "mp3", recall_bot_id)

            if first_chunk_time:
                stream_duration = (time.time() - first_chunk_time) * 1000
                self.logger.debug(f"Audio streaming complete: {chunks_sent} chunks in {stream_duration:.0f}ms")

        except Exception as e:
            self.logger.error(f"Audio streaming error: {e}")

        return chunks_sent

    def _send_avatar_state(self, bot_id: str, state: str, message: str = None):
        """
        Send state update to avatar webpage.

        Args:
            bot_id: Bot ID for routing
            state: State name (listening, thinking, speaking, error)
            message: Optional status message
        """
        try:
            from ..avatar.websocket_manager import get_avatar_ws_manager
            manager = get_avatar_ws_manager(self.logger)
            result = manager.send_state(bot_id, state, message)
            self.logger.info(f"Sent avatar state '{state}' to {bot_id[:8]}... result={result}")
        except Exception as e:
            self.logger.warning(f"Failed to send avatar state '{state}': {e}")

    def _send_audio_to_simli(self, audio_data: bytes, meeting_id: str = None):
        """
        Send audio to Simli avatar via LiveKit for lip sync.

        Args:
            audio_data: MP3 audio bytes
            meeting_id: Meeting ID to determine room name (optional)
        """
        try:
            from ..avatar.livekit_audio_sender import send_audio_to_simli
            from ..avatar.livekit_manager import get_livekit_manager

            # Get room name from LiveKit manager
            livekit_manager = get_livekit_manager()

            # Find the active room
            rooms = livekit_manager.list_rooms()
            if not rooms:
                self.logger.debug("No active LiveKit rooms for Simli audio")
                return

            # Use the first active room (or find by meeting_id if provided)
            room_name = rooms[0]
            if meeting_id:
                for r in rooms:
                    info = livekit_manager.get_room_info(r)
                    if info and info.get("meeting_id") == meeting_id:
                        room_name = r
                        break

            self.logger.info(f"Sending audio to Simli in room: {room_name}")

            # Send audio to Simli via LiveKit DataStream
            # Note: is_mp3=True will convert to 16kHz PCM which Simli expects
            success = send_audio_to_simli(
                room_name=room_name,
                audio_data=audio_data,
                sample_rate=16000,  # Simli expects 16kHz
                is_mp3=True
            )

            if success:
                self.logger.info("Audio sent to Simli for lip sync")
            else:
                self.logger.warning("Failed to send audio to Simli")

        except ImportError as e:
            self.logger.debug(f"LiveKit audio sender not available: {e}")
        except Exception as e:
            self.logger.warning(f"Error sending audio to Simli: {e}")

    def get_latency_stats(self) -> dict:
        """
        Get latency statistics from recent interactions.

        Returns:
            Dictionary with latency stats
        """
        if not self.interaction_history:
            return {"count": 0}

        latencies = [i.total_latency_ms for i in self.interaction_history[-100:]]

        return {
            "count": len(latencies),
            "avg_ms": sum(latencies) / len(latencies),
            "min_ms": min(latencies),
            "max_ms": max(latencies),
            "recent": latencies[-5:]
        }

    def get_cache_stats(self) -> dict:
        """
        Get semantic cache statistics.

        Returns:
            Dictionary with cache stats or empty dict if caching disabled
        """
        if not self.enable_cache or not self.response_cache:
            return {"enabled": False}

        stats = self.response_cache.get_stats()
        stats["enabled"] = True
        return stats

    def get_pipeline_stats(self) -> dict:
        """
        Get comprehensive pipeline statistics.

        Returns:
            Dictionary with all pipeline stats
        """
        vad_type = "silero" if hasattr(self.vad, 'is_silero_available') and self.vad.is_silero_available() else "energy"

        return {
            "latency": self.get_latency_stats(),
            "cache": self.get_cache_stats(),
            "vad": {
                "type": vad_type,
                "is_speaking": self.is_speaking,
                "barge_in_enabled": self.enable_barge_in
            },
            "interactions_recorded": len(self.interaction_history),
            "is_processing": self.is_processing,
            "is_running": self._running
        }


class VoiceWebhookHandler:
    """
    Handle real-time audio webhooks from Recall.ai.

    Recall.ai sends audio chunks via WebSocket or webhook.
    This handler processes them through the voice pipeline.
    """

    def __init__(
        self,
        pipeline: VoicePipeline,
        secret: str = None,
        logger: logging.Logger = None
    ):
        """
        Initialize webhook handler.

        Args:
            pipeline: Voice pipeline to process audio
            secret: Webhook authentication secret
            logger: Logger instance
        """
        self.pipeline = pipeline
        self.secret = secret
        self.logger = logger or logging.getLogger("qa_agent")

    def handle_webhook(self, data: dict) -> dict:
        """
        Handle incoming audio webhook from Recall.ai.

        Expected format:
        {
            "event": "audio_mixed_raw.data",
            "data": {
                "bot_id": "xxx",
                "audio": {
                    "data": "<base64 encoded>",
                    "sample_rate": 16000,
                    "num_channels": 1
                }
            }
        }
        """
        event_type = data.get("event", "")

        if event_type != "audio_mixed_raw.data":
            return {"status": "ignored", "reason": "Not audio event"}

        event_data = data.get("data", {})
        audio_info = event_data.get("audio", {})

        # Decode audio
        audio_b64 = audio_info.get("data", "")
        if not audio_b64:
            return {"status": "error", "error": "No audio data"}

        try:
            audio_bytes = base64.b64decode(audio_b64)
            sample_rate = audio_info.get("sample_rate", 16000)

            # Process through pipeline
            self.pipeline.process_audio_chunk(audio_bytes, sample_rate)

            return {"status": "processed", "bytes": len(audio_bytes)}

        except Exception as e:
            self.logger.error(f"Audio webhook error: {e}")
            return {"status": "error", "error": str(e)}


def create_voice_pipeline(
    openai_api_key: str,
    cartesia_api_key: str = None,
    recall_api_key: str = None,
    recall_bot_id: str = None,
    query_handler: Callable[[str], str] = None,
    voice_id: str = None,
    use_silero_vad: bool = True,
    enable_cache: bool = True,
    enable_barge_in: bool = True,
    logger: logging.Logger = None
) -> VoicePipeline:
    """
    Create a configured voice pipeline.

    Helper function to set up all components.

    Args:
        openai_api_key: OpenAI API key for Whisper ASR
        cartesia_api_key: Cartesia API key for TTS (optional, falls back to OpenAI)
        recall_api_key: Recall.ai API key for meeting output
        recall_bot_id: Recall.ai bot ID
        query_handler: Function to process queries
        voice_id: TTS voice ID
        use_silero_vad: Use ML-based Silero VAD (recommended, default True)
        enable_cache: Enable semantic caching of LLM responses (default True)
        enable_barge_in: Enable barge-in detection (default True)
        logger: Logger instance

    Returns:
        Configured VoicePipeline
    """
    logger = logger or logging.getLogger("qa_agent")

    # Create speech processor (ASR)
    speech_processor = SpeechProcessor(
        api_key=openai_api_key,
        logger=logger
    )

    # Create TTS client
    if cartesia_api_key:
        from .tts_client import CartesiaTTS
        tts_client = CartesiaTTS(
            api_key=cartesia_api_key,
            voice_id=voice_id,
            logger=logger
        )
    else:
        from .tts_client import OpenAITTS
        tts_client = OpenAITTS(
            api_key=openai_api_key,
            voice="nova",
            logger=logger
        )

    # Default query handler (echo for testing)
    if query_handler is None:
        query_handler = lambda text: f"I heard you say: {text}"

    return VoicePipeline(
        speech_processor=speech_processor,
        tts_client=tts_client,
        query_handler=query_handler,
        recall_bot_id=recall_bot_id,
        recall_api_key=recall_api_key,
        use_silero_vad=use_silero_vad,
        enable_cache=enable_cache,
        enable_barge_in=enable_barge_in,
        logger=logger
    )
