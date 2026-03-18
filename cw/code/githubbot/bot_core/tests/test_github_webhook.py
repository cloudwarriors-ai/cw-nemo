"""
Tests for GitHub webhook processing.

Tests the webhook endpoint at /api/webhook/ including:
- Signature verification
- Event type processing (push, pull_request, issues, issue_comment)
- Database storage of events
- WebSocket broadcasting
"""
import json
import hmac
import hashlib
from unittest.mock import patch, AsyncMock, Mock

import pytest
from django.test import AsyncClient
from asgiref.sync import sync_to_async

from bot_core.tests.conftest import generate_github_signature


pytestmark = pytest.mark.django_db(transaction=True)


class TestGitHubSignatureVerification:
    """Tests for GitHub webhook signature verification."""

    @pytest.mark.asyncio
    async def test_signature_verification_valid(self, async_client, github_push_payload):
        """Test that valid signatures are accepted."""
        payload_bytes = json.dumps(github_push_payload).encode('utf-8')
        signature = generate_github_signature(payload_bytes)

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom, \
             patch('bot_core.llm_bot.llm_bot') as mock_llm, \
             patch('bot_core.api.github_webhook.get_channel_layer') as mock_channel:
            mock_zoom.send_message = Mock()
            mock_llm.generate_response = Mock(return_value="Test comment")
            mock_channel.return_value = AsyncMock()
            mock_channel.return_value.group_send = AsyncMock()

            response = await async_client.post(
                '/api/webhook/',
                data=payload_bytes,
                content_type='application/json',
                headers={
                    'X-Hub-Signature-256': signature,
                    'X-GitHub-Event': 'push'
                }
            )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self, async_client, github_push_payload):
        """Test that invalid signatures are rejected with 403."""
        payload_bytes = json.dumps(github_push_payload).encode('utf-8')
        invalid_signature = 'sha256=invalid_signature_here'

        response = await async_client.post(
            '/api/webhook/',
            data=payload_bytes,
            content_type='application/json',
            headers={
                'X-Hub-Signature-256': invalid_signature,
                'X-GitHub-Event': 'push'
            }
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_signature_rejected(self, async_client, github_push_payload):
        """Test that missing signatures are rejected."""
        payload_bytes = json.dumps(github_push_payload).encode('utf-8')

        response = await async_client.post(
            '/api/webhook/',
            data=payload_bytes,
            content_type='application/json',
            headers={
                'X-GitHub-Event': 'push'
            }
        )

        assert response.status_code == 403


class TestPushEventProcessing:
    """Tests for GitHub push event processing."""

    @pytest.mark.asyncio
    async def test_push_event_processing(self, async_client, github_push_payload):
        """Test that push events are processed and stored correctly."""
        from bot_core.models import WebhookEvent, Repository

        payload_bytes = json.dumps(github_push_payload).encode('utf-8')
        signature = generate_github_signature(payload_bytes)

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom, \
             patch('bot_core.llm_bot.llm_bot') as mock_llm, \
             patch('bot_core.api.github_webhook.get_channel_layer') as mock_channel:
            mock_zoom.send_message = Mock()
            mock_llm.generate_response = Mock(return_value="Test comment")
            mock_channel.return_value = AsyncMock()
            mock_channel.return_value.group_send = AsyncMock()

            response = await async_client.post(
                '/api/webhook/',
                data=payload_bytes,
                content_type='application/json',
                headers={
                    'X-Hub-Signature-256': signature,
                    'X-GitHub-Event': 'push'
                }
            )

        assert response.status_code == 200

        # Verify repository was created
        repo_exists = await sync_to_async(Repository.objects.filter(
            full_name='test-org/test-repo'
        ).exists)()
        assert repo_exists

        # Verify webhook event was stored
        event_exists = await sync_to_async(WebhookEvent.objects.filter(
            event_type='push',
            actor_login='test-user'
        ).exists)()
        assert event_exists

    @pytest.mark.asyncio
    async def test_push_event_sends_zoom_notification(self, async_client, github_push_payload):
        """Test that push events trigger Zoom notifications."""
        payload_bytes = json.dumps(github_push_payload).encode('utf-8')
        signature = generate_github_signature(payload_bytes)

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom, \
             patch('bot_core.llm_bot.llm_bot') as mock_llm, \
             patch('bot_core.api.github_webhook.get_channel_layer') as mock_channel:
            mock_zoom.send_message = Mock()
            mock_llm.generate_response = Mock(return_value="Test comment")
            mock_channel.return_value = AsyncMock()
            mock_channel.return_value.group_send = AsyncMock()

            await async_client.post(
                '/api/webhook/',
                data=payload_bytes,
                content_type='application/json',
                headers={
                    'X-Hub-Signature-256': signature,
                    'X-GitHub-Event': 'push'
                }
            )

            # Verify Zoom message was sent
            mock_zoom.send_message.assert_called_once()
            call_args = mock_zoom.send_message.call_args[0][0]
            assert 'test-org/test-repo' in call_args
            assert 'Push' in call_args or 'push' in call_args.lower()


class TestPullRequestEventProcessing:
    """Tests for GitHub pull request event processing."""

    @pytest.mark.asyncio
    async def test_pull_request_event_processing(self, async_client, github_pr_payload):
        """Test that PR events are processed correctly."""
        from bot_core.models import WebhookEvent

        payload_bytes = json.dumps(github_pr_payload).encode('utf-8')
        signature = generate_github_signature(payload_bytes)

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom, \
             patch('bot_core.llm_bot.llm_bot') as mock_llm, \
             patch('bot_core.api.github_webhook.get_channel_layer') as mock_channel:
            mock_zoom.send_message = Mock()
            mock_llm.generate_response = Mock(return_value="Test comment")
            mock_channel.return_value = AsyncMock()
            mock_channel.return_value.group_send = AsyncMock()

            response = await async_client.post(
                '/api/webhook/',
                data=payload_bytes,
                content_type='application/json',
                headers={
                    'X-Hub-Signature-256': signature,
                    'X-GitHub-Event': 'pull_request'
                }
            )

        assert response.status_code == 200

        # Verify webhook event was stored with correct data
        event = await sync_to_async(WebhookEvent.objects.filter(
            event_type='pull_request'
        ).first)()
        assert event is not None
        assert event.action == 'opened'
        assert event.title == 'Test PR Title'


class TestIssuesEventProcessing:
    """Tests for GitHub issues event processing."""

    @pytest.mark.asyncio
    async def test_issues_event_processing(self, async_client, github_issue_payload):
        """Test that issue events are processed correctly."""
        from bot_core.models import WebhookEvent

        payload_bytes = json.dumps(github_issue_payload).encode('utf-8')
        signature = generate_github_signature(payload_bytes)

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom, \
             patch('bot_core.llm_bot.llm_bot') as mock_llm, \
             patch('bot_core.api.github_webhook.get_channel_layer') as mock_channel:
            mock_zoom.send_message = Mock()
            mock_llm.generate_response = Mock(return_value="Test comment")
            mock_channel.return_value = AsyncMock()
            mock_channel.return_value.group_send = AsyncMock()

            response = await async_client.post(
                '/api/webhook/',
                data=payload_bytes,
                content_type='application/json',
                headers={
                    'X-Hub-Signature-256': signature,
                    'X-GitHub-Event': 'issues'
                }
            )

        assert response.status_code == 200

        # Verify webhook event was stored
        event = await sync_to_async(WebhookEvent.objects.filter(
            event_type='issues'
        ).first)()
        assert event is not None
        assert event.title == 'Test Issue Title'
        assert event.action == 'opened'


class TestIssueCommentEventProcessing:
    """Tests for GitHub issue comment event processing."""

    @pytest.mark.asyncio
    async def test_issue_comment_event_processing(self, async_client, github_issue_comment_payload):
        """Test that issue comment events are processed correctly."""
        from bot_core.models import WebhookEvent

        payload_bytes = json.dumps(github_issue_comment_payload).encode('utf-8')
        signature = generate_github_signature(payload_bytes)

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom, \
             patch('bot_core.llm_bot.llm_bot') as mock_llm, \
             patch('bot_core.api.github_webhook.get_channel_layer') as mock_channel:
            mock_zoom.send_message = Mock()
            mock_llm.generate_response = Mock(return_value="Test comment")
            mock_channel.return_value = AsyncMock()
            mock_channel.return_value.group_send = AsyncMock()

            response = await async_client.post(
                '/api/webhook/',
                data=payload_bytes,
                content_type='application/json',
                headers={
                    'X-Hub-Signature-256': signature,
                    'X-GitHub-Event': 'issue_comment'
                }
            )

        assert response.status_code == 200

        # Verify webhook event was stored
        event = await sync_to_async(WebhookEvent.objects.filter(
            event_type='issue_comment'
        ).first)()
        assert event is not None
        assert 'Test Issue Title' in event.title


class TestUnsupportedEventTypes:
    """Tests for handling unsupported GitHub event types."""

    @pytest.mark.asyncio
    async def test_unsupported_event_type_ignored(self, async_client):
        """Test that unsupported event types are ignored with 200 OK."""
        payload = {
            'action': 'created',
            'repository': {'id': 12345, 'full_name': 'test/repo'},
            'sender': {'login': 'user', 'avatar_url': ''}
        }
        payload_bytes = json.dumps(payload).encode('utf-8')
        signature = generate_github_signature(payload_bytes)

        response = await async_client.post(
            '/api/webhook/',
            data=payload_bytes,
            content_type='application/json',
            headers={
                'X-Hub-Signature-256': signature,
                'X-GitHub-Event': 'star'  # Not in allowed events
            }
        )

        assert response.status_code == 200
        assert b'not tracked' in response.content.lower()

    @pytest.mark.asyncio
    async def test_fork_event_ignored(self, async_client):
        """Test that fork events are gracefully ignored."""
        payload = {
            'forkee': {'id': 99999, 'full_name': 'fork/repo'},
            'repository': {'id': 12345, 'full_name': 'test/repo'},
            'sender': {'login': 'user', 'avatar_url': ''}
        }
        payload_bytes = json.dumps(payload).encode('utf-8')
        signature = generate_github_signature(payload_bytes)

        response = await async_client.post(
            '/api/webhook/',
            data=payload_bytes,
            content_type='application/json',
            headers={
                'X-Hub-Signature-256': signature,
                'X-GitHub-Event': 'fork'
            }
        )

        assert response.status_code == 200


class TestWebSocketBroadcast:
    """Tests for WebSocket event broadcasting."""

    @pytest.mark.asyncio
    async def test_github_event_broadcast(self, async_client, github_push_payload):
        """Test that events are broadcast to WebSocket group."""
        payload_bytes = json.dumps(github_push_payload).encode('utf-8')
        signature = generate_github_signature(payload_bytes)

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom, \
             patch('bot_core.llm_bot.llm_bot') as mock_llm, \
             patch('bot_core.api.github_webhook.get_channel_layer') as mock_channel:
            mock_zoom.send_message = Mock()
            mock_llm.generate_response = Mock(return_value="Test comment")
            layer = AsyncMock()
            layer.group_send = AsyncMock()
            mock_channel.return_value = layer

            await async_client.post(
                '/api/webhook/',
                data=payload_bytes,
                content_type='application/json',
                headers={
                    'X-Hub-Signature-256': signature,
                    'X-GitHub-Event': 'push'
                }
            )

            # Verify group_send was called with github_events group
            layer.group_send.assert_called()
            call_args = layer.group_send.call_args_list[-1]
            assert call_args[0][0] == 'github_events'
            assert call_args[0][1]['type'] == 'github_event'


class TestInvalidPayloads:
    """Tests for handling invalid payloads."""

    @pytest.mark.asyncio
    async def test_invalid_json_rejected(self, async_client):
        """Test that invalid JSON is rejected."""
        payload_bytes = b'not valid json'
        signature = generate_github_signature(payload_bytes)

        response = await async_client.post(
            '/api/webhook/',
            data=payload_bytes,
            content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256=signature,
            headers={
                'X-GitHub-Event': 'push'
            }
        )

        assert response.status_code == 400
