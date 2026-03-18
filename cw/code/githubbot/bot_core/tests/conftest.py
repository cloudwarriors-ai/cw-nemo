"""
Pytest configuration and fixtures for bot_core tests.

This module provides:
- Django test database configuration
- Mock fixtures for external services (GitHub, Zoom, OpenAI)
- Common test data factories
"""
import os
import sys
import json
import hmac
import hashlib
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch, AsyncMock

import pytest
from django.test import AsyncClient
from django.utils import timezone
from asgiref.sync import sync_to_async

# Ensure Django settings are configured for tests
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'github_bot_project.settings')

# Note: We use actual settings from .env for tests since pytest-django loads Django
# before conftest.py runs. Tests use generate_github_signature() which reads from
# settings.GITHUB_WEBHOOK_SECRET to ensure signatures match.


# pytest-django handles database setup automatically via @pytest.mark.django_db
# No need for custom django_db_setup fixture


@pytest.fixture
def async_client():
    """Provide an async Django test client."""
    return AsyncClient()


# ==================== Settings Fixtures ====================

# Note: We use the actual GITHUB_WEBHOOK_SECRET from settings for tests
# to ensure signature verification works correctly with Django's async test client


# ==================== Mock Fixtures ====================

@pytest.fixture
def mock_github_bot():
    """Mock GitHubBot for testing without hitting GitHub API."""
    with patch('bot_core.github_bot.github_bot') as mock:
        mock.enabled = True
        mock.create_issue = Mock(return_value=(123, 'https://github.com/test/repo/issues/123'))
        mock.validate_repo_access = Mock(return_value=True)
        yield mock


@pytest.fixture
def mock_zoom_bot():
    """Mock ZoomChatBot for testing without hitting Zoom API."""
    with patch('bot_core.zoom_bot.zoom_bot') as mock:
        mock.send_message = Mock(return_value={'success': True})
        mock.send_message_to_devops = Mock(return_value={'success': True})
        mock.channel_id = 'test-channel-id'
        mock.prod_channel_id = 'test-prod-channel-id'
        yield mock


@pytest.fixture
def mock_llm_bot():
    """Mock LLMBot for testing without hitting OpenAI API."""
    with patch('bot_core.llm_bot.llm_bot') as mock:
        mock.generate_response = Mock(return_value="Test AI response")
        yield mock


@pytest.fixture
def mock_issue_maker_bot():
    """Mock ZoomIssueMakerBot for testing."""
    with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock:
        mock.enabled = True
        mock.send_message = Mock(return_value={'success': True})
        mock.delete_message = Mock(return_value=True)
        yield mock


@pytest.fixture
def mock_channel_layer():
    """Mock Django Channels layer for WebSocket testing."""
    with patch('bot_core.api.github_webhook.get_channel_layer') as mock:
        layer = AsyncMock()
        layer.group_send = AsyncMock()
        mock.return_value = layer
        yield layer


# ==================== Test Data Factories ====================

def generate_github_signature(payload: bytes, secret: str = None) -> str:
    """Generate a valid GitHub webhook signature for testing.

    Uses the actual GITHUB_WEBHOOK_SECRET from settings if no secret provided.
    """
    if secret is None:
        from django.conf import settings
        secret = settings.GITHUB_WEBHOOK_SECRET
    signature = hmac.new(
        key=secret.encode('utf-8'),
        msg=payload,
        digestmod=hashlib.sha256
    ).hexdigest()
    return f'sha256={signature}'


@pytest.fixture
def github_push_payload():
    """Sample GitHub push event payload."""
    return {
        'ref': 'refs/heads/main',
        'before': 'abc123',
        'after': 'def456',
        'repository': {
            'id': 12345,
            'full_name': 'test-org/test-repo',
            'html_url': 'https://github.com/test-org/test-repo'
        },
        'sender': {
            'login': 'test-user',
            'avatar_url': 'https://github.com/test-user.png'
        },
        'commits': [
            {
                'id': 'def456',
                'message': 'Test commit message',
                'author': {'name': 'Test User', 'email': 'test@example.com'}
            }
        ],
        'compare': 'https://github.com/test-org/test-repo/compare/abc123...def456'
    }


@pytest.fixture
def github_pr_payload():
    """Sample GitHub pull request event payload."""
    return {
        'action': 'opened',
        'number': 42,
        'pull_request': {
            'id': 98765,
            'number': 42,
            'title': 'Test PR Title',
            'body': 'Test PR description',
            'html_url': 'https://github.com/test-org/test-repo/pull/42',
            'user': {'login': 'test-user'}
        },
        'repository': {
            'id': 12345,
            'full_name': 'test-org/test-repo'
        },
        'sender': {
            'login': 'test-user',
            'avatar_url': 'https://github.com/test-user.png'
        }
    }


@pytest.fixture
def github_issue_payload():
    """Sample GitHub issue event payload."""
    return {
        'action': 'opened',
        'issue': {
            'id': 11111,
            'number': 99,
            'title': 'Test Issue Title',
            'body': 'Test issue description',
            'html_url': 'https://github.com/test-org/test-repo/issues/99',
            'labels': [],
            'state': 'open'
        },
        'repository': {
            'id': 12345,
            'full_name': 'test-org/test-repo'
        },
        'sender': {
            'login': 'test-user',
            'avatar_url': 'https://github.com/test-user.png'
        }
    }


@pytest.fixture
def github_issue_labeled_payload():
    """Sample GitHub issue labeled event payload."""
    return {
        'action': 'labeled',
        'issue': {
            'id': 11111,
            'number': 99,
            'title': 'Test Issue Title',
            'body': 'Test issue description',
            'html_url': 'https://github.com/test-org/test-repo/issues/99',
            'labels': [{'name': 'in-progress'}],
            'state': 'open'
        },
        'label': {
            'name': 'in-progress'
        },
        'repository': {
            'id': 12345,
            'full_name': 'test-org/test-repo'
        },
        'sender': {
            'login': 'test-user',
            'avatar_url': 'https://github.com/test-user.png'
        }
    }


@pytest.fixture
def github_issue_comment_payload():
    """Sample GitHub issue comment event payload."""
    return {
        'action': 'created',
        'issue': {
            'number': 99,
            'title': 'Test Issue Title',
            'html_url': 'https://github.com/test-org/test-repo/issues/99'
        },
        'comment': {
            'id': 22222,
            'body': 'Test comment body',
            'html_url': 'https://github.com/test-org/test-repo/issues/99#issuecomment-22222',
            'user': {'login': 'test-user'}
        },
        'repository': {
            'id': 12345,
            'full_name': 'test-org/test-repo'
        },
        'sender': {
            'login': 'test-user',
            'avatar_url': 'https://github.com/test-user.png'
        }
    }


@pytest.fixture
def zoom_command_payload():
    """Sample Zoom slash command payload."""
    def _make_payload(command: str):
        return {
            'payload': {
                'userJid': 'test-user-jid',
                'userName': 'Test User',
                'toJid': 'test-channel-jid',
                'robotJid': 'test-robot-jid',
                'accountId': 'test-account-id',
                'cmd': command
            }
        }
    return _make_payload


@pytest.fixture
def zoom_button_click_payload():
    """Sample Zoom button click payload."""
    def _make_payload(action_value: str, form_data: dict = None):
        payload = {
            'payload': {
                'userJid': 'test-user-jid',
                'userName': 'Test User',
                'toJid': 'test-channel-jid',
                'robotJid': 'test-robot-jid',
                'messageId': 'test-message-id',
                'actionItem': {
                    'value': action_value
                },
                'original': {
                    'body': []
                }
            }
        }
        if form_data:
            payload['payload']['original']['body'].append({
                'type': 'fields',
                'items': [{'key': k, 'value': v} for k, v in form_data.items()]
            })
        return payload
    return _make_payload


# ==================== Database Fixtures ====================

@pytest.fixture
@pytest.mark.django_db
def sample_repository(db):
    """Create a sample Repository for testing."""
    from bot_core.models import Repository
    return Repository.objects.create(
        full_name='test-org/test-repo',
        github_id=12345
    )


@pytest.fixture
@pytest.mark.django_db
def sample_application(db):
    """Create a sample Application for testing."""
    from bot_core.models import Application
    return Application.objects.create(
        name='Test App',
        github_repo='test-org/test-repo',
        description='Test application',
        is_active=True
    )


@pytest.fixture
@pytest.mark.django_db
def sample_conversation(db, sample_application):
    """Create a sample IssueConversation for testing."""
    from bot_core.models import IssueConversation
    return IssueConversation.objects.create(
        user_jid='test-user-jid',
        state=IssueConversation.State.AWAITING_APP,
        issue_title='Test Issue Title',
        expires_at=timezone.now() + timedelta(minutes=10)
    )


# ==================== Async Helpers ====================

@pytest.fixture
def run_async():
    """Helper to run async functions in sync tests."""
    import asyncio

    def _run(coro):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)

    return _run
