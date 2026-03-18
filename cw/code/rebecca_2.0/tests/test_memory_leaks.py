"""
Tests for memory leak prevention.

Validates bounded caching behavior:
- Maximum entry limits
- LRU eviction
- Size-based limits
- Thread safety
"""
import pytest
import threading
import time
from collections import OrderedDict, deque
from unittest.mock import Mock, patch


class TestMessageDedupCache:
    """Tests for message deduplication cache bounds."""

    def test_max_entries_enforced(self, app):
        """Test dedup cache doesn't exceed max entries."""
        from src.bot.app import _message_dedup_cache, _is_duplicate_message, _MAX_DEDUP_CACHE_SIZE

        _message_dedup_cache.clear()

        # Add more than max entries
        for i in range(_MAX_DEDUP_CACHE_SIZE + 100):
            _is_duplicate_message(f"msg-{i}")

        # Should be bounded
        assert len(_message_dedup_cache) <= _MAX_DEDUP_CACHE_SIZE

    def test_first_message_not_duplicate(self, app):
        """Test first occurrence is not marked as duplicate."""
        from src.bot.app import _message_dedup_cache, _is_duplicate_message

        _message_dedup_cache.clear()
        assert _is_duplicate_message("unique-msg-123") is False

    def test_second_message_is_duplicate(self, app):
        """Test second occurrence is marked as duplicate."""
        from src.bot.app import _message_dedup_cache, _is_duplicate_message

        _message_dedup_cache.clear()
        _is_duplicate_message("dup-msg-456")
        assert _is_duplicate_message("dup-msg-456") is True

    def test_cache_uses_ordered_dict(self, app):
        """Test cache is OrderedDict for FIFO eviction."""
        from src.bot.app import _message_dedup_cache

        assert isinstance(_message_dedup_cache, OrderedDict)


class TestConversationHistory:
    """Tests for meeting conversation history bounds."""

    def test_max_meetings_enforced(self, temp_db):
        """Test conversation history doesn't exceed max meetings."""
        from src.meeting.meeting_handler import MeetingHandler

        handler = MeetingHandler(
            recall_client=Mock(),
            db_path=temp_db
        )

        # Add more meetings than limit
        for i in range(handler._MAX_CONVERSATION_MEETINGS + 50):
            handler.add_to_conversation(f"meeting-{i}", "query", "response")

        # Should be bounded
        assert len(handler._conversation_history) <= handler._MAX_CONVERSATION_MEETINGS

    def test_history_uses_ordered_dict(self, temp_db):
        """Test history is OrderedDict for LRU eviction."""
        from src.meeting.meeting_handler import MeetingHandler

        handler = MeetingHandler(
            recall_client=Mock(),
            db_path=temp_db
        )

        assert isinstance(handler._conversation_history, OrderedDict)

    def test_lru_eviction_order(self, temp_db):
        """Test LRU eviction removes oldest meetings first."""
        from src.meeting.meeting_handler import MeetingHandler

        handler = MeetingHandler(
            recall_client=Mock(),
            db_path=temp_db
        )

        # Reduce limit for test
        handler._MAX_CONVERSATION_MEETINGS = 3

        # Add 3 meetings
        handler.add_to_conversation("meeting-1", "q1", "r1")
        handler.add_to_conversation("meeting-2", "q2", "r2")
        handler.add_to_conversation("meeting-3", "q3", "r3")

        # Access meeting-1 to make it recently used
        handler.add_to_conversation("meeting-1", "q1b", "r1b")

        # Add new meeting, should evict meeting-2 (oldest unused)
        handler.add_to_conversation("meeting-4", "q4", "r4")

        assert "meeting-1" in handler._conversation_history  # Recently accessed
        assert "meeting-2" not in handler._conversation_history  # Evicted
        assert "meeting-3" in handler._conversation_history
        assert "meeting-4" in handler._conversation_history

    def test_max_turns_per_meeting(self, temp_db):
        """Test individual meeting history is bounded by MAX_HISTORY_TURNS."""
        from src.meeting.meeting_handler import MeetingHandler

        handler = MeetingHandler(
            recall_client=Mock(),
            db_path=temp_db
        )

        # Add many turns to single meeting
        for i in range(handler.MAX_HISTORY_TURNS + 10):
            handler.add_to_conversation("meeting-x", f"query-{i}", f"response-{i}")

        history = handler._conversation_history["meeting-x"]
        max_messages = handler.MAX_HISTORY_TURNS * 2  # Each turn = 2 messages
        assert len(history) <= max_messages


class TestVoiceInteractionHistory:
    """Tests for voice pipeline interaction history bounds."""

    def test_interaction_history_uses_deque(self):
        """Test interaction history is a deque with maxlen."""
        from src.voice.voice_pipeline import VoicePipeline, MAX_INTERACTION_HISTORY

        pipeline = VoicePipeline(
            speech_processor=Mock(),
            tts_client=Mock(),
            query_handler=lambda x: "response"
        )

        assert isinstance(pipeline.interaction_history, deque)
        assert pipeline.interaction_history.maxlen == MAX_INTERACTION_HISTORY

    def test_deque_auto_eviction(self):
        """Test deque automatically evicts old entries."""
        from src.voice.voice_pipeline import VoiceInteraction

        # Create a small deque
        history = deque(maxlen=3)

        # Add more than maxlen
        for i in range(5):
            history.append(VoiceInteraction(
                id=f"int-{i}",
                user_speech=f"speech-{i}",
                response_text=f"response-{i}",
                audio_duration_ms=100,
                total_latency_ms=200,
                timestamp=time.time()
            ))

        # Should only have last 3
        assert len(history) == 3
        assert history[0].id == "int-2"
        assert history[-1].id == "int-4"


class TestSemanticCache:
    """Tests for semantic cache bounds."""

    def test_max_entries_enforced(self):
        """Test cache doesn't exceed max entries."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache(max_entries=5)

        # Add more than max
        for i in range(10):
            cache.put(f"query {i}", f"response {i}")

        assert len(cache._cache) <= 5

    def test_cache_uses_ordered_dict(self):
        """Test cache is OrderedDict for LRU eviction."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache()
        assert isinstance(cache._cache, OrderedDict)

    def test_total_audio_size_tracking(self):
        """Test total audio size is tracked."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache(max_entries=100)

        # Add entries with audio
        cache.put("query 1", "response 1", b"x" * 1000)
        cache.put("query 2", "response 2", b"y" * 2000)

        assert cache._total_audio_bytes == 3000

    def test_audio_size_limit_per_entry(self):
        """Test individual audio entries are size-limited."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache(max_entries=100)

        # Add entry with oversized audio
        cache.put("big query", "response", b"x" * 100_000)

        # Should not cache oversized audio
        entry = cache._cache.get(cache._normalize("big query"))
        assert entry.audio_data is None

    def test_lru_moves_accessed_to_end(self):
        """Test accessed entries are moved to end of OrderedDict."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache(max_entries=5, similarity_threshold=1.0)

        # Add entries
        cache.put("alpha", "response alpha")
        cache.put("beta", "response beta")
        cache.put("gamma", "response gamma")

        # Access alpha
        cache.get("alpha")

        # Alpha should now be at the end
        keys = list(cache._cache.keys())
        assert keys[-1] == cache._normalize("alpha")


class TestWebSocketManagerBounds:
    """Tests for WebSocket manager memory bounds."""

    def test_max_connections_enforced(self, temp_db):
        """Test connection count is bounded."""
        from src.avatar.websocket_manager import AvatarWebSocketManager

        manager = AvatarWebSocketManager(db_path=temp_db)

        # Add more connections than limit
        for i in range(manager.MAX_CONNECTIONS + 20):
            mock_ws = Mock()
            mock_ws.close = Mock()
            manager.register(f"bot-{i}", mock_ws)

        # Should be bounded
        assert len(manager._connections) <= manager.MAX_CONNECTIONS

    def test_max_mappings_enforced(self, temp_db):
        """Test ID mappings are bounded."""
        from src.avatar.websocket_manager import AvatarWebSocketManager

        manager = AvatarWebSocketManager(db_path=temp_db)

        # Add more mappings than limit (each mapping adds 2 entries: meeting->bot and bot->meeting)
        for i in range(manager.MAX_INMEMORY_MAPPINGS + 50):
            manager.add_id_mapping(f"meeting-{i}", f"bot-{i}")

        # Should be bounded
        assert len(manager._id_mappings) <= manager.MAX_INMEMORY_MAPPINGS

    def test_connections_use_ordered_dict(self, temp_db):
        """Test connections use OrderedDict for LRU eviction."""
        from src.avatar.websocket_manager import AvatarWebSocketManager

        manager = AvatarWebSocketManager(db_path=temp_db)
        assert isinstance(manager._connections, OrderedDict)

    def test_mappings_use_ordered_dict(self, temp_db):
        """Test ID mappings use OrderedDict for LRU eviction."""
        from src.avatar.websocket_manager import AvatarWebSocketManager

        manager = AvatarWebSocketManager(db_path=temp_db)
        assert isinstance(manager._id_mappings, OrderedDict)

    def test_stale_connection_cleanup(self, temp_db):
        """Test stale connections are cleaned up."""
        from src.avatar.websocket_manager import AvatarWebSocketManager, AvatarConnection

        manager = AvatarWebSocketManager(db_path=temp_db)

        # Register a connection
        mock_ws = Mock()
        mock_ws.close = Mock()
        manager.register("stale-bot", mock_ws)

        # Artificially age the connection
        with manager._lock:
            manager._connections["stale-bot"].last_ping = time.time() - 600  # 10 minutes ago

        # Trigger cleanup
        manager._cleanup_stale_connections()

        # Stale connection should be removed
        assert "stale-bot" not in manager._connections


class TestThreadSafety:
    """Tests for thread-safe operations."""

    def test_dedup_cache_thread_safety(self, app):
        """Test dedup cache handles concurrent access."""
        from src.bot.app import _message_dedup_cache, _is_duplicate_message

        _message_dedup_cache.clear()
        errors = []

        def writer():
            for i in range(100):
                try:
                    _is_duplicate_message(f"thread-msg-{threading.current_thread().name}-{i}")
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(4)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_semantic_cache_thread_safety(self):
        """Test semantic cache handles concurrent access."""
        from src.voice.voice_pipeline import SemanticCache

        cache = SemanticCache(max_entries=100)
        errors = []

        def writer():
            for i in range(50):
                try:
                    cache.put(f"query-{threading.current_thread().name}-{i}", f"response-{i}")
                except Exception as e:
                    errors.append(e)

        def reader():
            for i in range(50):
                try:
                    cache.get(f"query-{i}")
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
