"""
Tests for centralized timeout configuration.

Verifies that timeout tiers are properly configured and accessible.
"""
import pytest
import os
from unittest.mock import patch


class TestTimeoutConfig:
    """Tests for TimeoutConfig configuration."""

    def test_timeout_config_default_values(self):
        """Test TimeoutConfig has sensible defaults."""
        from src.bot.config import TimeoutConfig

        config = TimeoutConfig()

        # Tier 1: INSTANT
        assert config.instant == 2
        assert config.health_check == 2

        # Tier 2: FAST
        assert config.fast == 5
        assert config.llm_query == 5
        assert config.queue_operation == 0.5

        # Tier 3: NORMAL
        assert config.normal == 10
        assert config.zoom_api == 10
        assert config.github_user == 10
        assert config.websocket_receive == 10

        # Tier 4: SLOW
        assert config.slow == 30
        assert config.github_bulk == 30
        assert config.recall_api == 30
        assert config.n8n_workflow == 30
        assert config.tts_synthesis == 30
        assert config.video_generation == 30

        # Tier 5: EXTENDED
        assert config.extended == 60
        assert config.file_upload == 60
        assert config.meeting_wait == 120

        # Circuit breaker
        assert config.circuit_recovery == 60

    def test_timeout_config_from_env(self):
        """Test TimeoutConfig loads from environment variables."""
        from src.bot.config import TimeoutConfig

        env_vars = {
            "TIMEOUT_INSTANT": "3",
            "LLM_TIMEOUT": "8",
            "TIMEOUT_ZOOM_API": "15",
            "GITHUB_TIMEOUT": "45",
            "TIMEOUT_FILE_UPLOAD": "90",
        }

        with patch.dict(os.environ, env_vars):
            config = TimeoutConfig.from_env()

            assert config.instant == 3
            assert config.llm_query == 8
            assert config.zoom_api == 15
            assert config.github_bulk == 45
            assert config.file_upload == 90

    def test_timeout_hierarchy_ordering(self):
        """Test that timeout tiers are properly ordered."""
        from src.bot.config import TimeoutConfig

        config = TimeoutConfig()

        # Verify hierarchy: instant < fast < normal < slow < extended
        assert config.instant < config.fast
        assert config.fast < config.normal
        assert config.normal < config.slow
        assert config.slow < config.extended

    def test_timeout_config_in_global_config(self):
        """Test TimeoutConfig is accessible via global Config."""
        from src.bot.config import Config

        config = Config()
        assert hasattr(config, "timeout")
        assert config.timeout.instant == 2
        assert config.timeout.slow == 30

    def test_get_config_includes_timeout(self):
        """Test get_config() includes timeout configuration."""
        from src.bot.config import get_config

        # Reset the singleton to force reload
        import src.bot.config as config_module
        config_module._config = None

        config = get_config()
        assert config.timeout is not None
        assert config.timeout.llm_query == 5


class TestTimeoutUsageConsistency:
    """Tests to verify timeout values are used consistently."""

    def test_llm_config_uses_same_timeout(self):
        """Test LLM config timeout matches timeout hierarchy."""
        from src.bot.config import LLMConfig, TimeoutConfig

        llm_config = LLMConfig()
        timeout_config = TimeoutConfig()

        # LLM timeout should match the llm_query timeout in hierarchy
        assert llm_config.timeout_seconds == timeout_config.llm_query

    def test_github_config_uses_same_timeout(self):
        """Test GitHub config aligns with timeout hierarchy."""
        from src.bot.config import GitHubConfig, TimeoutConfig

        github_config = GitHubConfig()
        timeout_config = TimeoutConfig()

        # GitHub timeout should match github_user (normal tier) for user operations
        assert github_config.timeout_seconds == timeout_config.github_user
