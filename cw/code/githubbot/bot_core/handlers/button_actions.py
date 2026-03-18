"""
Button action handlers for Zoom interactive messages.

Handles various button click actions including:
- create_issue: Full form submission with title, app, and description
- quick_create: One-click issue creation with just app selection
- cancel_form: Cancel the issue creation
- select_app: Select an application from dropdown
- submit_issue: Submit issue with description from form
- cancel: Cancel with conversation ID
"""
import logging

from asgiref.sync import sync_to_async

from bot_core.models import Application, IssueConversation, TrackedIssue

logger = logging.getLogger(__name__)


async def _sync_to_project_pulse(
    title: str,
    description: str,
    github_repo: str,
    github_issue_number: int,
    github_issue_url: str,
    application_name: str,
    user_name: str,
    conversation_id: int
):
    """
    Sync a Zoom-created issue to Project Pulse.

    Creates a TrackedIssue record and calls Project Pulse API to create a ticket.
    Errors are logged but don't fail the main operation.
    """
    try:
        from bot_core.services.project_pulse_client import project_pulse_client

        # 1. Create TrackedIssue record
        def _create_tracked_issue():
            return TrackedIssue.objects.create(
                github_repo=github_repo,
                github_issue_number=github_issue_number,
                github_issue_url=github_issue_url,
                status=TrackedIssue.Status.ACTIVE,
                source=TrackedIssue.Source.ZOOM_CHAT,
                zoom_conversation_id=conversation_id,
                title=title,
                description=description or title,
                created_by=user_name
            )

        tracked_issue = await sync_to_async(_create_tracked_issue)()
        logger.info(f"Created TrackedIssue {tracked_issue.id} for GitHub issue #{github_issue_number}")

        # 2. Call Project Pulse API to create ticket (if client is enabled)
        if project_pulse_client and project_pulse_client.enabled:
            result = await sync_to_async(project_pulse_client.create_ticket)(
                title=title,
                description=description or title,
                github_repo=github_repo,
                github_issue_number=github_issue_number,
                github_issue_url=github_issue_url,
                application_name=application_name,
                source='ZoomChat',
                submitter_name=user_name
            )

            if result:
                # Update TrackedIssue with Project Pulse ticket ID
                ticket_id = result.get('ticketId') or result.get('id')
                if ticket_id:
                    def _update_tracked():
                        tracked_issue.project_pulse_ticket_id = str(ticket_id)
                        tracked_issue.save()
                    await sync_to_async(_update_tracked)()
                    logger.info(f"Linked TrackedIssue {tracked_issue.id} to Project Pulse ticket {ticket_id}")
            else:
                logger.warning(f"Failed to create Project Pulse ticket for TrackedIssue {tracked_issue.id}")
        else:
            logger.debug("Project Pulse client not enabled, skipping ticket creation")

    except Exception as e:
        # Log but don't fail - the GitHub issue was created successfully
        logger.error(f"Error syncing to Project Pulse: {str(e)}", exc_info=True)


async def handle_button_action(action_value: str, user_data: dict) -> dict:
    """
    Handle button click actions from Zoom interactive messages.

    Args:
        action_value: The button value in format "action_type:param1:param2"
        user_data: Dictionary containing user info and form data

    Returns:
        Zoom message response dict or None
    """
    logger.info(f"Handling button action: {action_value}")

    parts = action_value.split(':')
    action_type = parts[0] if parts else ''

    if action_type == 'create_issue':
        return await _handle_create_issue(parts, user_data)

    elif action_type == 'quick_create' and len(parts) >= 3:
        return await _handle_quick_create(parts, user_data)

    elif action_type == 'cancel_form':
        return await _handle_cancel_form(parts, user_data)

    elif action_type == 'select_app' and len(parts) >= 3:
        return await _handle_select_app(parts, user_data)

    elif action_type == 'submit_issue' and len(parts) >= 2:
        return await _handle_submit_issue(parts, user_data)

    elif action_type == 'submit_enhanced_issue' and len(parts) >= 2:
        return await _handle_submit_enhanced_issue(parts, user_data)

    elif action_type == 'revise_issue' and len(parts) >= 2:
        return await _handle_revise_issue(parts, user_data)

    elif action_type == 'show_app_selection' and len(parts) >= 2:
        return await _handle_show_app_selection(parts, user_data)

    elif action_type == 'create_enhanced_with_app' and len(parts) >= 3:
        return await _handle_create_enhanced_with_app(parts, user_data)

    elif action_type == 'cancel' and len(parts) >= 2:
        return await _handle_cancel(parts, user_data)

    return None


async def _handle_create_issue(parts: list, user_data: dict) -> dict:
    """Handle create_issue button action (full form submission)."""
    # Get conversation_id from button value (create_issue:123)
    conversation_id = int(parts[1]) if len(parts) > 1 else None

    if not conversation_id:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ Session expired. Please start over with /issue'}]
        }

    # Get the conversation with stored form data
    def _get_conversation():
        return IssueConversation.objects.select_related('selected_app').filter(id=conversation_id).first()
    conversation = await sync_to_async(_get_conversation)()

    if not conversation:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ Session expired. Please start over with /issue'}]
        }

    title = conversation.issue_title.strip() if conversation.issue_title else ''
    description = conversation.issue_description.strip() if conversation.issue_description else ''
    app = conversation.selected_app

    logger.info(f"Create issue from conversation {conversation_id}: title={title}, app={app.name if app else 'None'}, desc={description[:50] if description else 'empty'}...")

    # Validate
    if not title:
        return {
            'head': {'text': 'Missing Title'},
            'body': [{'type': 'message', 'text': '❌ Please enter an issue title and try again.'}]
        }
    if not app:
        return {
            'head': {'text': 'Missing Application'},
            'body': [{'type': 'message', 'text': '❌ Please select an application and try again.'}]
        }
    if not description:
        return {
            'head': {'text': 'Missing Description'},
            'body': [{'type': 'message', 'text': '❌ Please enter a description and try again.'}]
        }

    # Create the GitHub issue
    from bot_core.github_bot import github_bot

    if not github_bot or not github_bot.enabled:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ GitHub integration is not configured.'}]
        }

    user_name = user_data.get('user_name', 'Zoom User')
    body = f"{description}\n\n---\n_Submitted via Zoom by {user_name}_"

    issue_number, issue_url = await sync_to_async(github_bot.create_issue)(
        app.github_repo,
        title,
        body
    )

    if issue_number and issue_url:
        # Update conversation as completed
        def _complete():
            conversation.github_issue_number = issue_number
            conversation.github_issue_url = issue_url
            conversation.state = IssueConversation.State.COMPLETED
            conversation.save()
        await sync_to_async(_complete)()

        # Sync to Project Pulse (create TrackedIssue and PP ticket)
        await _sync_to_project_pulse(
            title=title,
            description=description,
            github_repo=app.github_repo,
            github_issue_number=issue_number,
            github_issue_url=issue_url,
            application_name=app.name,
            user_name=user_name,
            conversation_id=conversation_id
        )

        return {
            'head': {'text': 'Issue Created! 🎉'},
            'body': [{
                'type': 'message',
                'text': f"✅ Issue #{issue_number} created in *{app.name}*\n\n📝 *{title}*\n\n🔗 {issue_url}"
            }]
        }
    else:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': f'❌ Failed to create issue in {app.github_repo}. Check GitHub access.'}]
        }


async def _handle_quick_create(parts: list, user_data: dict) -> dict:
    """
    Handle quick_create button action.

    Quick create: click app button → create issue immediately
    Format: quick_create:<conversation_id>:<app_id>
    """
    conversation_id = int(parts[1])
    app_id = int(parts[2])

    # Get the original message ID so we can delete it after
    original_message_id = user_data.get('message_id')
    to_jid = user_data.get('to_jid')

    # Get conversation and app
    def _get_data():
        conv = IssueConversation.objects.filter(id=conversation_id).first()
        app = Application.objects.filter(id=app_id, is_active=True).first()
        return conv, app
    conversation, app = await sync_to_async(_get_data)()

    if not conversation or not app:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ Session expired. Please start over with /issue'}]
        }

    title = conversation.issue_title
    if not title:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ No title found. Please start over with /issue <title>'}]
        }

    # Create the GitHub issue
    from bot_core.github_bot import github_bot

    if not github_bot or not github_bot.enabled:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ GitHub integration is not configured.'}]
        }

    user_name = user_data.get('user_name', 'Zoom User')
    # Use title as both title and description for simplicity
    body = f"{title}\n\n---\n_Submitted via Zoom by {user_name}_"

    issue_number, issue_url = await sync_to_async(github_bot.create_issue)(
        app.github_repo,
        title,
        body
    )

    if issue_number and issue_url:
        # Update conversation as completed
        def _complete():
            conversation.selected_app = app
            conversation.github_issue_number = issue_number
            conversation.github_issue_url = issue_url
            conversation.state = IssueConversation.State.COMPLETED
            conversation.save()
        await sync_to_async(_complete)()

        # Sync to Project Pulse (create TrackedIssue and PP ticket)
        await _sync_to_project_pulse(
            title=title,
            description=title,  # Quick create uses title as description
            github_repo=app.github_repo,
            github_issue_number=issue_number,
            github_issue_url=issue_url,
            application_name=app.name,
            user_name=user_name,
            conversation_id=conversation_id
        )

        # Delete the original button message to clean up
        if original_message_id and to_jid:
            from bot_core.issue_maker_bot import issue_maker_bot
            if issue_maker_bot and issue_maker_bot.enabled:
                await sync_to_async(issue_maker_bot.delete_message)(original_message_id, to_jid)

        return {
            'head': {'text': 'Issue Created! 🎉'},
            'body': [{
                'type': 'message',
                'text': f"✅ Issue #{issue_number} created in **{app.name}**\n\n🔗 {issue_url}"
            }]
        }
    else:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': f'❌ Failed to create issue. Check GitHub access to {app.github_repo}.'}]
        }


async def _handle_cancel_form(parts: list, user_data: dict) -> dict:
    """Handle cancel_form button action."""
    # Cancel the conversation if we have an ID
    conversation_id = int(parts[1]) if len(parts) > 1 else None
    if conversation_id:
        def _cancel():
            conv = IssueConversation.objects.filter(id=conversation_id).first()
            if conv:
                conv.state = IssueConversation.State.CANCELLED
                conv.save()
        await sync_to_async(_cancel)()

    # Delete the original button message
    original_message_id = user_data.get('message_id')
    to_jid = user_data.get('to_jid')
    if original_message_id and to_jid:
        from bot_core.issue_maker_bot import issue_maker_bot
        if issue_maker_bot and issue_maker_bot.enabled:
            await sync_to_async(issue_maker_bot.delete_message)(original_message_id, to_jid)

    return {
        'head': {'text': 'Cancelled'},
        'body': [{'type': 'message', 'text': '🚫 Issue creation cancelled.'}]
    }


async def _handle_select_app(parts: list, user_data: dict) -> dict:
    """Handle select_app button action."""
    # Format: select_app:conversation_id:app_id
    conversation_id = int(parts[1])
    app_id = int(parts[2])

    # Get conversation and app
    def _get_data():
        conv = IssueConversation.objects.filter(id=conversation_id).first()
        app = Application.objects.filter(id=app_id).first()
        return conv, app
    conversation, app = await sync_to_async(_get_data)()

    if not conversation or not app:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ Session expired. Please start over with /issue'}]
        }

    if conversation.is_expired():
        return {
            'head': {'text': 'Session Expired'},
            'body': [{'type': 'message', 'text': '⏰ Session expired. Please start over with /issue'}]
        }

    # Update conversation with selected app and prompt for description
    def _update():
        conversation.selected_app = app
        conversation.state = IssueConversation.State.AWAITING_DESCRIPTION
        conversation.save()
    await sync_to_async(_update)()

    return {
        'head': {'text': 'Describe Issue'},
        'body': [
            {
                'type': 'message',
                'text': f"✅ Selected: *{app.name}*\n\n📝 Issue: *{conversation.issue_title}*"
            },
            {
                'type': 'form',
                'items': [
                    {
                        'key': 'description',
                        'value': '',
                        'editable': True,
                        'placeholder': 'Describe the issue in detail...'
                    }
                ]
            },
            {
                'type': 'actions',
                'items': [
                    {
                        'text': '✅ Create Issue',
                        'value': f"submit_issue:{conversation.id}",
                        'style': 'Primary'
                    },
                    {
                        'text': '❌ Cancel',
                        'value': f"cancel:{conversation.id}",
                        'style': 'Danger'
                    }
                ]
            }
        ]
    }


async def _handle_submit_issue(parts: list, user_data: dict) -> dict:
    """Handle submit_issue button action (with form data)."""
    # Format: submit_issue:conversation_id
    # Form data comes in user_data
    conversation_id = int(parts[1])
    form_data = user_data.get('form_data', {})
    description = form_data.get('description', '').strip()

    if not description:
        return {
            'head': {'text': 'Missing Description'},
            'body': [{'type': 'message', 'text': '❌ Please enter a description for the issue.'}]
        }

    # Get conversation
    def _get_conv():
        return IssueConversation.objects.select_related('selected_app').filter(id=conversation_id).first()
    conversation = await sync_to_async(_get_conv)()

    if not conversation or not conversation.selected_app:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ Session expired. Please start over with /issue'}]
        }

    if conversation.is_expired():
        return {
            'head': {'text': 'Session Expired'},
            'body': [{'type': 'message', 'text': '⏰ Session expired. Please start over with /issue'}]
        }

    # Create the GitHub issue
    from bot_core.github_bot import github_bot

    if not github_bot or not github_bot.enabled:
        def _cancel():
            conversation.state = IssueConversation.State.CANCELLED
            conversation.save()
        await sync_to_async(_cancel)()
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ GitHub integration is not configured.'}]
        }

    user_name = user_data.get('user_name', 'Zoom User')
    body = f"{description}\n\n---\n_Submitted via Zoom by {user_name}_"

    issue_number, issue_url = await sync_to_async(github_bot.create_issue)(
        conversation.selected_app.github_repo,
        conversation.issue_title,
        body
    )

    if issue_number and issue_url:
        def _complete():
            conversation.issue_description = description
            conversation.github_issue_number = issue_number
            conversation.github_issue_url = issue_url
            conversation.state = IssueConversation.State.COMPLETED
            conversation.save()
        await sync_to_async(_complete)()

        # Sync to Project Pulse (create TrackedIssue and PP ticket)
        await _sync_to_project_pulse(
            title=conversation.issue_title,
            description=description,
            github_repo=conversation.selected_app.github_repo,
            github_issue_number=issue_number,
            github_issue_url=issue_url,
            application_name=conversation.selected_app.name,
            user_name=user_name,
            conversation_id=conversation_id
        )

        return {
            'head': {'text': 'Issue Created! 🎉'},
            'body': [{
                'type': 'message',
                'text': f"✅ Issue #{issue_number} created in *{conversation.selected_app.name}*\n\n🔗 {issue_url}"
            }]
        }
    else:
        def _fail():
            conversation.state = IssueConversation.State.CANCELLED
            conversation.save()
        await sync_to_async(_fail)()

        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ Failed to create issue. The GitHub App may not have access to this repository.'}]
        }


async def _handle_cancel(parts: list, user_data: dict) -> dict:
    """Handle cancel:<id> button action."""
    # Format: cancel:conversation_id
    conversation_id = int(parts[1])

    def _cancel():
        conv = IssueConversation.objects.filter(id=conversation_id).first()
        if conv:
            conv.state = IssueConversation.State.CANCELLED
            conv.save()
        return conv
    await sync_to_async(_cancel)()

    return {
        'head': {'text': 'Cancelled'},
        'body': [{'type': 'message', 'text': '🚫 Issue creation cancelled.'}]
    }


async def _handle_submit_enhanced_issue(parts: list, user_data: dict) -> dict:
    """
    Handle enhanced issue submission with async validation.

    This queues a Celery task and returns immediately to avoid Zoom webhook timeout.
    """
    from django.db import transaction

    conversation_id = int(parts[1])
    form_data = user_data.get('form_data', {})
    selected_item = user_data.get('selected_item', {})

    # Get conversation with locking to prevent race conditions
    def _get_and_update_conv():
        with transaction.atomic():
            # Lock row for update
            conv = IssueConversation.objects.select_for_update().filter(
                id=conversation_id
            ).first()

            if not conv:
                return None, "Conversation not found"

            if conv.is_expired():
                return None, "Session expired"

            # Check if already validating
            if conv.state == 'validating':
                return None, "Already validating this issue"

            # Extract and update conversation with form data
            conv.issue_title = form_data.get('Title', conv.issue_title).strip()
            conv.description = form_data.get('Description', '').strip()

            # Parse screenshot URLs
            urls_string = form_data.get('Screenshot URLs', '').strip()
            if urls_string:
                urls = [u.strip() for u in urls_string.split(',') if u.strip()]
                conv.screenshot_urls = urls
            else:
                conv.screenshot_urls = []

            conv.reproduction_steps = form_data.get('Reproduction Steps', '').strip()
            conv.environment = form_data.get('Environment', '').strip()
            conv.expected_behavior = form_data.get('Expected Behavior', '').strip()
            conv.actual_behavior = form_data.get('Actual Behavior', '').strip()

            # Get selected app
            app_id = selected_item.get('value')
            if app_id:
                try:
                    conv.selected_app = Application.objects.get(id=int(app_id))
                except Application.DoesNotExist:
                    return None, "Selected application not found"

            if not conv.selected_app:
                return None, "Please select an application"

            # Update state to validating
            conv.state = 'validating'
            conv.save()

            return conv, None

    conversation, error = await sync_to_async(_get_and_update_conv)()

    if error:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': f'❌ {error}'}]
        }

    # Validate screenshot URLs synchronously (SSRF check is fast)
    if conversation.screenshot_urls:
        from bot_core.services.screenshot_validator import validate_screenshot_urls
        import asyncio

        urls_valid, url_error = await validate_screenshot_urls(conversation.screenshot_urls)
        if not urls_valid:
            # Revert state
            def _revert():
                conversation.state = 'awaiting_form'
                conversation.save()
            await sync_to_async(_revert)()

            return {
                'head': {'text': 'Invalid Screenshot URL'},
                'body': [{'type': 'message', 'text': f'❌ {url_error}\n\nPlease use imgur.com, GitHub, or Google Drive URLs.'}]
            }

    # Queue async validation task (returns immediately)
    from bot_core.tasks import validate_and_notify_issue
    validate_and_notify_issue.delay(conversation.id)

    # Return immediate response to avoid webhook timeout
    if conversation.is_urgent:
        message = '✅ Creating issue (validation skipped - urgent flag set)...'
    else:
        message = '🤖 Analyzing your issue...\n\nThis may take a few seconds. You\'ll receive a notification when complete.'

    return {
        'head': {'text': 'Processing...'},
        'body': [{'type': 'message', 'text': message}]
    }


async def _handle_revise_issue(parts: list, user_data: dict) -> dict:
    """Handle revise_issue button - re-show form with pre-filled data."""
    conversation_id = int(parts[1])

    from bot_core.handlers.conversation import handle_revise_issue
    return await handle_revise_issue(conversation_id, user_data)


async def _handle_show_app_selection(parts: list, user_data: dict) -> dict:
    """
    Handle show_app_selection - save form data and show app buttons.

    This is step 2 of the enhanced flow: after filling the form, show app selection.
    """
    conversation_id = int(parts[1])
    form_data = user_data.get('form_data', {})

    # Get conversation (fields already saved by field edit events - don't overwrite!)
    def _get_conv():
        conv = IssueConversation.objects.filter(id=conversation_id).first()
        return conv

    conversation = await sync_to_async(_get_conv)()

    if not conversation:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ Session expired. Please start over with `/issue detailed`'}]
        }

    # Get apps and show selection buttons
    from bot_core.handlers.conversation import get_active_applications
    apps = await get_active_applications()

    if not apps:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ No applications configured. Please contact an admin.'}]
        }

    # Build app buttons
    app_buttons = []
    for app in apps:
        app_buttons.append({
            'text': app.name,
            'value': f'create_enhanced_with_app:{conversation.id}:{app.id}',
            'style': 'Primary'
        })

    # Add cancel button
    app_buttons.append({
        'text': '❌ Cancel',
        'value': f'cancel_form:{conversation.id}',
        'style': 'Danger'
    })

    return {
        'head': {'text': '📝 Select Application'},
        'body': [
            {
                'type': 'message',
                'text': f"**{conversation.issue_title}**\n\nSelect which application this issue is for:"
            },
            {
                'type': 'actions',
                'items': app_buttons
            }
        ]
    }


async def _handle_create_enhanced_with_app(parts: list, user_data: dict) -> dict:
    """
    Handle final submission with app selection for enhanced issue.

    Format: create_enhanced_with_app:<conversation_id>:<app_id>
    """
    conversation_id = int(parts[1])
    app_id = int(parts[2])

    # Get conversation and app
    def _get_data():
        conv = IssueConversation.objects.filter(id=conversation_id).first()
        app = Application.objects.filter(id=app_id, is_active=True).first()
        return conv, app

    conversation, app = await sync_to_async(_get_data)()

    if not conversation or not app:
        return {
            'head': {'text': 'Error'},
            'body': [{'type': 'message', 'text': '❌ Session expired. Please start over with `/issue detailed`'}]
        }

    # Update conversation with selected app
    def _update_app():
        conversation.selected_app = app
        conversation.state = 'validating'
        conversation.save()

    await sync_to_async(_update_app)()

    # Validate screenshot URLs (SSRF check)
    if conversation.screenshot_urls:
        from bot_core.services.screenshot_validator import validate_screenshot_urls

        urls_valid, url_error = await validate_screenshot_urls(conversation.screenshot_urls)
        if not urls_valid:
            # Revert state
            def _revert():
                conversation.state = 'awaiting_form'
                conversation.save()
            await sync_to_async(_revert)()

            return {
                'head': {'text': 'Invalid Screenshot URL'},
                'body': [{'type': 'message', 'text': f'❌ {url_error}\n\nPlease use imgur.com, GitHub, or Google Drive URLs.'}]
            }

    # Queue async validation task (returns immediately)
    logger.info(f"Queueing validation task for conversation {conversation.id}")

    try:
        from bot_core.tasks import validate_and_notify_issue
        task = validate_and_notify_issue.delay(conversation.id)
        logger.info(f"Task queued successfully: {task.id}")
    except Exception as e:
        logger.error(f"Failed to queue validation task: {e}", exc_info=True)
        # Fall back to direct creation if Celery fails
        from bot_core.tasks import _create_github_issue
        _create_github_issue(conversation)
        return {
            'head': {'text': 'Issue Created'},
            'body': [{'type': 'message', 'text': '✅ Issue created (validation skipped - task queue unavailable)'}]
        }

    # Return immediate response
    if conversation.is_urgent:
        message = '✅ Creating issue (validation skipped - urgent flag set)...'
    else:
        message = '🤖 Analyzing your issue with AI...\n\nThis may take a few seconds. You\'ll receive a notification when complete.'

    return {
        'head': {'text': 'Processing...'},
        'body': [{'type': 'message', 'text': message}]
    }
