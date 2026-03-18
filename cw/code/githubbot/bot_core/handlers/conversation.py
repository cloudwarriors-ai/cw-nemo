"""
Issue conversation state management.

Handles multi-step conversation flow for issue creation including:
- Active conversation lookup
- App selection prompts
- Description input handling
- Conversation cancellation
"""
import logging
from datetime import timedelta

from django.utils import timezone
from asgiref.sync import sync_to_async

from bot_core.models import Application, IssueConversation

logger = logging.getLogger(__name__)


async def get_active_conversation(user_jid: str):
    """
    Find an active (non-expired, pending) conversation for a user.

    Args:
        user_jid: The user's Zoom JID

    Returns:
        IssueConversation instance or None
    """
    def _get_conversation():
        return IssueConversation.objects.filter(
            user_jid=user_jid,
            state__in=[IssueConversation.State.AWAITING_APP, IssueConversation.State.AWAITING_DESCRIPTION],
            expires_at__gt=timezone.now()
        ).first()
    return await sync_to_async(_get_conversation)()


async def get_active_applications():
    """
    Get list of active applications.

    Returns:
        List of Application instances
    """
    def _get_apps():
        return list(Application.objects.filter(is_active=True).order_by('name'))
    return await sync_to_async(_get_apps)()


async def handle_issue_command(title: str, user_data: dict) -> dict:
    """
    Show app selection buttons for issue creation - simple two-step flow.

    Args:
        title: The issue title
        user_data: Dictionary containing user_jid, user_name, etc.

    Returns:
        Zoom message response dict
    """
    # Require a title
    if not title or not title.strip():
        return {
            'head': {'text': 'Create Issue'},
            'body': [{
                'type': 'message',
                'text': '📝 **Create a GitHub Issue**\n\nUsage: `/issue <title>`\n\nExample: `/issue Login button broken on mobile`'
            }]
        }

    # Get active applications
    apps = await get_active_applications()

    if not apps:
        return {
            'head': {'text': 'Issue Creation'},
            'body': [{
                'type': 'message',
                'text': '❌ No applications configured. Please contact an admin.'
            }]
        }

    # Create a conversation record to store the title
    user_jid = user_data.get('user_jid', '')
    to_jid = user_data.get('to_jid', '')  # Channel where command was issued

    def _create_conversation():
        # Cancel any old pending conversations for this user
        IssueConversation.objects.filter(
            user_jid=user_jid,
            state=IssueConversation.State.AWAITING_APP
        ).update(state=IssueConversation.State.CANCELLED)

        # Create new conversation with title
        conv = IssueConversation.objects.create(
            user_jid=user_jid,
            channel_jid=to_jid,  # Store channel for replies
            state=IssueConversation.State.AWAITING_APP,
            issue_title=title.strip(),
            expires_at=timezone.now() + timedelta(minutes=10)
        )
        return conv.id

    conversation_id = await sync_to_async(_create_conversation)()

    # Build app buttons - clicking creates the issue immediately
    app_buttons = []
    for app in apps:
        app_buttons.append({
            'text': app.name,
            'value': f'quick_create:{conversation_id}:{app.id}',
            'style': 'Primary'
        })

    # Add cancel button
    app_buttons.append({
        'text': '❌ Cancel',
        'value': f'cancel_form:{conversation_id}',
        'style': 'Danger'
    })

    return {
        'head': {'text': '📝 Create Issue'},
        'body': [
            {
                'type': 'message',
                'text': f'**{title.strip()}**\n\nSelect the application:'
            },
            {
                'type': 'actions',
                'items': app_buttons
            }
        ]
    }


async def handle_app_selection(selection: str, user_data: dict, conversation) -> dict:
    """
    Process app selection and prompt for description.

    Args:
        selection: The user's selection (number string)
        user_data: Dictionary containing user info
        conversation: The IssueConversation instance

    Returns:
        Zoom message response dict
    """
    apps = await get_active_applications()

    # Parse the selection
    try:
        index = int(selection.strip()) - 1
        if 0 <= index < len(apps):
            selected_app = apps[index]
        else:
            return {
                'head': {'text': 'Invalid Selection'},
                'body': [{
                    'type': 'message',
                    'text': f"❌ Please enter a number between 1 and {len(apps)}."
                }]
            }
    except ValueError:
        return {
            'head': {'text': 'Invalid Selection'},
            'body': [{
                'type': 'message',
                'text': f"❌ Please enter a number between 1 and {len(apps)}."
            }]
        }

    # Update conversation state
    def _update_conversation():
        conversation.selected_app = selected_app
        conversation.state = IssueConversation.State.AWAITING_DESCRIPTION
        conversation.save()

    await sync_to_async(_update_conversation)()

    return {
        'head': {'text': 'Describe Issue'},
        'body': [{
            'type': 'message',
            'text': f"✅ Selected: *{selected_app.name}* ({selected_app.github_repo})\n\nDescribe the issue:\n_Reply with the issue description, or 'cancel' to abort._"
        }]
    }


async def handle_description_input(description: str, user_data: dict, conversation) -> dict:
    """
    Process description and create the GitHub issue.

    Args:
        description: The issue description
        user_data: Dictionary containing user info
        conversation: The IssueConversation instance

    Returns:
        Zoom message response dict
    """
    from bot_core.github_bot import github_bot

    if not github_bot or not github_bot.enabled:
        # Mark conversation as cancelled
        def _cancel():
            conversation.state = IssueConversation.State.CANCELLED
            conversation.save()
        await sync_to_async(_cancel)()

        return {
            'head': {'text': 'Error'},
            'body': [{
                'type': 'message',
                'text': '❌ GitHub integration is not configured. Please contact an admin.'
            }]
        }

    # Get the selected app
    def _get_app():
        return conversation.selected_app
    selected_app = await sync_to_async(_get_app)()

    if not selected_app:
        return {
            'head': {'text': 'Error'},
            'body': [{
                'type': 'message',
                'text': '❌ Application not found. Please start over with the issue command.'
            }]
        }

    # Create the issue
    user_name = user_data.get('user_name', 'Zoom User')
    body = f"{description}\n\n---\n_Submitted via Zoom by {user_name}_"

    issue_number, issue_url = await sync_to_async(github_bot.create_issue)(
        selected_app.github_repo,
        conversation.issue_title,
        body
    )

    if issue_number and issue_url:
        # Update conversation as completed
        def _complete():
            conversation.issue_description = description
            conversation.github_issue_number = issue_number
            conversation.github_issue_url = issue_url
            conversation.state = IssueConversation.State.COMPLETED
            conversation.save()
        await sync_to_async(_complete)()

        return {
            'head': {'text': 'Issue Created'},
            'body': [{
                'type': 'message',
                'text': f"✅ Issue #{issue_number} created!\n\n🔗 {issue_url}"
            }]
        }
    else:
        # Mark as cancelled on failure
        def _fail():
            conversation.state = IssueConversation.State.CANCELLED
            conversation.save()
        await sync_to_async(_fail)()

        return {
            'head': {'text': 'Error'},
            'body': [{
                'type': 'message',
                'text': '❌ Failed to create issue. The GitHub App may not have access to this repository.'
            }]
        }


async def handle_cancel_conversation(conversation) -> dict:
    """
    Cancel an active conversation.

    Args:
        conversation: The IssueConversation instance

    Returns:
        Zoom message response dict
    """
    def _cancel():
        conversation.state = IssueConversation.State.CANCELLED
        conversation.save()
    await sync_to_async(_cancel)()

    return {
        'head': {'text': 'Cancelled'},
        'body': [{
            'type': 'message',
            'text': '🚫 Issue creation cancelled.'
        }]
    }


async def handle_issue_detailed_command(title: str, user_data: dict, is_urgent: bool = False) -> dict:
    """
    Show structured form for enhanced issue creation.

    Args:
        title: The issue title
        user_data: Dictionary containing user_jid, user_name, etc.
        is_urgent: If True, skip validation

    Returns:
        Zoom message response dict
    """
    # Require a title
    if not title or not title.strip():
        return {
            'head': {'text': 'Create Issue'},
            'body': [{
                'type': 'message',
                'text': '📝 **Create a GitHub Issue (Enhanced)**\n\nUsage: `/issue detailed <title>`\n\nExample: `/issue detailed Login button broken on mobile`'
            }]
        }

    # Get active applications
    apps = await get_active_applications()

    if not apps:
        return {
            'head': {'text': 'Issue Creation'},
            'body': [{
                'type': 'message',
                'text': '❌ No applications configured. Please contact an admin.'
            }]
        }

    # Create conversation with enhanced mode enabled
    user_jid = user_data.get('user_jid', '')
    to_jid = user_data.get('to_jid', '')  # Channel where command was issued

    def _create_conversation():
        # Cancel any old pending conversations for this user
        IssueConversation.objects.filter(
            user_jid=user_jid,
            state__in=['awaiting_app', 'awaiting_form', 'awaiting_revision']
        ).update(state='cancelled')

        # Create new conversation
        conv = IssueConversation.objects.create(
            user_jid=user_jid,
            channel_jid=to_jid,  # Store channel for replies
            state='awaiting_form',
            issue_title=title.strip(),
            is_enhanced=True,
            is_urgent=is_urgent,
            expires_at=timezone.now() + timedelta(minutes=15)  # Longer for form filling
        )
        return conv.id

    conversation_id = await sync_to_async(_create_conversation)()

    # Build form message
    form_header = f'**{title.strip()}**\n\nPlease provide details to create a quality issue that developers can act on.'
    if is_urgent:
        form_header += '\n\n⚡ **URGENT** - Validation will be skipped.'

    return {
        'head': {'text': '📝 Create GitHub Issue (Enhanced)'},
        'body': [
            {
                'type': 'message',
                'text': form_header
            },
            {
                'type': 'fields',
                'items': [
                    {
                        'key': 'Title',
                        'value': title.strip(),
                        'editable': True,
                        'short': True
                    },
                    {
                        'key': 'Description',
                        'value': ' ',
                        'editable': True,
                        'short': False,
                        'placeholder': 'Describe the issue in detail...'
                    },
                    {
                        'key': 'Screenshot URLs',
                        'value': ' ',
                        'editable': True,
                        'short': True,
                        'placeholder': 'https://imgur.com/abc123.png (comma-separated)'
                    },
                    {
                        'key': 'Reproduction Steps',
                        'value': ' ',
                        'editable': True,
                        'short': False,
                        'placeholder': '1. Open the app\n2. Navigate to...\n3. Click on...'
                    },
                    {
                        'key': 'Environment',
                        'value': ' ',
                        'editable': True,
                        'short': True,
                        'placeholder': 'iOS 16.5, iPhone 13, Chrome 120'
                    },
                    {
                        'key': 'Expected Behavior',
                        'value': ' ',
                        'editable': True,
                        'short': False,
                        'placeholder': 'What should happen?'
                    },
                    {
                        'key': 'Actual Behavior',
                        'value': ' ',
                        'editable': True,
                        'short': False,
                        'placeholder': 'What actually happens?'
                    }
                ]
            },
            {
                'type': 'actions',
                'items': [
                    {
                        'text': '✅ Next: Select App',
                        'value': f'show_app_selection:{conversation_id}',
                        'style': 'Primary'
                    },
                    {
                        'text': '❌ Cancel',
                        'value': f'cancel_form:{conversation_id}',
                        'style': 'Danger'
                    }
                ]
            }
        ]
    }


async def handle_revise_issue(conversation_id: int, user_data: dict) -> dict:
    """
    Re-show form with pre-filled data for revision after validation feedback.

    Args:
        conversation_id: The conversation ID
        user_data: Dictionary containing user info

    Returns:
        Zoom message response dict
    """
    def _get_conv():
        return IssueConversation.objects.select_related('selected_app').filter(
            id=conversation_id
        ).first()

    conversation = await sync_to_async(_get_conv)()

    if not conversation:
        return {
            'head': {'text': 'Error'},
            'body': [{
                'type': 'message',
                'text': '❌ Session expired. Please start over with `/issue detailed`'
            }]
        }

    # Get apps for dropdown
    apps = await get_active_applications()
    app_options = [{"text": app.name, "value": str(app.id)} for app in apps]

    # Format screenshot URLs back to string
    screenshot_urls_str = ', '.join(conversation.screenshot_urls) if conversation.screenshot_urls else ''

    # Build selected item for dropdown
    selected_item = None
    if conversation.selected_app:
        selected_item = {
            'text': conversation.selected_app.name,
            'value': str(conversation.selected_app.id)
        }

    max_attempts = 3  # Should match IssueValidatorService.MAX_VALIDATION_ATTEMPTS
    attempts_text = f"Revision {conversation.validation_attempts}/{max_attempts}"

    return {
        'head': {'text': '✏️ Revise Issue'},
        'body': [
            {
                'type': 'message',
                'text': f'**{attempts_text}**\n\nUpdate the fields below and try again.'
            },
            {
                'type': 'fields',
                'items': [
                    {
                        'key': 'Title',
                        'value': conversation.issue_title,
                        'editable': True,
                        'short': True
                    },
                    {
                        'key': 'Description',
                        'value': conversation.description or ' ',
                        'editable': True,
                        'short': False,
                        'placeholder': 'Describe the issue in detail...'
                    },
                    {
                        'key': 'Screenshot URLs',
                        'value': screenshot_urls_str or ' ',
                        'editable': True,
                        'short': True,
                        'placeholder': 'https://imgur.com/abc.png'
                    },
                    {
                        'key': 'Reproduction Steps',
                        'value': conversation.reproduction_steps or ' ',
                        'editable': True,
                        'short': False,
                        'placeholder': '1. Step one\n2. Step two...'
                    },
                    {
                        'key': 'Environment',
                        'value': conversation.environment or ' ',
                        'editable': True,
                        'short': True,
                        'placeholder': 'iOS 16.5, Chrome 120'
                    },
                    {
                        'key': 'Expected Behavior',
                        'value': conversation.expected_behavior or ' ',
                        'editable': True,
                        'short': False
                    },
                    {
                        'key': 'Actual Behavior',
                        'value': conversation.actual_behavior or ' ',
                        'editable': True,
                        'short': False
                    }
                ]
            },
            {
                'type': 'select',
                'text': 'Application',
                'select_items': app_options,
                'selected_item': selected_item
            },
            {
                'type': 'actions',
                'items': [
                    {
                        'text': '✅ Submit Again',
                        'value': f'submit_enhanced_issue:{conversation.id}',
                        'style': 'Primary'
                    },
                    {
                        'text': '❌ Cancel',
                        'value': f'cancel_form:{conversation.id}',
                        'style': 'Danger'
                    }
                ]
            }
        ]
    }
