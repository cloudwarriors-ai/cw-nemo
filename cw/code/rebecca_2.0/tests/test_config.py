"""
Tests for configuration module.

Tests config loading from environment variables and default values.
"""
import os
import pytest
from unittest.mock import patch

from src.bot.config import (
    Config,
    LLMConfig,
    CacheConfig,
    RateLimitConfig,
    InputSanitizationConfig,
    DeduplicationConfig,
    CircuitBreakerConfig,
    MeetingConfig,
    LoggingConfig,
    GitHubConfig,
    get_config,
    reset_config,
    HttpStatus,
    BOT_MENTIONS,
)


class TestLLMConfig:
    """Tests for LLM configuration."""

    def test_default_values(self):
        """Test default configuration values."""
        config = LLMConfig()
        assert config.api_key == ""
        assert config.model == "anthropic/claude-haiku-4.5"
        assert config.timeout_seconds == 5
        assert config.max_retries == 2
        assert config.retry_backoff_factor == 0.5
        assert config.max_tokens == 500
        assert config.temperature == 0.3
        assert config.max_repos_in_prompt == 20

    def test_from_env(self):
        """Test loading config from environment variables."""
        env_vars = {
            "OPENROUTER_API_KEY": "test-key",
            "MODEL": "test-model",
            "LLM_TIMEOUT": "10",
            "LLM_MAX_RETRIES": "5",
            "LLM_RETRY_BACKOFF": "1.0",
            "LLM_MAX_TOKENS": "1000",
            "LLM_TEMPERATURE": "0.7",
            "LLM_MAX_REPOS_IN_PROMPT": "50",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            config = LLMConfig.from_env()
            assert config.api_key == "test-key"
            assert config.model == "test-model"
            assert config.timeout_seconds == 10
            assert config.max_retries == 5
            assert config.retry_backoff_factor == 1.0
            assert config.max_tokens == 1000
            assert config.temperature == 0.7
            assert config.max_repos_in_prompt == 50


class TestCacheConfig:
    """Tests for cache configuration."""

    def test_default_values(self):
        """Test default cache configuration."""
        config = CacheConfig()
        assert config.ttl_seconds == 60
        assert config.stale_days == 14

    def test_from_env(self):
        """Test loading cache config from environment."""
        env_vars = {"CACHE_TTL": "120", "STALE_DAYS": "7"}
        with patch.dict(os.environ, env_vars, clear=False):
            config = CacheConfig.from_env()
            assert config.ttl_seconds == 120
            assert config.stale_days == 7


class TestRateLimitConfig:
    """Tests for rate limit configuration."""

    def test_default_values(self):
        """Test default rate limits."""
        config = RateLimitConfig()
        assert config.chat_requests_per_hour == 20
        assert config.meeting_joins_per_hour == 5

    def test_from_env(self):
        """Test loading rate limits from environment."""
        env_vars = {"RATE_LIMIT": "100", "MEETING_RATE_LIMIT": "10"}
        with patch.dict(os.environ, env_vars, clear=False):
            config = RateLimitConfig.from_env()
            assert config.chat_requests_per_hour == 100
            assert config.meeting_joins_per_hour == 10


class TestInputSanitizationConfig:
    """Tests for input sanitization configuration."""

    def test_default_values(self):
        """Test default input limits."""
        config = InputSanitizationConfig()
        assert config.max_input_length == 500
        assert config.max_response_length == 4000
        assert config.max_username_length == 50


class TestDeduplicationConfig:
    """Tests for deduplication configuration."""

    def test_default_values(self):
        """Test default deduplication TTL."""
        config = DeduplicationConfig()
        assert config.ttl_seconds == 60


class TestCircuitBreakerConfig:
    """Tests for circuit breaker configuration."""

    def test_default_values(self):
        """Test default circuit breaker settings."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.recovery_timeout_seconds == 30
        assert config.half_open_requests == 1


class TestMeetingConfig:
    """Tests for meeting configuration."""

    def test_default_values(self):
        """Test default meeting cleanup settings."""
        config = MeetingConfig()
        assert config.cleanup_stale_minutes == 30
        assert config.cleanup_old_days == 30


class TestLoggingConfig:
    """Tests for logging configuration."""

    def test_default_values(self):
        """Test default logging settings."""
        config = LoggingConfig()
        assert config.error_truncate_length == 200
        assert config.query_log_length == 100
        assert config.request_id_length == 8


class TestGitHubConfig:
    """Tests for GitHub configuration."""

    def test_default_values(self):
        """Test default GitHub API settings."""
        config = GitHubConfig()
        assert config.timeout_seconds == 10
        assert config.max_retries == 3
        assert config.retry_backoff_factor == 0.5


class TestMasterConfig:
    """Tests for master Config class."""

    def test_default_creates_all_subconfigs(self):
        """Test that default Config creates all sub-configurations."""
        config = Config()
        assert isinstance(config.llm, LLMConfig)
        assert isinstance(config.cache, CacheConfig)
        assert isinstance(config.rate_limit, RateLimitConfig)
        assert isinstance(config.input, InputSanitizationConfig)
        assert isinstance(config.dedup, DeduplicationConfig)
        assert isinstance(config.circuit_breaker, CircuitBreakerConfig)
        assert isinstance(config.meeting, MeetingConfig)
        assert isinstance(config.logging, LoggingConfig)
        assert isinstance(config.github, GitHubConfig)

    def test_from_env_loads_all(self):
        """Test that from_env loads all sub-configurations."""
        config = Config.from_env()
        # Just verify it creates valid config objects
        assert config.llm.timeout_seconds > 0
        assert config.cache.ttl_seconds > 0


class TestConfigSingleton:
    """Tests for config singleton behavior."""

    def test_get_config_returns_same_instance(self):
        """Test that get_config returns singleton."""
        reset_config()  # Clear any existing config
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2

    def test_reset_config_clears_singleton(self):
        """Test that reset_config clears the singleton."""
        config1 = get_config()
        reset_config()
        config2 = get_config()
        assert config1 is not config2


class TestHttpStatus:
    """Tests for HTTP status constants."""

    def test_status_values(self):
        """Test HTTP status values are correct."""
        assert HttpStatus.OK == 200
        assert HttpStatus.CREATED == 201
        assert HttpStatus.BAD_REQUEST == 400
        assert HttpStatus.UNAUTHORIZED == 401
        assert HttpStatus.NOT_FOUND == 404
        assert HttpStatus.TOO_MANY_REQUESTS == 429
        assert HttpStatus.INTERNAL_ERROR == 500
        assert HttpStatus.SERVICE_UNAVAILABLE == 503


class TestBotMentions:
    """Tests for bot mention prefixes."""

    def test_bot_mentions_defined(self):
        """Test that bot mentions are defined."""
        assert "@qabot" in BOT_MENTIONS
        assert "@qa-bot" in BOT_MENTIONS
        assert "@qa_bot" in BOT_MENTIONS
