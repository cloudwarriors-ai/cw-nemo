"""
GitHub webhook endpoint and processing.

Handles GitHub webhook events including:
- Signature verification
- Event type routing (push, pull_request, issues, issue_comment)
- Database storage
- Zoom notifications
- WebSocket broadcasting
"""
import hmac
import hashlib
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseBadRequest, HttpResponseServerError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from channels.layers import get_channel_layer
from asgiref.sync import sync_to_async

from bot_core.models import Repository, WebhookEvent, TrackedIssue

logger = logging.getLogger(__name__)


def verify_github_signature(body: bytes, signature: str) -> bool:
    """
    Verify the GitHub webhook signature.

    Args:
        body: Raw request body bytes
        signature: The X-Hub-Signature-256 header value

    Returns:
        True if signature is valid, False otherwise
    """
    webhook_secret = settings.GITHUB_WEBHOOK_SECRET.encode('utf-8')
    expected = hmac.new(
        key=webhook_secret,
        msg=body,
        digestmod=hashlib.sha256
    ).hexdigest()
    expected_signature = f'sha256={expected}'
    return hmac.compare_digest(expected_signature, signature)


async def _handle_container_heartbeat(payload: dict, channel_layer) -> HttpResponse:
    """Handle container heartbeat notifications."""
    logger.info(f"Received container heartbeat notification: {payload}")

    data = payload.get('data', {})
    container_name = data.get('container', 'unknown')
    status = data.get('status', 'unknown')

    # Broadcast to websocket group
    await channel_layer.group_send(
        'github_events',
        {
            'type': 'container_heartbeat',
            'data': data
        }
    )

    # Also send to Zoom if unhealthy
    if status == 'unhealthy':
        try:
            from bot_core.zoom_bot import zoom_bot

            severity = data.get('severity', 'WARNING')
            use_prod_channel = (severity == 'CRITICAL' and
                                hasattr(zoom_bot, 'prod_channel_id') and
                                zoom_bot.prod_channel_id)

            message = f"*⚠️ CONTAINER ALERT [{severity}]*\n\n{data.get('summary', 'Container health check failed')}"

            if use_prod_channel:
                zoom_bot.send_message_to_production(message)
            else:
                zoom_bot.send_message(message)
        except Exception as e:
            logger.error(f"Failed to send container alert to Zoom: {str(e)}")

    return HttpResponse('OK')


def _build_event_message(event_type: str, payload: dict, repository_full_name: str, sender_username: str) -> tuple:
    """
    Build the event message and extract metadata.

    Returns:
        Tuple of (message, action, title, html_url, extra_fields)
    """
    message = f"*New GitHub Event from {repository_full_name}*\n\n"
    action = ''
    title = ''
    html_url = None
    extra_fields = {}

    if event_type == 'push':
        commits = payload.get('commits', [])
        ref = payload.get('ref', '').split('/')[-1]
        action = 'push'
        title = f"Push to {ref} ({len(commits)} commits)"
        message += f"*Event:* 📦 Push to {ref}\n"
        message += f"*By:* {sender_username}\n"
        message += f"*Commits:* {len(commits)}\n"
        if commits:
            message += "\n*Latest Commits:*\n"
            for commit in commits[:3]:
                message += f"• {commit.get('message', '').splitlines()[0]}\n"
        if payload.get('compare'):
            message += f"\n🔗 [View Changes]({payload['compare']})"

        # Extra fields for push events
        repo_url = payload.get('repository', {}).get('html_url')
        if repo_url and ref:
            html_url = f"{repo_url}/commits/{ref}"
        extra_fields = {
            'ref': payload.get('ref'),
            'before': payload.get('before'),
            'after': payload.get('after'),
            'commits_count': len(commits)
        }

    elif event_type == 'pull_request':
        pr = payload.get('pull_request', {})
        action = payload.get('action', '')
        title = pr.get('title', '')
        number = pr.get('number', '')
        html_url = pr.get('html_url')
        message += f"*Event:* 🤝 PR #{number} {action}\n"
        message += f"*Title:* {title}\n"
        message += f"*By:* {sender_username}\n"
        if html_url:
            message += f"\n🔗 [View PR]({html_url})"

    elif event_type == 'issues':
        issue = payload.get('issue', {})
        action = payload.get('action', '')
        title = issue.get('title', '')
        number = issue.get('number', '')
        html_url = issue.get('html_url')
        message += f"*Event:* 🐛 Issue #{number} {action}\n"
        message += f"*Title:* {title}\n"
        message += f"*By:* {sender_username}\n"
        if html_url:
            message += f"\n🔗 [View Issue]({html_url})"

    elif event_type == 'issue_comment':
        issue = payload.get('issue', {})
        comment = payload.get('comment', {})
        action = 'commented'
        title = f"Comment on issue: {issue.get('title', '')}"
        number = issue.get('number', '')
        html_url = comment.get('html_url')
        message += f"*Event:* 💬 New comment on Issue #{number}\n"
        message += f"*Issue:* {title}\n"
        message += f"*By:* {sender_username}\n"
        if html_url:
            message += f"\n🔗 [View Comment]({html_url})"

    return message, action, title, html_url, extra_fields


async def _forward_issue_event_to_project_pulse(
    payload: dict,
    repository_full_name: str,
    sender_username: str
):
    """
    Forward issue events to Project Pulse for tracked issues.

    Checks if the issue is tracked and forwards status updates.
    """
    from bot_core.services.status_mapper import (
        github_to_project_pulse_status,
        should_notify_project_pulse,
        extract_assignees,
    )
    from bot_core.services.project_pulse_client import project_pulse_client

    if not project_pulse_client or not project_pulse_client.enabled:
        logger.debug("Project Pulse client not enabled, skipping forwarding")
        return

    issue = payload.get('issue', {})
    action = payload.get('action', '')
    issue_number = issue.get('number')

    if not issue_number:
        return

    # Check if we should notify Project Pulse for this event
    labels = issue.get('labels', [])
    if not should_notify_project_pulse('issues', action, labels):
        logger.debug(f"Action '{action}' does not trigger Project Pulse update")
        return

    # Look up the tracked issue
    def _get_tracked_issue():
        return TrackedIssue.objects.filter(
            github_repo=repository_full_name,
            github_issue_number=issue_number,
            status=TrackedIssue.Status.ACTIVE
        ).first()

    tracked_issue = await sync_to_async(_get_tracked_issue)()

    if not tracked_issue:
        logger.debug(f"Issue #{issue_number} in {repository_full_name} is not tracked")
        return

    # Only forward events for Project Pulse-originated tickets
    # (Zoom tickets don't need status updates sent back)
    if tracked_issue.source != TrackedIssue.Source.PROJECT_PULSE:
        logger.debug(f"Issue #{issue_number} originated from {tracked_issue.source}, not forwarding")
        return

    if not tracked_issue.project_pulse_ticket_id:
        logger.warning(f"TrackedIssue {tracked_issue.id} has no project_pulse_ticket_id")
        return

    # Map GitHub state/labels to Project Pulse status
    state = issue.get('state', 'open')
    new_status = github_to_project_pulse_status(labels, state, action)

    # Build event data for context
    github_event_data = {
        'action': action,
        'actor': sender_username,
        'labels': [{'name': l.get('name', '')} for l in labels],
        'assignees': extract_assignees(issue),
        'state': state,
    }

    logger.info(f"Forwarding issue #{issue_number} status update to Project Pulse: {new_status.value}")

    # Send update to Project Pulse (async-safe call)
    success = await sync_to_async(project_pulse_client.update_ticket_status)(
        tracked_issue.project_pulse_ticket_id,
        new_status,
        github_event_data
    )

    if success:
        logger.info(f"Successfully forwarded status update for ticket {tracked_issue.project_pulse_ticket_id}")
    else:
        logger.error(f"Failed to forward status update for ticket {tracked_issue.project_pulse_ticket_id}")


@csrf_exempt
@require_POST
async def webhook(request):
    """
    Handle GitHub webhook events.

    Supported event types: push, pull_request, issues, issue_comment
    Also handles container heartbeat notifications.
    """
    try:
        # Parse the request body
        try:
            if 'payload' in request.POST:
                payload = json.loads(request.POST['payload'])
            else:
                raw_body = request.body.decode('utf-8')
                payload = json.loads(raw_body)

            # Check if this is a container heartbeat notification
            if payload.get('event_type') == 'container_heartbeat':
                channel_layer = get_channel_layer()
                return await _handle_container_heartbeat(payload, channel_layer)

        except json.JSONDecodeError:
            logger.error("Failed to decode JSON payload", exc_info=True)
            return HttpResponseBadRequest('Invalid JSON')

        # Verify signature
        signature = request.headers.get('X-Hub-Signature-256', '')
        if not verify_github_signature(request.body, signature):
            return HttpResponseForbidden('Invalid signature')

        # Debug logging
        content_type = request.headers.get('Content-Type', '')
        raw_body = request.body.decode('utf-8')
        logger.debug(f"Webhook Content-Type: {content_type}")
        logger.debug(f"Raw body: {raw_body[:200]}...")

        # Re-parse payload (in case we need it after signature verification)
        if 'payload' in request.POST:
            payload = json.loads(request.POST['payload'])
        else:
            payload = json.loads(raw_body)

        # Extract event type and repository info
        event_type = request.headers.get('X-GitHub-Event', 'unknown')

        # Only process specific event types
        allowed_events = {'push', 'pull_request', 'issues', 'issue_comment'}
        if event_type not in allowed_events:
            logger.info(f"Skipping event type: {event_type} (not in allowed events)")
            return HttpResponse('OK - Event type not tracked')

        repo_data = payload.get('repository', {})
        repository_full_name = repo_data.get('full_name', '')
        repository_id = repo_data.get('id', 0)
        sender_username = payload.get('sender', {}).get('login', 'unknown')
        avatar_url = payload.get('sender', {}).get('avatar_url', '')

        logger.info(f"Processing {event_type} event from {sender_username} for {repository_full_name}")

        # Build message and extract metadata
        message, action, title, html_url, extra_fields = _build_event_message(
            event_type, payload, repository_full_name, sender_username
        )

        # Send Zoom notification
        try:
            from bot_core.zoom_bot import zoom_bot
            from bot_core.llm_bot import llm_bot

            # Get witty comment from LLM
            prompt = f"""You are a witty developer assistant. Generate a short, funny, and engaging comment about this GitHub event:
Event Type: {event_type}
Repository: {repository_full_name}
Actor: {sender_username}
Action: {action}
Title: {title}

Keep the response very short (1-2 lines) and make it fun! Use developer humor if appropriate."""

            try:
                witty_comment = await sync_to_async(llm_bot.generate_response)(prompt)
                if witty_comment:
                    message += f"\n\n🤖 *AI Commentary:*\n{witty_comment}"
            except Exception as e:
                logger.error(f"Failed to generate LLM comment: {str(e)}", exc_info=True)

            zoom_bot.send_message(message)
            logger.info("Successfully sent notification to Zoom")
        except Exception as e:
            logger.error(f"Failed to send Zoom notification: {str(e)}", exc_info=True)

        # Get or create repository
        repository, _ = await sync_to_async(Repository.objects.get_or_create)(
            github_id=repository_id,
            defaults={'full_name': repository_full_name}
        )

        # Create webhook event
        event_kwargs = {
            'event_type': event_type,
            'repository': repository,
            'actor_login': sender_username,
            'actor_avatar_url': avatar_url,
            'action': action,
            'title': title,
            'payload': payload,
            'html_url': html_url,
        }

        # Add push-specific fields
        if event_type == 'push':
            event_kwargs.update({
                'ref': extra_fields.get('ref'),
                'before': extra_fields.get('before'),
                'after': extra_fields.get('after'),
                'commits_count': extra_fields.get('commits_count'),
            })

        webhook_event = await sync_to_async(WebhookEvent.objects.create)(**event_kwargs)

        logger.info(f"Stored webhook event: {webhook_event.id} - {event_type} - {title}")

        # Forward issue events to Project Pulse for tracked issues
        if event_type == 'issues':
            try:
                await _forward_issue_event_to_project_pulse(
                    payload, repository_full_name, sender_username
                )
            except Exception as e:
                # Log but don't fail the webhook on Project Pulse errors
                logger.error(f"Error forwarding to Project Pulse: {str(e)}", exc_info=True)

        # Broadcast to websocket group
        channel_layer = get_channel_layer()
        event_data = {
            'id': webhook_event.id,
            'summary': await sync_to_async(webhook_event.get_summary)(),
            'repository': repository.full_name,
            'created_at': webhook_event.created_at.isoformat(),
            'actor_avatar': webhook_event.actor_avatar_url,
            'html_url': webhook_event.html_url,
            'type': webhook_event.event_type,
        }
        await channel_layer.group_send(
            'github_events',
            {
                'type': 'github_event',
                'data': event_data
            }
        )

        return HttpResponse('OK')

    except json.JSONDecodeError:
        logger.error("Failed to decode JSON payload", exc_info=True)
        return HttpResponseBadRequest('Invalid JSON')
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return HttpResponseServerError('Internal server error')
