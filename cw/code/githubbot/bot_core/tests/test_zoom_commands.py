"""
Tests for Zoom slash command handling.

Tests the /command/ endpoint and handle_zoom_command() function including:
- help command
- events command
- chat command
- whoami command
- issue command flow
- unknown command handling
"""
import json
from unittest.mock import patch, Mock, AsyncMock

import pytest
from django.test import AsyncClient
from asgiref.sync import sync_to_async


pytestmark = pytest.mark.django_db(transaction=True)


class TestHelpCommand:
    """Tests for the help command."""

    @pytest.mark.asyncio
    async def test_help_command_returns_command_list(self, async_client, zoom_command_payload):
        """Test that help command returns list of available commands."""
        payload = zoom_command_payload('help')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            response = await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        # Verify help message was sent
        mock_zoom.send_message.assert_called_once()
        call_args = mock_zoom.send_message.call_args[0][0]

        # Check that help message contains expected commands
        body_text = call_args['body'][0]['text']
        assert 'help' in body_text.lower()
        assert 'events' in body_text.lower()
        assert 'issue' in body_text.lower()
        assert 'chat' in body_text.lower()
        assert 'whoami' in body_text.lower()


class TestEventsCommand:
    """Tests for the events command."""

    @pytest.mark.asyncio
    async def test_events_command_no_events(self, async_client, zoom_command_payload):
        """Test events command when no events exist."""
        payload = zoom_command_payload('events')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            response = await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_zoom.send_message.assert_called_once()
        call_args = mock_zoom.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        assert 'no recent events' in body_text.lower()

    @pytest.mark.asyncio
    async def test_events_command_with_events(self, async_client, zoom_command_payload, sample_repository):
        """Test events command with existing events."""
        from bot_core.models import WebhookEvent

        # Create a test event
        await sync_to_async(WebhookEvent.objects.create)(
            repository=sample_repository,
            event_type='push',
            payload={},
            actor_login='test-user',
            action='push',
            title='Test push event',
            ref='refs/heads/main',
            commits_count=1
        )

        payload = zoom_command_payload('events')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            response = await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_zoom.send_message.assert_called_once()
        call_args = mock_zoom.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        assert 'test-org/test-repo' in body_text


class TestChatCommand:
    """Tests for the chat command."""

    @pytest.mark.asyncio
    async def test_chat_command_without_message(self, async_client, zoom_command_payload):
        """Test chat command without a message prompts for input."""
        payload = zoom_command_payload('chat')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            response = await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_zoom.send_message.assert_called_once()
        call_args = mock_zoom.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        assert 'provide a message' in body_text.lower()

    @pytest.mark.asyncio
    async def test_chat_command_with_message(self, async_client, zoom_command_payload):
        """Test chat command calls LLM and returns response."""
        payload = zoom_command_payload('chat Hello, how are you?')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom, \
             patch('bot_core.llm_bot.llm_bot') as mock_llm:
            mock_zoom.send_message = Mock()
            mock_llm.generate_response = AsyncMock(return_value="I'm doing great, thanks!")

            response = await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        # Verify LLM was called
        mock_llm.generate_response.assert_called_once()

        # Verify response was sent
        mock_zoom.send_message.assert_called_once()
        call_args = mock_zoom.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        assert "I'm doing great" in body_text


class TestWhoamiCommand:
    """Tests for the whoami command."""

    @pytest.mark.asyncio
    async def test_whoami_command_returns_user_info(self, async_client):
        """Test whoami command returns user's Zoom information."""
        payload = {
            'payload': {
                'userJid': 'test-user-jid-12345',
                'userName': 'Test User Name',
                'toJid': 'test-channel-jid-67890',
                'robotJid': 'test-robot-jid',
                'accountId': 'test-account-id',
                'cmd': 'whoami'
            }
        }

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            response = await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_zoom.send_message.assert_called_once()
        call_args = mock_zoom.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']

        # Check that user info is present
        assert 'Test User Name' in body_text
        assert 'test-user-jid-12345' in body_text
        assert 'test-channel-jid-67890' in body_text


class TestIssueCommand:
    """Tests for the issue command flow."""

    @pytest.mark.asyncio
    async def test_issue_command_without_title(self, async_client, zoom_command_payload):
        """Test issue command without title shows usage."""
        payload = zoom_command_payload('issue')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            response = await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_zoom.send_message.assert_called_once()
        call_args = mock_zoom.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        assert 'usage' in body_text.lower() or 'example' in body_text.lower()

    @pytest.mark.asyncio
    async def test_issue_command_with_title_no_apps(self, async_client, zoom_command_payload):
        """Test issue command when no applications are configured."""
        payload = zoom_command_payload('issue "Test Issue Title"')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            response = await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_zoom.send_message.assert_called_once()
        call_args = mock_zoom.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        assert 'no applications' in body_text.lower() or 'contact' in body_text.lower()

    @pytest.mark.asyncio
    async def test_issue_command_with_title_shows_app_buttons(
            self, async_client, zoom_command_payload, sample_application):
        """Test issue command with title shows app selection buttons."""
        payload = zoom_command_payload('issue "Test Issue Title"')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            response = await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_zoom.send_message.assert_called_once()
        call_args = mock_zoom.send_message.call_args[0][0]

        # Should have body with message and actions
        assert 'body' in call_args
        body = call_args['body']

        # Find actions item
        actions = None
        for item in body:
            if item.get('type') == 'actions':
                actions = item
                break

        assert actions is not None
        # Should have app button and cancel button
        assert len(actions['items']) >= 2

    @pytest.mark.asyncio
    async def test_issue_command_creates_conversation(
            self, async_client, zoom_command_payload, sample_application):
        """Test that issue command creates an IssueConversation record."""
        from bot_core.models import IssueConversation

        payload = zoom_command_payload('issue "Test Issue Title"')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        # Verify conversation was created
        conversation = await sync_to_async(IssueConversation.objects.filter(
            user_jid='test-user-jid',
            issue_title='Test Issue Title'
        ).first)()

        assert conversation is not None
        assert conversation.state == IssueConversation.State.AWAITING_APP


class TestUnknownCommand:
    """Tests for unknown command handling."""

    @pytest.mark.asyncio
    async def test_unknown_command_returns_error(self, async_client, zoom_command_payload):
        """Test that unknown commands return helpful error message."""
        payload = zoom_command_payload('unknowncommand')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            response = await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_zoom.send_message.assert_called_once()
        call_args = mock_zoom.send_message.call_args[0][0]

        # Should indicate unknown command
        assert call_args['head']['text'] == 'Unknown Command'
        body_text = call_args['body'][0]['text']
        assert 'unknown command' in body_text.lower()
        assert 'help' in body_text.lower()


class TestZoomCommandLogging:
    """Tests for Zoom command logging."""

    @pytest.mark.asyncio
    async def test_commands_are_logged(self, async_client, zoom_command_payload):
        """Test that all commands are logged to ZoomCommand model."""
        from bot_core.models import ZoomCommand

        payload = zoom_command_payload('help')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        # Verify command was logged
        logged_command = await sync_to_async(ZoomCommand.objects.filter(
            user_jid='test-user-jid',
            command='help'
        ).first)()

        assert logged_command is not None
        assert logged_command.user_name == 'Test User'


class TestCancelCommand:
    """Tests for cancel command during issue creation."""

    @pytest.mark.asyncio
    async def test_cancel_with_active_conversation(
            self, async_client, zoom_command_payload, sample_conversation):
        """Test that cancel command cancels active conversation."""
        from bot_core.models import IssueConversation

        payload = zoom_command_payload('cancel')

        with patch('bot_core.zoom_bot.zoom_bot') as mock_zoom:
            mock_zoom.send_message = Mock()

            await async_client.post(
                '/command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        # Verify conversation was cancelled
        await sync_to_async(sample_conversation.refresh_from_db)()
        assert sample_conversation.state == IssueConversation.State.CANCELLED

        mock_zoom.send_message.assert_called_once()
        call_args = mock_zoom.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        assert 'cancelled' in body_text.lower()
