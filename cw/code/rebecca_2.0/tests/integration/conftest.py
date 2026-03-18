"""
Integration test configuration and fixtures.

These tests require real API credentials to run.
They are skipped by default unless credentials are available.

Run with: pytest tests/integration/ -v
"""
import os
import pytest
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires real API)"
    )
    config.addinivalue_line(
        "markers", "github: mark test as requiring GitHub API"
    )
    config.addinivalue_line(
        "markers", "recall: mark test as requiring Recall.ai API"
    )
    config.addinivalue_line(
        "markers", "simli: mark test as requiring Simli API"
    )
    config.addinivalue_line(
        "markers", "cartesia: mark test as requiring Cartesia API"
    )


# ============================================================================
# Skip conditions
# ============================================================================

def has_github_token():
    """Check if GitHub token is available."""
    token = os.getenv("GITHUB_TOKEN", "")
    return bool(token) and not token.startswith("ghp_xxx")


def has_recall_api_key():
    """Check if Recall.ai API key is available."""
    key = os.getenv("RECALL_API_KEY", "")
    return bool(key) and key != "xxxxxxxx"


def has_simli_api_key():
    """Check if Simli API key is available."""
    key = os.getenv("SIMLI_API_KEY", "")
    return bool(key) and key != "xxxxxxxx"


def has_cartesia_api_key():
    """Check if Cartesia API key is available."""
    key = os.getenv("CARTESIA_API_KEY", "")
    return bool(key) and key != "xxxxxxxx"


def has_openai_api_key():
    """Check if OpenAI API key is available."""
    key = os.getenv("OPENAI_API_KEY", "")
    return bool(key) and not key.startswith("sk-xxx")


# Skip decorators
skip_without_github = pytest.mark.skipif(
    not has_github_token(),
    reason="GITHUB_TOKEN not configured"
)

skip_without_recall = pytest.mark.skipif(
    not has_recall_api_key(),
    reason="RECALL_API_KEY not configured"
)

skip_without_simli = pytest.mark.skipif(
    not has_simli_api_key(),
    reason="SIMLI_API_KEY not configured"
)

skip_without_cartesia = pytest.mark.skipif(
    not has_cartesia_api_key(),
    reason="CARTESIA_API_KEY not configured"
)

skip_without_openai = pytest.mark.skipif(
    not has_openai_api_key(),
    reason="OPENAI_API_KEY not configured"
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def github_token():
    """Get GitHub token for testing."""
    return os.getenv("GITHUB_TOKEN")


@pytest.fixture
def github_org():
    """Get GitHub org for testing."""
    return os.getenv("GITHUB_ORG", "cloudwarriors-ai")


@pytest.fixture
def recall_api_key():
    """Get Recall.ai API key for testing."""
    return os.getenv("RECALL_API_KEY")


@pytest.fixture
def simli_api_key():
    """Get Simli API key for testing."""
    return os.getenv("SIMLI_API_KEY")


@pytest.fixture
def cartesia_api_key():
    """Get Cartesia API key for testing."""
    return os.getenv("CARTESIA_API_KEY")


@pytest.fixture
def openai_api_key():
    """Get OpenAI API key for testing."""
    return os.getenv("OPENAI_API_KEY")


@pytest.fixture
def integration_app():
    """Create Flask app with real configuration for integration testing."""
    from src.bot.app import create_app

    app = create_app({
        "TESTING": True,
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN"),
        "GITHUB_ORG": os.getenv("GITHUB_ORG", "cloudwarriors-ai"),
        "RECALL_API_KEY": os.getenv("RECALL_API_KEY"),
        "SIMLI_API_KEY": os.getenv("SIMLI_API_KEY"),
        "CARTESIA_API_KEY": os.getenv("CARTESIA_API_KEY"),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
    })

    return app


@pytest.fixture
def integration_client(integration_app):
    """Create test client with real API configuration."""
    with integration_app.test_client() as client:
        yield client


# ============================================================================
# Meta-tests for skip decorators (verify they work correctly)
# ============================================================================

class TestSkipDecoratorLogic:
    """
    Meta-tests to verify skip decorator logic is correct.

    These tests run unconditionally to verify that the skip
    conditions themselves are implemented correctly.
    """

    def test_has_github_token_rejects_placeholder(self):
        """Test that placeholder tokens are rejected."""
        original = os.environ.get("GITHUB_TOKEN")
        try:
            os.environ["GITHUB_TOKEN"] = "ghp_xxxxxxxxxxxx"
            assert has_github_token() is False

            os.environ["GITHUB_TOKEN"] = ""
            assert has_github_token() is False
        finally:
            if original:
                os.environ["GITHUB_TOKEN"] = original
            elif "GITHUB_TOKEN" in os.environ:
                del os.environ["GITHUB_TOKEN"]

    def test_has_recall_api_key_rejects_placeholder(self):
        """Test that placeholder keys are rejected."""
        original = os.environ.get("RECALL_API_KEY")
        try:
            os.environ["RECALL_API_KEY"] = "xxxxxxxx"
            assert has_recall_api_key() is False

            os.environ["RECALL_API_KEY"] = ""
            assert has_recall_api_key() is False
        finally:
            if original:
                os.environ["RECALL_API_KEY"] = original
            elif "RECALL_API_KEY" in os.environ:
                del os.environ["RECALL_API_KEY"]

    def test_has_openai_api_key_rejects_placeholder(self):
        """Test that placeholder keys are rejected."""
        original = os.environ.get("OPENAI_API_KEY")
        try:
            os.environ["OPENAI_API_KEY"] = "sk-xxxxxxxxxxxx"
            assert has_openai_api_key() is False

            os.environ["OPENAI_API_KEY"] = ""
            assert has_openai_api_key() is False
        finally:
            if original:
                os.environ["OPENAI_API_KEY"] = original
            elif "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]

    def test_skip_decorators_are_pytest_marks(self):
        """Test that skip decorators are valid pytest marks."""
        assert hasattr(skip_without_github, 'mark')
        assert hasattr(skip_without_recall, 'mark')
        assert hasattr(skip_without_simli, 'mark')
        assert hasattr(skip_without_cartesia, 'mark')
        assert hasattr(skip_without_openai, 'mark')
