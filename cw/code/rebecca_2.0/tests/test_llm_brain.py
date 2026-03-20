"""
Unit tests for LLM Brain module.

Tests security-critical functions like sensitive topic detection,
JSON parsing, and error sanitization.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import json

from src.bot.llm_brain import QABrain, Capability, ChatResponse, WorkflowResponse
from src.bot.prompts import SENSITIVE_TOPICS, HELP_RESPONSE


class TestSensitiveTopicDetection:
    """Tests for _contains_sensitive_topic() - security critical."""

    @pytest.fixture
    def brain(self):
        """Create a QABrain instance for testing."""
        with patch('src.bot.llm_brain.requests.Session'):
            return QABrain(
                api_key="test-key",
                model="test-model",
                repos=["test-repo"],
                logger=Mock()
            )

    def test_detects_performance_review(self, brain):
        """Should detect 'performance review' as sensitive."""
        assert brain._contains_sensitive_topic("I need a performance review")
        assert brain._contains_sensitive_topic("What about my performance review?")

    def test_detects_termination(self, brain):
        """Should detect termination-related words."""
        assert brain._contains_sensitive_topic("Is John getting fired?")
        assert brain._contains_sensitive_topic("termination process")

    def test_detects_salary(self, brain):
        """Should detect salary/compensation topics."""
        assert brain._contains_sensitive_topic("What's my salary?")
        assert brain._contains_sensitive_topic("compensation discussion")
        assert brain._contains_sensitive_topic("I want a raise")

    def test_detects_harassment(self, brain):
        """Should detect harassment/discrimination."""
        assert brain._contains_sensitive_topic("harassment complaint")
        assert brain._contains_sensitive_topic("discrimination issue")

    def test_word_boundaries_prevent_false_positives(self, brain):
        """Should NOT match partial words (e.g., 'decompensation')."""
        # 'compensation' is sensitive, but 'decompensation' (medical term) is not
        assert not brain._contains_sensitive_topic("cardiac decompensation")
        # 'personal' is sensitive, but 'personality' is not
        assert not brain._contains_sensitive_topic("personality test")

    def test_case_insensitive(self, brain):
        """Should match regardless of case."""
        assert brain._contains_sensitive_topic("PERFORMANCE REVIEW")
        assert brain._contains_sensitive_topic("Salary Discussion")
        assert brain._contains_sensitive_topic("HARASSMENT")

    def test_normal_queries_not_flagged(self, brain):
        """Normal QA queries should not be flagged as sensitive."""
        assert not brain._contains_sensitive_topic("high priority issues")
        assert not brain._contains_sensitive_topic("tell me about hermes")
        assert not brain._contains_sensitive_topic("summary")
        assert not brain._contains_sensitive_topic("unassigned bugs")


class TestJsonParsing:
    """Tests for _parse_json_response() - handles LLM output parsing."""

    @pytest.fixture
    def brain(self):
        """Create a QABrain instance for testing."""
        with patch('src.bot.llm_brain.requests.Session'):
            return QABrain(
                api_key="test-key",
                model="test-model",
                repos=[],
                logger=Mock()
            )

    def test_parses_clean_json(self, brain):
        """Should parse clean JSON."""
        result = brain._parse_json_response('{"intent": "issue_query", "filters": {}}')
        assert result == {"intent": "issue_query", "filters": {}}

    def test_parses_json_in_markdown_block(self, brain):
        """Should extract JSON from markdown code blocks."""
        text = '''```json
{"intent": "repo_info", "filters": {"repo": "hermes"}}
```'''
        result = brain._parse_json_response(text)
        assert result == {"intent": "repo_info", "filters": {"repo": "hermes"}}

    def test_parses_json_in_plain_markdown_block(self, brain):
        """Should extract JSON from plain markdown blocks."""
        text = '''```
{"intent": "help"}
```'''
        result = brain._parse_json_response(text)
        assert result == {"intent": "help"}

    def test_handles_malformed_json(self, brain):
        """Should return None for malformed JSON."""
        result = brain._parse_json_response("not json at all")
        assert result is None

    def test_extracts_json_from_mixed_text(self, brain):
        """Should find JSON embedded in other text."""
        text = 'Here is the response: {"intent": "general"} hope that helps!'
        result = brain._parse_json_response(text)
        assert result == {"intent": "general"}

    def test_handles_empty_string(self, brain):
        """Should handle empty input."""
        result = brain._parse_json_response("")
        assert result is None

    def test_handles_whitespace_only(self, brain):
        """Should handle whitespace-only input."""
        result = brain._parse_json_response("   \n\t  ")
        assert result is None


class TestErrorSanitization:
    """Tests for _sanitize_error_response() - prevents secret leakage."""

    @pytest.fixture
    def brain(self):
        """Create a QABrain instance for testing."""
        with patch('src.bot.llm_brain.requests.Session'):
            return QABrain(
                api_key="test-key",
                model="test-model",
                repos=[],
                logger=Mock()
            )

    def test_extracts_safe_fields_from_json_error(self, brain):
        """Should only include safe fields from JSON errors."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "error": "rate_limit_exceeded",
            "message": "Too many requests",
            "code": 429,
            "secret_key": "sk-should-not-appear",
            "internal_data": {"password": "secret123"}
        }
        mock_response.text = "raw text"

        result = brain._sanitize_error_response(mock_response)
        parsed = json.loads(result)

        assert "error" in parsed
        assert "message" in parsed
        assert "code" in parsed
        assert "secret_key" not in parsed
        assert "internal_data" not in parsed

    def test_redacts_api_keys_from_text(self, brain):
        """Should redact API keys from raw text."""
        mock_response = Mock()
        mock_response.json.side_effect = json.JSONDecodeError("", "", 0)
        # Key must be long enough (20+ chars after sk-) to match redaction pattern
        mock_response.text = "Error with key sk-or-v1-fakeTESTplaceholder failed"

        result = brain._sanitize_error_response(mock_response)

        assert "sk-or-v1-fakeTESTplaceholder" not in result
        assert "[REDACTED]" in result

    def test_redacts_bearer_tokens(self, brain):
        """Should redact Bearer tokens."""
        mock_response = Mock()
        mock_response.json.side_effect = json.JSONDecodeError("", "", 0)
        # Bearer token must be long enough (20+ chars) to match redaction pattern
        mock_response.text = "Authorization: Bearer abc123xyz789def456ghi012jkl invalid"

        result = brain._sanitize_error_response(mock_response)

        assert "abc123xyz789def456ghi012jkl" not in result
        assert "[REDACTED]" in result

    def test_truncates_long_responses(self, brain):
        """Should truncate very long error responses."""
        mock_response = Mock()
        mock_response.json.side_effect = json.JSONDecodeError("", "", 0)
        mock_response.text = "x" * 500  # 500 chars

        result = brain._sanitize_error_response(mock_response)

        assert len(result) <= 200


class TestCapabilityMapping:
    """Tests for _map_intent_to_capability()."""

    @pytest.fixture
    def brain(self):
        """Create a QABrain instance for testing."""
        with patch('src.bot.llm_brain.requests.Session'):
            return QABrain(
                api_key="test-key",
                model="test-model",
                repos=[],
                logger=Mock()
            )

    def test_maps_known_intents(self, brain):
        """Should map known intents to capabilities."""
        assert brain._map_intent_to_capability("issue_query") == Capability.ISSUE_QUERY
        assert brain._map_intent_to_capability("repo_info") == Capability.REPO_INFO
        assert brain._map_intent_to_capability("help") == Capability.HELP
        assert brain._map_intent_to_capability("escalate") == Capability.ESCALATE
        assert brain._map_intent_to_capability("general") == Capability.GENERAL

    def test_unknown_intent_returns_unknown(self, brain):
        """Should return UNKNOWN for unrecognized intents."""
        assert brain._map_intent_to_capability("foo") == Capability.UNKNOWN
        assert brain._map_intent_to_capability("") == Capability.UNKNOWN
        assert brain._map_intent_to_capability("random") == Capability.UNKNOWN


class TestChatQueryHelp:
    """Tests for help command handling."""

    @pytest.fixture
    def brain(self):
        """Create a QABrain instance for testing."""
        with patch('src.bot.llm_brain.requests.Session'):
            return QABrain(
                api_key="test-key",
                model="test-model",
                repos=["repo1", "repo2"],
                logger=Mock()
            )

    def test_help_returns_help_response(self, brain):
        """Explicit help command should return help text."""
        result = brain.chat_query("help")
        assert result.capability == Capability.HELP
        assert result.confidence == 1.0
        assert "QA Bot Help" in result.response

    def test_question_mark_returns_help(self, brain):
        """Question mark should return help."""
        result = brain.chat_query("?")
        assert result.capability == Capability.HELP

    def test_commands_returns_help(self, brain):
        """'commands' should return help."""
        result = brain.chat_query("commands")
        assert result.capability == Capability.HELP


class TestChatQuerySensitiveEscalation:
    """Tests for automatic escalation of sensitive topics."""

    @pytest.fixture
    def brain(self):
        """Create a QABrain instance for testing."""
        with patch('src.bot.llm_brain.requests.Session'):
            return QABrain(
                api_key="test-key",
                model="test-model",
                repos=[],
                logger=Mock()
            )

    def test_sensitive_topic_escalates(self, brain):
        """Sensitive topics should trigger escalation."""
        result = brain.chat_query("I want to discuss my salary")
        assert result.capability == Capability.ESCALATE
        assert result.confidence == 1.0

    def test_escalation_message_mentions_chad(self, brain):
        """Escalation response should mention handoff."""
        result = brain.chat_query("harassment complaint")
        assert "Chad" in result.response or "escalate" in result.response.lower()
