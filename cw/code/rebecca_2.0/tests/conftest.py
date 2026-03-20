"""
Pytest configuration and fixtures for QA Bot tests.
"""
import os
import tempfile
import pytest

# Set test environment before imports
os.environ["TESTING"] = "true"
os.environ["ZOOM_BOT_VERIFICATION_TOKEN"] = "test-token"
os.environ["GITHUB_TOKEN"] = ""  # Disable GitHub in tests
os.environ["REPOS"] = ""

# API key for authenticated endpoints - use from .env or generate test key
TEST_API_KEY = os.environ.get("API_KEY", "test-api-key-for-testing")
os.environ["API_KEY"] = TEST_API_KEY


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Initialize the database
    from src.bot.database import init_db
    init_db(db_path)

    yield db_path

    # Cleanup
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def app(temp_db):
    """Create a test Flask application."""
    os.environ["DB_PATH"] = temp_db

    from src.bot.app import create_app
    app = create_app({"TESTING": True})
    app.config["DB_PATH"] = temp_db

    yield app


@pytest.fixture
def client(app):
    """Create a test client for the Flask application."""
    return app.test_client()


@pytest.fixture
def api_key():
    """Return the test API key for authenticated requests."""
    return TEST_API_KEY


@pytest.fixture
def auth_headers():
    """Return headers with API key for authenticated requests."""
    return {
        "Content-Type": "application/json",
        "X-API-Key": TEST_API_KEY
    }


@pytest.fixture
def query_parser():
    """Create a QueryParser instance for testing."""
    from src.bot.query_parser import QueryParser
    return QueryParser()


@pytest.fixture
def response_builder():
    """Create a ResponseBuilder instance for testing."""
    from src.bot.response_builder import ResponseBuilder
    return ResponseBuilder()


@pytest.fixture
def sample_issues():
    """Create sample Issue objects for testing."""
    from src.github_client import Issue

    return [
        Issue(
            repo="pulse",
            number=42,
            title="Fix authentication timeout",
            assignee="alice",
            labels=["priority/high", "type/bug"],
            priority="high",
            status=None,
            issue_type="bug",
            url="https://github.com/org/pulse/issues/42",
            updated="2024-01-01",
            created="2024-01-01",
            is_stale=False,
        ),
        Issue(
            repo="pulse",
            number=43,
            title="Update documentation",
            assignee=None,
            labels=["type/docs"],
            priority=None,
            status=None,
            issue_type="docs",
            url="https://github.com/org/pulse/issues/43",
            updated="2023-12-01",
            created="2023-12-01",
            is_stale=True,
        ),
        Issue(
            repo="macd",
            number=15,
            title="Database migration issue",
            assignee="bob",
            labels=["priority/high", "status/in-progress"],
            priority="high",
            status="in-progress",
            issue_type=None,
            url="https://github.com/org/macd/issues/15",
            updated="2024-01-05",
            created="2024-01-05",
            is_stale=False,
        ),
    ]
