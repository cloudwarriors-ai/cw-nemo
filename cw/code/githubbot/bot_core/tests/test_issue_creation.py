"""
Tests for the GitHub issue creation flow.

Tests the issue maker functionality including:
- Quick create flow (button click → immediate issue creation)
- Cancel flow
- App selection
- Button actions (create_issue, quick_create, cancel_form, etc.)
"""
import json
from unittest.mock import patch, Mock, AsyncMock

import pytest
from django.test import AsyncClient
from django.utils import timezone
from datetime import timedelta
from asgiref.sync import sync_to_async


pytestmark = pytest.mark.django_db(transaction=True)


class TestQuickCreateFlow:
    """Tests for the quick create flow (app button → immediate issue creation)."""

    @pytest.mark.asyncio
    async def test_quick_create_success(
            self, async_client, zoom_button_click_payload, sample_application, sample_conversation):
        """Test successful quick_create button click creates GitHub issue."""
        from bot_core.models import IssueConversation

        # Set up the conversation with the title
        sample_conversation.issue_title = "Test Quick Issue"
        await sync_to_async(sample_conversation.save)()

        payload = zoom_button_click_payload(
            f'quick_create:{sample_conversation.id}:{sample_application.id}'
        )

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot, \
             patch('bot_core.github_bot.github_bot') as mock_github:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()
            mock_issue_bot.delete_message = Mock(return_value=True)
            mock_github.enabled = True
            mock_github.create_issue = Mock(
                return_value=(42, 'https://github.com/test-org/test-repo/issues/42')
            )

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        # Verify GitHub issue was created
        mock_github.create_issue.assert_called_once()
        call_args = mock_github.create_issue.call_args
        assert call_args[0][0] == sample_application.github_repo
        assert call_args[0][1] == "Test Quick Issue"

        # Verify conversation was marked as completed
        await sync_to_async(sample_conversation.refresh_from_db)()
        assert sample_conversation.state == IssueConversation.State.COMPLETED
        assert sample_conversation.github_issue_number == 42
        assert sample_conversation.github_issue_url == 'https://github.com/test-org/test-repo/issues/42'

    @pytest.mark.asyncio
    async def test_quick_create_github_failure(
            self, async_client, zoom_button_click_payload, sample_application, sample_conversation):
        """Test quick_create handles GitHub API failure gracefully."""
        sample_conversation.issue_title = "Test Issue"
        await sync_to_async(sample_conversation.save)()

        payload = zoom_button_click_payload(
            f'quick_create:{sample_conversation.id}:{sample_application.id}'
        )

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot, \
             patch('bot_core.github_bot.github_bot') as mock_github:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()
            mock_github.enabled = True
            mock_github.create_issue = Mock(return_value=(None, None))  # Failure

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        # Verify error message was sent
        mock_issue_bot.send_message.assert_called_once()
        call_args = mock_issue_bot.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        assert 'failed' in body_text.lower() or 'error' in body_text.lower()

    @pytest.mark.asyncio
    async def test_quick_create_github_disabled(
            self, async_client, zoom_button_click_payload, sample_application, sample_conversation):
        """Test quick_create handles disabled GitHub bot."""
        sample_conversation.issue_title = "Test Issue"
        await sync_to_async(sample_conversation.save)()

        payload = zoom_button_click_payload(
            f'quick_create:{sample_conversation.id}:{sample_application.id}'
        )

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot, \
             patch('bot_core.github_bot.github_bot') as mock_github:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()
            mock_github.enabled = False  # GitHub bot disabled

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_issue_bot.send_message.assert_called_once()
        call_args = mock_issue_bot.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        assert 'not configured' in body_text.lower()

    @pytest.mark.asyncio
    async def test_quick_create_expired_conversation(
            self, async_client, zoom_button_click_payload, sample_application, sample_conversation):
        """Test quick_create with expired conversation."""
        # Expire the conversation
        sample_conversation.expires_at = timezone.now() - timedelta(minutes=1)
        sample_conversation.issue_title = "Test Issue"
        await sync_to_async(sample_conversation.save)()

        payload = zoom_button_click_payload(
            f'quick_create:{sample_conversation.id}:{sample_application.id}'
        )

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot, \
             patch('bot_core.github_bot.github_bot') as mock_github:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()
            mock_github.enabled = True
            # Note: quick_create doesn't check expiry currently, but creates issue anyway
            mock_github.create_issue = Mock(
                return_value=(42, 'https://github.com/test/repo/issues/42')
            )

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200


class TestCancelFlow:
    """Tests for the cancel flow."""

    @pytest.mark.asyncio
    async def test_cancel_form_button(
            self, async_client, zoom_button_click_payload, sample_conversation):
        """Test cancel_form button cancels the conversation."""
        from bot_core.models import IssueConversation

        payload = zoom_button_click_payload(f'cancel_form:{sample_conversation.id}')

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()
            mock_issue_bot.delete_message = Mock(return_value=True)

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        # Verify conversation was cancelled
        await sync_to_async(sample_conversation.refresh_from_db)()
        assert sample_conversation.state == IssueConversation.State.CANCELLED

        # Verify cancel message was sent
        mock_issue_bot.send_message.assert_called_once()
        call_args = mock_issue_bot.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        assert 'cancelled' in body_text.lower()

    @pytest.mark.asyncio
    async def test_cancel_button_action(
            self, async_client, zoom_button_click_payload, sample_conversation):
        """Test cancel:<id> button action."""
        from bot_core.models import IssueConversation

        payload = zoom_button_click_payload(f'cancel:{sample_conversation.id}')

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        await sync_to_async(sample_conversation.refresh_from_db)()
        assert sample_conversation.state == IssueConversation.State.CANCELLED


class TestAppSelection:
    """Tests for application selection flow."""

    @pytest.mark.asyncio
    async def test_select_app_button(
            self, async_client, zoom_button_click_payload, sample_application, sample_conversation):
        """Test select_app button updates conversation."""
        from bot_core.models import IssueConversation

        payload = zoom_button_click_payload(
            f'select_app:{sample_conversation.id}:{sample_application.id}'
        )

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        # Verify conversation was updated
        await sync_to_async(sample_conversation.refresh_from_db)()
        app = await sync_to_async(lambda: sample_conversation.selected_app)()
        assert app.id == sample_application.id
        assert sample_conversation.state == IssueConversation.State.AWAITING_DESCRIPTION

    @pytest.mark.asyncio
    async def test_select_app_expired_conversation(
            self, async_client, zoom_button_click_payload, sample_application, sample_conversation):
        """Test select_app with expired conversation returns error."""
        # Expire the conversation
        sample_conversation.expires_at = timezone.now() - timedelta(minutes=1)
        await sync_to_async(sample_conversation.save)()

        payload = zoom_button_click_payload(
            f'select_app:{sample_conversation.id}:{sample_application.id}'
        )

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_issue_bot.send_message.assert_called_once()
        call_args = mock_issue_bot.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        assert 'expired' in body_text.lower()


class TestSubmitIssue:
    """Tests for the submit_issue button action with form data."""

    @pytest.mark.asyncio
    async def test_submit_issue_with_description(
            self, async_client, sample_application, sample_conversation):
        """Test submit_issue with form description creates issue."""
        from bot_core.models import IssueConversation

        # Set up conversation state
        sample_conversation.issue_title = "Test Issue"
        sample_conversation.selected_app = sample_application
        sample_conversation.state = IssueConversation.State.AWAITING_DESCRIPTION
        await sync_to_async(sample_conversation.save)()

        payload = {
            'payload': {
                'userJid': 'test-user-jid',
                'userName': 'Test User',
                'toJid': 'test-channel-jid',
                'messageId': 'test-message-id',
                'actionItem': {
                    'value': f'submit_issue:{sample_conversation.id}'
                },
                'original': {
                    'body': [
                        {
                            'type': 'fields',
                            'items': [
                                {'key': 'description', 'value': 'This is the issue description'}
                            ]
                        }
                    ]
                }
            }
        }

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot, \
             patch('bot_core.github_bot.github_bot') as mock_github:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()
            mock_github.enabled = True
            mock_github.create_issue = Mock(
                return_value=(99, 'https://github.com/test-org/test-repo/issues/99')
            )

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        # Verify issue was created with description
        mock_github.create_issue.assert_called_once()
        call_args = mock_github.create_issue.call_args
        assert 'This is the issue description' in call_args[0][2]

        # Verify conversation was completed
        await sync_to_async(sample_conversation.refresh_from_db)()
        assert sample_conversation.state == IssueConversation.State.COMPLETED
        assert sample_conversation.github_issue_number == 99

    @pytest.mark.asyncio
    async def test_submit_issue_empty_description(
            self, async_client, sample_application, sample_conversation):
        """Test submit_issue with empty description returns error."""
        from bot_core.models import IssueConversation

        sample_conversation.issue_title = "Test Issue"
        sample_conversation.selected_app = sample_application
        sample_conversation.state = IssueConversation.State.AWAITING_DESCRIPTION
        await sync_to_async(sample_conversation.save)()

        payload = {
            'payload': {
                'userJid': 'test-user-jid',
                'userName': 'Test User',
                'toJid': 'test-channel-jid',
                'messageId': 'test-message-id',
                'actionItem': {
                    'value': f'submit_issue:{sample_conversation.id}'
                },
                'original': {
                    'body': [
                        {
                            'type': 'fields',
                            'items': [
                                {'key': 'description', 'value': ''}
                            ]
                        }
                    ]
                }
            }
        }

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_issue_bot.send_message.assert_called_once()
        call_args = mock_issue_bot.send_message.call_args[0][0]
        assert call_args['head']['text'] == 'Missing Description'


class TestCreateIssueButton:
    """Tests for the create_issue button action (full form submission)."""

    @pytest.mark.asyncio
    async def test_create_issue_missing_title(
            self, async_client, zoom_button_click_payload, sample_conversation):
        """Test create_issue with missing title returns error."""
        sample_conversation.issue_title = ''
        await sync_to_async(sample_conversation.save)()

        payload = zoom_button_click_payload(f'create_issue:{sample_conversation.id}')

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_issue_bot.send_message.assert_called_once()
        call_args = mock_issue_bot.send_message.call_args[0][0]
        assert call_args['head']['text'] == 'Missing Title'


class TestSlashCommand:
    """Tests for the /issue slash command in issue-command endpoint."""

    @pytest.mark.asyncio
    async def test_slash_command_empty(self, async_client, sample_application):
        """Test /issue with no args shows form."""
        payload = {
            'payload': {
                'userJid': 'test-user-jid',
                'userName': 'Test User',
                'toJid': 'test-channel-jid',
                'cmd': ''
            }
        }

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        mock_issue_bot.send_message.assert_called_once()
        call_args = mock_issue_bot.send_message.call_args[0][0]
        body_text = call_args['body'][0]['text']
        # Should show usage or form
        assert 'usage' in body_text.lower() or '/issue' in body_text.lower()

    @pytest.mark.asyncio
    async def test_slash_command_with_title(self, async_client, sample_application):
        """Test /issue "title" shows app selection."""
        from bot_core.models import IssueConversation

        payload = {
            'payload': {
                'userJid': 'test-user-jid',
                'userName': 'Test User',
                'toJid': 'test-channel-jid',
                'cmd': '"Test Issue Title"'
            }
        }

        with patch('bot_core.issue_maker_bot.issue_maker_bot') as mock_issue_bot:
            mock_issue_bot.enabled = True
            mock_issue_bot.send_message = Mock()

            response = await async_client.post(
                '/issue-command/',
                data=json.dumps(payload),
                content_type='application/json'
            )

        assert response.status_code == 200

        # Verify conversation was created
        conversation = await sync_to_async(IssueConversation.objects.filter(
            user_jid='test-user-jid',
            issue_title='Test Issue Title'
        ).first)()
        assert conversation is not None

        # Verify app selection was shown
        mock_issue_bot.send_message.assert_called_once()
        call_args = mock_issue_bot.send_message.call_args[0][0]
        body = call_args['body']

        # Find actions
        has_actions = any(item.get('type') == 'actions' for item in body)
        assert has_actions
