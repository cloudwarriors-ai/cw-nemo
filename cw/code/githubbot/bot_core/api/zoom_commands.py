"""
Zoom slash command handling.

Handles Zoom bot commands including:
- help: Show available commands
- events: Show recent GitHub events
- chat: Chat with AI assistant
- whoami: Show user's Zoom info
- issue: Create a GitHub issue
- cancel: Cancel active conversation
"""
import json
import logging

from django.http import HttpResponse, HttpResponseServerError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from asgiref.sync import sync_to_async

from bot_core.models import WebhookEvent, ZoomCommand, IssueConversation
from bot_core.handlers.conversation import (
    get_active_conversation,
    handle_issue_command,
    handle_app_selection,
    handle_description_input,
    handle_cancel_conversation,
)

logger = logging.getLogger(__name__)


async def handle_zoom_command(command: str, user_data: dict) -> dict:
    """
    Handle different Zoom bot commands.

    Args:
        command: The command string (e.g., "help", "events", "chat Hello")
        user_data: Dictionary containing user_jid, user_name, raw_data, etc.

    Returns:
        Zoom message response dict
    """
    logger.info(f"Handling command: {command}")

    user_jid = user_data.get('user_jid', '')
    user_name = user_data.get('user_name', '')

    # Create command record
    await sync_to_async(ZoomCommand.objects.create)(
        user_jid=user_jid,
        user_name=user_name,
        command=command,
        raw_data=user_data
    )

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

    # Split command into parts
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower() if parts else ''
    args = parts[1] if len(parts) > 1 else ''

    if cmd == 'help':
        return _handle_help()

    elif cmd == 'issue':
        return await _handle_issue(args, user_data)

    elif cmd == 'events':
        return await _handle_events()

    elif cmd == 'whoami':
        return _handle_whoami(user_data)

    elif cmd == 'chat':
        return await _handle_chat(args, user_data)

    else:
        return _handle_unknown(cmd)


def _handle_help() -> dict:
    """Handle the help command."""
    return {
        'head': {
            'text': 'Available Commands'
        },
        'body': [{
            'type': 'message',
            'text': """Here are the available commands:
• help - Show this help message
• events - Show recent GitHub events
• issue "<title>" - Create a GitHub issue
• chat <message> - Chat with the AI assistant
• whoami - Show your Zoom user ID and channel ID
• cancel - Cancel current issue creation"""
        }]
    }


async def _handle_issue(args: str, user_data: dict) -> dict:
    """Handle the issue command."""
    if not args:
        return {
            'head': {'text': 'Issue Command'},
            'body': [{
                'type': 'message',
                'text': 'Usage: issue "<title>"\nExample: issue "Login button broken on mobile"'
            }]
        }

    # Extract title (handle quoted or unquoted)
    title = args.strip()
    if title.startswith('"') and title.endswith('"'):
        title = title[1:-1]
    elif title.startswith("'") and title.endswith("'"):
        title = title[1:-1]

    return await handle_issue_command(title, user_data)


async def _handle_events() -> dict:
    """Handle the events command."""
    events_query = WebhookEvent.objects.select_related('repository').order_by('-created_at')[:5]
    events = await sync_to_async(lambda: list(events_query))()

    if not events:
        return {
            'head': {
                'text': 'Recent Events'
            },
            'body': [{
                'type': 'message',
                'text': 'No recent events found.'
            }]
        }

    # Format events
    event_list = []
    for event in events:
        summary = await sync_to_async(event.get_summary)()
        event_list.append(f"• {summary} ({event.repository.full_name})")

    return {
        'head': {
            'text': 'Recent Events'
        },
        'body': [{
            'type': 'message',
            'text': '\n'.join(event_list)
        }]
    }


def _handle_whoami(user_data: dict) -> dict:
    """Handle the whoami command."""
    # Get user's Zoom info from the raw data
    payload = user_data.get('raw_data', {}).get('payload', {})

    # Extract command data
    user_jid = payload.get('userJid')
    user_name = payload.get('userName')
    channel_id = payload.get('toJid')  # Channel ID is in toJid for channel messages
    robot_jid = payload.get('robotJid')
    account_id = payload.get('accountId')

    return {
        'head': {
            'text': 'Your Zoom Information'
        },
        'body': [{
            'type': 'message',
            'text': f"""👤 *User Information*
• Name: {user_name}
• User JID: {user_jid}
• Channel ID: {channel_id}
• Robot JID: {robot_jid}
• Account ID: {account_id}"""
        }]
    }


async def _handle_chat(args: str, user_data: dict) -> dict:
    """Handle the chat command."""
    if not args:
        logger.info("Chat command received with no message")
        return {
            'head': {
                'text': 'Chat'
            },
            'body': [{
                'type': 'message',
                'text': 'Please provide a message to chat with the AI assistant.'
            }]
        }

    try:
        logger.info(f"Processing chat command: {args[:100]}...")
        from bot_core.llm_bot import llm_bot

        # Get response from LLM
        context = {
            'user_name': user_data.get('name', 'Unknown User'),
            'platform': 'Zoom',
            'command': 'chat'
        }
        logger.info(f"Sending to LLM with context: {context}")

        response = await llm_bot.generate_response(args, context)
        logger.info(f"Received LLM response ({len(response)} chars)")
        logger.debug(f"Full LLM response: {response}")

        formatted_response = {
            'head': {
                'text': 'AI Response'
            },
            'body': [{
                'type': 'message',
                'text': response
            }]
        }
        logger.debug(f"Formatted Zoom response: {json.dumps(formatted_response, indent=2)}")
        return formatted_response

    except Exception as e:
        logger.error(f"Error in chat command: {str(e)}", exc_info=True)
        return {
            'head': {
                'text': 'Error'
            },
            'body': [{
                'type': 'message',
                'text': "Sorry, I couldn't generate a response at this time."
            }]
        }


def _handle_unknown(cmd: str) -> dict:
    """Handle unknown commands."""
    return {
        'head': {
            'text': 'Unknown Command'
        },
        'body': [{
            'type': 'message',
            'text': f'Unknown command: {cmd}\nType "help" to see available commands.'
        }]
    }


@csrf_exempt
@require_POST
async def zoom_command(request):
    """
    Handle Zoom slash commands.

    Endpoint: POST /command/
    """
    try:
        # Parse the JSON body
        body_data = json.loads(request.body.decode('utf-8'))
        payload = body_data.get('payload', {})

        # Extract command data
        to_jid = payload.get('toJid')  # Channel where command was sent
        command_data = {
            'user_jid': payload.get('userJid'),
            'user_name': payload.get('userName'),
            'command': payload.get('cmd'),
            'raw_data': body_data
        }

        logger.info(f"Received Zoom command: {command_data['command']} from {command_data['user_name']} in channel {to_jid}")

        # Handle the command
        response = await handle_zoom_command(command_data['command'], command_data)
        logger.info(f"Command handler response: {response}")

        # Get the Zoom bot instance
        from bot_core.zoom_bot import zoom_bot

        # If we have a response and the bot is initialized
        if response and zoom_bot:
            # Send the response to the channel where the command was received
            await sync_to_async(zoom_bot.send_message)(response, to_jid)

        # Return 200 OK for Zoom
        return HttpResponse(status=200)

    except Exception as e:
        logger.error(f"Error handling Zoom command: {str(e)}", exc_info=True)
        return HttpResponseServerError('Internal server error')
