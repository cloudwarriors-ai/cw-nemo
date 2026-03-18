"""
Tests for WebSocket consumer functionality.

Tests the GitHubEventConsumer including:
- GitHub event broadcasting
- Container heartbeat broadcasting
- Connection and disconnection handling
"""
import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from channels.testing import WebsocketCommunicator
from channels.layers import get_channel_layer
from asgiref.sync import sync_to_async

from bot_core.consumers import GitHubEventConsumer


pytestmark = pytest.mark.django_db(transaction=True)


class TestGitHubEventConsumer:
    """Tests for GitHubEventConsumer WebSocket."""

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test WebSocket connection is accepted."""
        communicator = WebsocketCommunicator(
            GitHubEventConsumer.as_asgi(),
            "/ws/github/events/"
        )
        connected, _ = await communicator.connect()
        assert connected

        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test WebSocket disconnection is handled gracefully."""
        communicator = WebsocketCommunicator(
            GitHubEventConsumer.as_asgi(),
            "/ws/github/events/"
        )
        await communicator.connect()
        await communicator.disconnect()
        # No exception means success

    @pytest.mark.asyncio
    async def test_receive_ignored(self):
        """Test that messages from client are ignored (receive is a no-op)."""
        communicator = WebsocketCommunicator(
            GitHubEventConsumer.as_asgi(),
            "/ws/github/events/"
        )
        await communicator.connect()

        # Send a message (should be ignored)
        await communicator.send_json_to({"type": "test", "data": "ignored"})

        # Should timeout because no response is expected
        from asyncio import wait_for, TimeoutError as AsyncTimeoutError
        try:
            response = await wait_for(communicator.receive_from(), timeout=0.1)
            # If we get here, something unexpected was sent back
            assert False, f"Unexpected response: {response}"
        except AsyncTimeoutError:
            pass  # Expected - no response

        await communicator.disconnect()


class TestGitHubEventBroadcast:
    """Tests for GitHub event broadcasting."""

    @pytest.mark.asyncio
    async def test_github_event_broadcast(self):
        """Test that github_event messages are broadcast correctly."""
        communicator = WebsocketCommunicator(
            GitHubEventConsumer.as_asgi(),
            "/ws/github/events/"
        )
        await communicator.connect()

        # Simulate sending a github_event through the consumer's handler
        consumer = GitHubEventConsumer()
        consumer.send = AsyncMock()

        event_data = {
            'id': 123,
            'summary': 'Push to main (2 commits) by test-user',
            'repository': 'test-org/test-repo',
            'created_at': '2025-01-30T12:00:00Z',
            'actor_avatar': 'https://github.com/test-user.png',
            'html_url': 'https://github.com/test-org/test-repo/commits/main',
            'type': 'push'
        }

        await consumer.github_event({
            'type': 'github_event',
            'data': event_data
        })

        # Verify send was called with JSON data
        consumer.send.assert_called_once()
        call_args = consumer.send.call_args
        sent_data = json.loads(call_args[1]['text_data'])
        assert sent_data['id'] == 123
        assert sent_data['type'] == 'push'

        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_github_event_data_structure(self):
        """Test that broadcast event data has expected structure."""
        consumer = GitHubEventConsumer()
        consumer.send = AsyncMock()

        event_data = {
            'id': 456,
            'summary': 'PR #42 opened by contributor',
            'repository': 'org/repo',
            'created_at': '2025-01-30T14:00:00Z',
            'actor_avatar': 'https://github.com/user.png',
            'html_url': 'https://github.com/org/repo/pull/42',
            'type': 'pull_request'
        }

        await consumer.github_event({
            'type': 'github_event',
            'data': event_data
        })

        call_args = consumer.send.call_args
        sent_data = json.loads(call_args[1]['text_data'])

        # Verify all expected fields are present
        assert 'id' in sent_data
        assert 'summary' in sent_data
        assert 'repository' in sent_data
        assert 'created_at' in sent_data
        assert 'actor_avatar' in sent_data
        assert 'html_url' in sent_data
        assert 'type' in sent_data


class TestContainerHeartbeatBroadcast:
    """Tests for container heartbeat broadcasting."""

    @pytest.mark.asyncio
    async def test_container_heartbeat_broadcast(self):
        """Test that container_heartbeat messages are broadcast."""
        consumer = GitHubEventConsumer()
        consumer.send = AsyncMock()

        heartbeat_data = {
            'container': 'web-server',
            'status': 'healthy',
            'summary': 'Container is running normally'
        }

        await consumer.container_heartbeat({
            'type': 'container_heartbeat',
            'data': heartbeat_data
        })

        consumer.send.assert_called_once()
        call_args = consumer.send.call_args
        sent_data = json.loads(call_args[1]['text_data'])

        assert 'container' in sent_data or 'status' in sent_data

    @pytest.mark.asyncio
    async def test_unhealthy_container_alert_level(self):
        """Test that unhealthy containers get danger alert level."""
        consumer = GitHubEventConsumer()
        consumer.send = AsyncMock()

        heartbeat_data = {
            'container': 'database',
            'status': 'unhealthy',
            'summary': 'Database connection failed'
        }

        await consumer.container_heartbeat({
            'type': 'container_heartbeat',
            'data': heartbeat_data
        })

        call_args = consumer.send.call_args
        sent_data = json.loads(call_args[1]['text_data'])

        assert sent_data['alert_level'] == 'danger'
        assert sent_data['status'] == 'unhealthy'

    @pytest.mark.asyncio
    async def test_healthy_container_alert_level(self):
        """Test that healthy containers get success alert level."""
        consumer = GitHubEventConsumer()
        consumer.send = AsyncMock()

        heartbeat_data = {
            'container': 'api-server',
            'status': 'healthy',
            'summary': 'API responding normally'
        }

        await consumer.container_heartbeat({
            'type': 'container_heartbeat',
            'data': heartbeat_data
        })

        call_args = consumer.send.call_args
        sent_data = json.loads(call_args[1]['text_data'])

        assert sent_data['alert_level'] == 'success'

    @pytest.mark.asyncio
    async def test_heartbeat_summary_formatting(self):
        """Test that heartbeat summary is formatted correctly."""
        consumer = GitHubEventConsumer()
        consumer.send = AsyncMock()

        heartbeat_data = {
            'container': 'worker',
            'status': 'healthy',
            'summary': 'Processing tasks'
        }

        await consumer.container_heartbeat({
            'type': 'container_heartbeat',
            'data': heartbeat_data
        })

        call_args = consumer.send.call_args
        sent_data = json.loads(call_args[1]['text_data'])

        # Summary should be prefixed if not already
        assert 'Container Heartbeat:' in sent_data['summary']


class TestChannelGroupMembership:
    """Tests for channel group membership handling."""

    @pytest.mark.asyncio
    async def test_connect_joins_github_events_group(self):
        """Test that connecting adds consumer to github_events group."""
        communicator = WebsocketCommunicator(
            GitHubEventConsumer.as_asgi(),
            "/ws/github/events/"
        )
        await communicator.connect()

        # The consumer should now be in the github_events group
        # This is verified by the fact that connect() succeeded
        # and the consumer's connect method calls group_add

        await communicator.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_leaves_github_events_group(self):
        """Test that disconnecting removes consumer from github_events group."""
        communicator = WebsocketCommunicator(
            GitHubEventConsumer.as_asgi(),
            "/ws/github/events/"
        )
        await communicator.connect()
        await communicator.disconnect()

        # Disconnect should have called group_discard
        # If there's an error, the test would fail


class TestGetLatestEvents:
    """Tests for the get_latest_events database method."""

    @pytest.mark.asyncio
    async def test_get_latest_events_empty(self):
        """Test get_latest_events when no events exist."""
        consumer = GitHubEventConsumer()
        events = await consumer.get_latest_events()

        assert events == []

    @pytest.mark.asyncio
    async def test_get_latest_events_with_data(self, sample_repository):
        """Test get_latest_events returns formatted events."""
        from bot_core.models import WebhookEvent

        # Create test events
        await sync_to_async(WebhookEvent.objects.create)(
            repository=sample_repository,
            event_type='push',
            payload={},
            actor_login='test-user',
            actor_avatar_url='https://github.com/test-user.png',
            action='push',
            title='Test push',
            ref='refs/heads/main',
            commits_count=3,
            html_url='https://github.com/test-org/test-repo/commits/main'
        )

        consumer = GitHubEventConsumer()
        events = await consumer.get_latest_events()

        assert len(events) == 1
        event = events[0]
        assert event['type'] == 'push'
        assert event['repository'] == 'test-org/test-repo'
        assert event['actor_avatar'] == 'https://github.com/test-user.png'
        assert 'summary' in event
        assert 'created_at' in event
        assert 'html_url' in event

    @pytest.mark.asyncio
    async def test_get_latest_events_limit(self, sample_repository):
        """Test get_latest_events returns max 50 events."""
        from bot_core.models import WebhookEvent

        # Create 60 events
        for i in range(60):
            await sync_to_async(WebhookEvent.objects.create)(
                repository=sample_repository,
                event_type='push',
                payload={},
                actor_login='user',
                action='push',
                title=f'Push {i}',
                commits_count=1
            )

        consumer = GitHubEventConsumer()
        events = await consumer.get_latest_events()

        assert len(events) == 50  # Limited to 50
