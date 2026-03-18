"""
Tests for production configuration validation.

Ensures critical config errors prevent app startup in production mode.
"""
import pytest
from unittest.mock import MagicMock, patch
from flask import Flask

from src.bot.bootstrap import _validate_production_config, ConfigurationError


class TestProductionConfigValidation:
    """Tests for _validate_production_config() function."""

    @pytest.fixture
    def production_app(self):
        """Create a Flask app in production mode (debug=False, TESTING=False)."""
        app = Flask(__name__)
        app.debug = False
        app.config["TESTING"] = False
        return app

    @pytest.fixture
    def dev_app(self):
        """Create a Flask app in development mode (debug=True)."""
        app = Flask(__name__)
        app.debug = True
        return app

    @pytest.fixture
    def test_app(self):
        """Create a Flask app in test mode (TESTING=True)."""
        app = Flask(__name__)
        app.config["TESTING"] = True
        return app

    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return MagicMock()

    def test_raises_error_when_api_key_missing_in_production(self, production_app, mock_logger):
        """Test that missing API_KEY raises ConfigurationError in production."""
        production_app.config["ZOOM_BOT_SECRET"] = "secret"
        production_app.config["RECALL_TRANSCRIPTION_SECRET"] = "secret"
        # API_KEY is missing

        with pytest.raises(ConfigurationError) as exc_info:
            _validate_production_config(production_app, mock_logger)

        assert "API_KEY" in str(exc_info.value)
        assert "critical configuration error" in str(exc_info.value).lower()

    def test_raises_error_when_zoom_secret_missing_in_production(self, production_app, mock_logger):
        """Test that missing ZOOM_BOT_SECRET raises ConfigurationError in production."""
        production_app.config["API_KEY"] = "key"
        production_app.config["RECALL_TRANSCRIPTION_SECRET"] = "secret"
        # ZOOM_BOT_SECRET is missing

        with pytest.raises(ConfigurationError) as exc_info:
            _validate_production_config(production_app, mock_logger)

        assert "ZOOM_BOT_SECRET" in str(exc_info.value)

    def test_raises_error_when_recall_secret_missing_in_production(self, production_app, mock_logger):
        """Test that missing RECALL_TRANSCRIPTION_SECRET raises ConfigurationError."""
        production_app.config["API_KEY"] = "key"
        production_app.config["ZOOM_BOT_SECRET"] = "secret"
        # RECALL_TRANSCRIPTION_SECRET is missing

        with pytest.raises(ConfigurationError) as exc_info:
            _validate_production_config(production_app, mock_logger)

        assert "RECALL_TRANSCRIPTION_SECRET" in str(exc_info.value)

    def test_raises_error_with_multiple_critical_issues(self, production_app, mock_logger):
        """Test that multiple critical issues are reported together."""
        # All critical config missing

        with pytest.raises(ConfigurationError) as exc_info:
            _validate_production_config(production_app, mock_logger)

        error_msg = str(exc_info.value)
        assert "3 critical configuration error" in error_msg
        assert "API_KEY" in error_msg
        assert "ZOOM_BOT_SECRET" in error_msg
        assert "RECALL_TRANSCRIPTION_SECRET" in error_msg

    def test_returns_warnings_for_non_critical_config(self, production_app, mock_logger):
        """Test that non-critical missing config returns warnings, not errors."""
        # Set all critical config
        production_app.config["API_KEY"] = "key"
        production_app.config["ZOOM_BOT_SECRET"] = "secret"
        production_app.config["RECALL_TRANSCRIPTION_SECRET"] = "secret"
        # Leave non-critical config unset (GITHUB_TOKEN, OPENROUTER_API_KEY)

        warnings = _validate_production_config(production_app, mock_logger)

        assert len(warnings) == 2
        assert any("GITHUB_TOKEN" in w for w in warnings)
        assert any("OPENROUTER_API_KEY" in w for w in warnings)

    def test_no_validation_in_debug_mode(self, dev_app, mock_logger):
        """Test that validation is skipped in debug mode."""
        # All config missing, but debug mode should skip validation

        warnings = _validate_production_config(dev_app, mock_logger)

        assert warnings == []
        # No exception raised

    def test_no_validation_in_test_mode(self, test_app, mock_logger):
        """Test that validation is skipped in test mode."""
        # All config missing, but test mode should skip validation

        warnings = _validate_production_config(test_app, mock_logger)

        assert warnings == []
        # No exception raised

    def test_all_config_present_returns_empty_warnings(self, production_app, mock_logger):
        """Test that all config present returns no warnings."""
        production_app.config["API_KEY"] = "key"
        production_app.config["ZOOM_BOT_SECRET"] = "secret"
        production_app.config["RECALL_TRANSCRIPTION_SECRET"] = "secret"
        production_app.config["GITHUB_TOKEN"] = "token"
        production_app.config["OPENROUTER_API_KEY"] = "openrouter_key"

        warnings = _validate_production_config(production_app, mock_logger)

        assert warnings == []

    def test_logs_warnings_for_non_critical(self, production_app, mock_logger):
        """Test that warnings are logged for non-critical issues."""
        production_app.config["API_KEY"] = "key"
        production_app.config["ZOOM_BOT_SECRET"] = "secret"
        production_app.config["RECALL_TRANSCRIPTION_SECRET"] = "secret"
        # Leave GITHUB_TOKEN unset

        _validate_production_config(production_app, mock_logger)

        # Check that warning was logged
        mock_logger.warning.assert_called()
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("GITHUB_TOKEN" in str(c) for c in warning_calls)

    def test_logs_errors_before_raising(self, production_app, mock_logger):
        """Test that critical errors are logged before exception is raised."""
        # All critical config missing

        with pytest.raises(ConfigurationError):
            _validate_production_config(production_app, mock_logger)

        # Check that errors were logged
        mock_logger.error.assert_called()
        error_calls = [str(c) for c in mock_logger.error.call_args_list]
        assert any("API_KEY" in str(c) for c in error_calls)


class TestConfigurationError:
    """Tests for ConfigurationError exception class."""

    def test_configuration_error_is_exception(self):
        """Test that ConfigurationError is an Exception subclass."""
        assert issubclass(ConfigurationError, Exception)

    def test_configuration_error_message(self):
        """Test ConfigurationError can be raised with a message."""
        with pytest.raises(ConfigurationError) as exc_info:
            raise ConfigurationError("Missing critical config")

        assert "Missing critical config" in str(exc_info.value)
