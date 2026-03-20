"""
GitHub Issue Maker Zoom app endpoint.

Handles the dedicated Issue Maker Zoom app including:
- Slash commands (/issue)
- Button click actions
- Form field edits
- Dropdown selections
"""
import json
import logging

from django.http import HttpResponse, HttpResponseServerError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from asgiref.sync import sync_to_async

from bot_core.models import Application, IssueConversation
from bot_core.handlers.conversation import (
    get_active_conversation,
    handle_issue_command,
    handle_app_selection,
    handle_description_input,
    handle_cancel_conversation,
)
from bot_core.handlers.button_actions import handle_button_action

logger = logging.getLogger(__name__)


async def handle_issue_maker_command(command: str, user_data: dict) -> dict:
    """
    Handle commands from the GitHub Issue Maker Zoom app.

    Supports:
    - /issue <title> - Quick create with app selection
    - /issue detailed <title> - Enhanced create with full form
    - /issue --urgent <title> - Quick create, skip validation

    Args:
        command: The command string (title from /issue)
        user_data: Dictionary containing user_jid, user_name, to_jid, etc.

    Returns:
        Zoom message response dict
    """
    logger.info(f"Issue Maker handling command: {command}")

    user_jid = user_data.get('user_jid', '')
    user_name = user_data.get('user_name', '')
    to_jid = user_data.get('to_jid', '')

    # Check for active conversation first
    active_conversation = await get_active_conversation(user_jid)
    if active_conversation:
        cmd_lower = command.strip().lower()

        # Handle cancel
        if cmd_lower == 'cancel':
            return await handle_cancel_conversation(active_conversation)

        # Route based on conversation state
        if active_conversation.state == IssueConversation.State.AWAITING_APP:
            return await handle_app_selection(command, user_data, active_conversation)
        elif active_conversation.state == IssueConversation.State.AWAITING_DESCRIPTION:
            return await handle_description_input(command, user_data, active_conversation)

    # No active conversation - parse command flags
    command_clean = command.strip()

    # Remove surrounding quotes if present
    if command_clean and ((command_clean.startswith('"') and command_clean.endswith('"')) or
                          (command_clean.startswith("'") and command_clean.endswith("'"))):
        command_clean = command_clean[1:-1]

    # Check for flags
    is_detailed = False
    is_urgent = False

    # Parse "detailed" flag
    if command_clean.lower().startswith('detailed '):
        is_detailed = True
        title = command_clean[9:].strip()  # Remove "detailed " prefix
    # Parse "--urgent" flag
    elif command_clean.startswith('--urgent '):
        is_urgent = True
        title = command_clean[9:].strip()  # Remove "--urgent " prefix
    else:
        title = command_clean

    # Route to appropriate handler
    if is_detailed or is_urgent:
        from bot_core.handlers.conversation import handle_issue_detailed_command
        return await handle_issue_detailed_command(title, user_data, is_urgent=is_urgent)
    else:
        # Default: quick create
        return await handle_issue_command(title, user_data)


async def _handle_field_edit(field_edit_item: dict, user_jid: str):
    """Handle field edit event (user editing form fields)."""
    logger.info(f"Field edit event: {field_edit_item}")

    # Store field values - find most recent active conversation for this user
    def _update_fields():
        conv = IssueConversation.objects.filter(
            user_jid=user_jid,
            state__in=['awaiting_app', 'awaiting_form', 'awaiting_revision']
        ).order_by('-created_at').first()
        if conv:
            # Update fields based on what was edited
            key = field_edit_item.get('key', '')
            new_value = field_edit_item.get('newValue', '').strip()

            logger.info(f"Updating field '{key}' to '{new_value[:50]}...' for conversation {conv.id}")

            # Map field keys to model fields
            if key == 'Title':
                conv.issue_title = new_value
            elif key == 'Description':
                conv.description = new_value
                conv.issue_description = new_value  # Also update legacy field
            elif key == 'Screenshot URLs':
                # Parse comma-separated URLs
                if new_value and new_value.strip():
                    urls = [u.strip() for u in new_value.split(',') if u.strip()]
                    conv.screenshot_urls = urls
                else:
                    conv.screenshot_urls = []
            elif key == 'Reproduction Steps':
                conv.reproduction_steps = new_value
            elif key == 'Environment':
                conv.environment = new_value
            elif key == 'Expected Behavior':
                conv.expected_behavior = new_value
            elif key == 'Actual Behavior':
                conv.actual_behavior = new_value

            conv.save()
            logger.info(f"Saved field '{key}' for conversation {conv.id}")

    await sync_to_async(_update_fields)()


async def _handle_selected_item(selected_item: dict, user_jid: str):
    """Handle dropdown select event."""
    logger.info(f"Dropdown select event: {selected_item}")

    # Store selected app
    def _update_selection():
        conv = IssueConversation.objects.filter(
            user_jid=user_jid,
            state=IssueConversation.State.AWAITING_APP
        ).order_by('-created_at').first()
        if conv:
            app_id = selected_item.get('value', '')
            if app_id:
                try:
                    app = Application.objects.get(id=int(app_id))
                    conv.selected_app = app
                    conv.save()
                    logger.info(f"Updated conversation {conv.id}: selected_app={app.name}")
                except (ValueError, Application.DoesNotExist):
                    logger.error(f"Invalid app_id: {app_id}")

    await sync_to_async(_update_selection)()


@csrf_exempt
@require_POST
async def issue_command(request):
    """
    Handle GitHub Issue Maker Zoom slash commands and button clicks.

    Endpoint: POST /issue-command/
    """
    try:
        body_data = json.loads(request.body.decode('utf-8'))
        payload = body_data.get('payload', {})

        logger.info(f"Issue Maker request received")
        logger.debug(f"Full payload: {json.dumps(payload, indent=2)}")

        # Extract common data
        user_jid = payload.get('userJid')
        user_name = payload.get('userName')
        to_jid = payload.get('toJid')
        robot_jid = payload.get('robotJid')
        message_id = payload.get('messageId')

        user_data = {
            'user_jid': user_jid,
            'user_name': user_name,
            'to_jid': to_jid,
            'robot_jid': robot_jid,
            'message_id': message_id,
            'raw_data': body_data
        }

        response = None

        # Log payload keys to understand what type of event this is
        logger.debug(f"Payload keys: {list(payload.keys())}")

        # Check if this is a button click (actionItem)
        action_item = payload.get('actionItem')

        # Check if this is a field edit event (user editing form fields)
        field_edit_item = payload.get('fieldEditItem')

        # Check if this is a dropdown select event
        selected_item = payload.get('selectedItem')

        if action_item:
            # Button was clicked - process the action
            action_value = action_item.get('value', '')
            logger.info(f"Button clicked: {action_value} by {user_name}")

            # Form data is in the 'original' object which contains the message with user edits
            original = payload.get('original', {})
            logger.debug(f"Original message: {json.dumps(original, indent=2)}")

            # Extract form fields from the original message body
            form_fields = {}
            selected_item_data = None
            original_body = original.get('body', [])

            logger.debug(f"Processing original body with {len(original_body)} items")

            for item in original_body:
                item_type = item.get('type')
                logger.debug(f"Processing item type: {item_type}")

                if item_type == 'fields':
                    # Extract editable field values
                    for field in item.get('items', []):
                        key = field.get('key', '')
                        value = field.get('value', '')
                        form_fields[key] = value
                elif item_type == 'select':
                    # Extract selected dropdown value
                    logger.debug(f"Select item data: {json.dumps(item, indent=2)}")
                    selected_item_data = item.get('selected_item', {})
                    if not selected_item_data:
                        # Try alternative key names
                        selected_item_data = item.get('selectedItem', {})
                    logger.debug(f"Found selected_item: {selected_item_data}")

            user_data['form_data'] = form_fields
            user_data['selected_item'] = selected_item_data or {}

            logger.debug(f"Extracted form data: {form_fields}")
            logger.debug(f"Extracted selected item: {selected_item_data}")

            response = await handle_button_action(action_value, user_data)

        elif field_edit_item:
            # User is editing form fields - store the values
            logger.info(f"Field edit event from {user_name}: {field_edit_item}")
            await _handle_field_edit(field_edit_item, user_jid)
            # Return 200 OK without sending a message
            return HttpResponse(status=200)

        elif selected_item:
            # User selected from dropdown - store the selection
            logger.info(f"Dropdown select event from {user_name}: {selected_item}")
            await _handle_selected_item(selected_item, user_jid)
            # Return 200 OK without sending a message
            return HttpResponse(status=200)

        else:
            # Regular slash command
            command = payload.get('cmd', '')
            if command is not None:  # Only process if there's actually a command
                logger.info(f"Issue Maker command: '{command}' from {user_name} in channel {to_jid}")
                response = await handle_issue_maker_command(command, user_data)
            else:
                # Unknown event type - just acknowledge
                logger.info(f"Unknown event type, acknowledging without response")
                return HttpResponse(status=200)

        logger.info(f"Issue Maker response: {response}")

        # Get the Issue Maker bot instance
        from bot_core.issue_maker_bot import issue_maker_bot

        if response and issue_maker_bot and issue_maker_bot.enabled:
            await sync_to_async(issue_maker_bot.send_message)(response, to_jid)

        return HttpResponse(status=200)

    except Exception as e:
        logger.error(f"Error handling Issue Maker command: {str(e)}", exc_info=True)
        return HttpResponseServerError('Internal server error')
