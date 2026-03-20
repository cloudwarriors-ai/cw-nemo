"""Tests for wake word detector."""

import pytest
from src.meeting.wake_word_detector import WakeWordDetector


class TestWakeWordDetector:
    """Tests for WakeWordDetector class."""

    @pytest.fixture
    def detector(self):
        """Create detector instance."""
        return WakeWordDetector(bot_name="QA Bot")

    def test_exact_wake_word(self, detector):
        """Test exact wake word detection."""
        detected, query = detector.detect("qa bot what are the high priority issues", "User")
        assert detected is True
        assert query == "what are the high priority issues"

    def test_exact_wake_word_qabot(self, detector):
        """Test qabot variant."""
        detected, query = detector.detect("qabot show me bugs", "User")
        assert detected is True
        assert query == "show me bugs"

    def test_misrecognition_qa_about(self, detector):
        """Test common misrecognition 'qa about'."""
        detected, query = detector.detect("qa about the latest issues", "User")
        assert detected is True
        assert query == "the latest issues"

    def test_misrecognition_queba(self, detector):
        """Test phonetic misrecognition 'queba'."""
        detected, query = detector.detect("queba list all bugs", "User")
        assert detected is True
        assert query == "list all bugs"

    def test_no_wake_word(self, detector):
        """Test no detection without wake word."""
        detected, query = detector.detect("what are the high priority issues", "User")
        assert detected is False
        assert query == ""

    def test_ignores_bot_speaker(self, detector):
        """Test bot speaker is ignored."""
        detected, query = detector.detect("qa bot what are issues", "QA Bot")
        assert detected is False
        assert query == ""

    def test_ignores_qabot_speaker(self, detector):
        """Test qabot speaker variant is ignored."""
        detected, query = detector.detect("qa bot hello", "qabot")
        assert detected is False
        assert query == ""

    def test_query_too_short(self, detector):
        """Test query must be at least 3 characters."""
        detected, query = detector.detect("qa bot hi", "User")
        assert detected is False
        assert query == ""

    def test_soundex(self, detector):
        """Test Soundex encoding."""
        assert WakeWordDetector.soundex("qabot") == "Q130"
        assert WakeWordDetector.soundex("queba") == "Q100"
        assert WakeWordDetector.soundex("robert") == "R163"
        assert WakeWordDetector.soundex("rupert") == "R163"

    def test_levenshtein(self, detector):
        """Test Levenshtein distance calculation."""
        assert WakeWordDetector.levenshtein_distance("qabot", "qabot") == 0
        assert WakeWordDetector.levenshtein_distance("qabot", "qabotx") == 1
        assert WakeWordDetector.levenshtein_distance("qabot", "qaba") == 2
        assert WakeWordDetector.levenshtein_distance("qabot", "xyz") == 5

    def test_fuzzy_match(self, detector):
        """Test fuzzy matching."""
        assert detector.fuzzy_match("qabot") is True
        assert detector.fuzzy_match("qabat") is True  # 1 edit
        assert detector.fuzzy_match("qaba") is True  # 2 edits
        assert detector.fuzzy_match("xyz") is False

    def test_fuzzy_match_too_short(self, detector):
        """Test fuzzy match rejects very short words."""
        assert detector.fuzzy_match("qa") is False

    def test_fuzzy_match_too_long(self, detector):
        """Test fuzzy match rejects very long words."""
        assert detector.fuzzy_match("qabotqabotqabot") is False

    def test_is_bot_speaker(self, detector):
        """Test bot speaker detection."""
        assert detector.is_bot_speaker("QA Bot") is True
        assert detector.is_bot_speaker("qa bot") is True
        assert detector.is_bot_speaker("qabot") is True
        assert detector.is_bot_speaker("User") is False

    def test_hey_prefix(self, detector):
        """Test 'hey qa bot' variant."""
        detected, query = detector.detect("hey qa bot what is the status", "User")
        assert detected is True
        assert query == "what is the status"

    def test_combined_first_words(self, detector):
        """Test detection of combined first two words."""
        # This should fuzzy-match "cueabot" or similar combinations
        detected, query = detector.detect("cue a bot show issues", "User")
        assert detected is True
