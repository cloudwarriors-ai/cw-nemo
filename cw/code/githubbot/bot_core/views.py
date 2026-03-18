"""
Views for the bot_core application.

This module now imports from the refactored modules in bot_core.api and bot_core.handlers
for better code organization. All original functionality is preserved.
"""
import json
import logging

from django.shortcuts import render
from django.http import JsonResponse, HttpResponseServerError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from asgiref.sync import sync_to_async

from .models import Repository, WebhookEvent, ZoomCommand, Application, IssueConversation

# Import from refactored modules
from .api.github_webhook import webhook, verify_github_signature
from .api.zoom_commands import zoom_command, handle_zoom_command
from .api.issue_maker import issue_command, handle_issue_maker_command

# Import handlers for use in this module
from .handlers.conversation import (
    get_active_conversation,
    get_active_applications,
    handle_issue_command,
    handle_app_selection,
    handle_description_input,
    handle_cancel_conversation,
)
from .handlers.button_actions import handle_button_action

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
    'webhook',
    'verify_github_signature',
    'zoom_command',
    'handle_zoom_command',
    'issue_command',
    'handle_issue_maker_command',
    'list_events',
    'webhook_list',
    'analyze_event',
    'get_active_conversation',
    'get_active_applications',
    'handle_issue_command',
    'handle_app_selection',
    'handle_description_input',
    'handle_cancel_conversation',
    'handle_button_action',
]


def list_events(request):
    """List recent webhook events for the web dashboard."""
    # Get all events ordered by created_at descending
    events = WebhookEvent.objects.select_related('repository').order_by('-created_at')[:50]

    # Format events for display
    formatted_events = []
    for event in events:
        # Get the URL from the payload based on event type
        html_url = event.html_url  # Use the stored html_url from our model

        formatted_event = {
            'id': event.id,
            'summary': event.get_summary(),
            'repository': event.repository.full_name,
            'created_at': event.created_at,
            'actor_avatar': event.actor_avatar_url,
            'html_url': html_url,
            'type': event.event_type,
        }
        formatted_events.append(formatted_event)

    return render(request, 'bot_core/list.html', {
        'events': formatted_events,
        'title': 'Recent GitHub Events'
    })


def webhook_list(request):
    """Paginated list of webhook events with filtering."""
    # Get event type filter
    event_type = request.GET.get('event_type')

    # Base queryset
    queryset = WebhookEvent.objects.select_related('repository').order_by('-created_at')

    # Apply event type filter if specified
    if event_type:
        queryset = queryset.filter(event_type=event_type)

    # Get unique event types for the filter dropdown
    event_types = WebhookEvent.objects.values_list('event_type', flat=True).distinct()

    # Pagination
    paginator = Paginator(queryset, 10)  # Show 10 webhooks per page
    page = request.GET.get('page')
    webhook_events = paginator.get_page(page)

    context = {
        'webhook_events': webhook_events,
        'event_types': event_types,
        'selected_event_type': event_type,
    }

    return render(request, 'bot_core/webhook_list.html', context)


@csrf_exempt
@require_POST
async def analyze_event(request):
    """Analyze a GitHub event using LLM."""
    try:
        data = json.loads(request.body)
        event_id = data.get('event_id')

        if not event_id:
            return JsonResponse({'error': 'event_id is required'}, status=400)

        # Get the event using sync_to_async with a lambda to handle the queryset
        event_query = WebhookEvent.objects.select_related('repository').filter(id=event_id)
        event = await sync_to_async(lambda: event_query.first())()

        if not event:
            return JsonResponse({'error': 'Event not found'}, status=404)

        from .llm_bot import llm_bot

        context = {
            'repository': event.repository.full_name,
            'event_type': event.event_type,
            'actor': event.actor_login,
            'action': event.action,
            'title': event.title
        }

        if event.event_type == 'pull_request':
            analysis = await llm_bot.generate_response(
                "Analyze this pull request and provide insights about its impact and suggested review areas.",
                context
            )
        elif event.event_type == 'issues':
            analysis = await llm_bot.generate_response(
                "Analyze this issue and suggest how to handle it.",
                context
            )
        elif event.event_type == 'push':
            analysis = await llm_bot.generate_response(
                "Analyze these changes and their potential impact.",
                context
            )
        else:
            analysis = await llm_bot.generate_response(
                "Provide insights about this event.",
                context
            )

        return JsonResponse({
            'analysis': analysis
        })

    except WebhookEvent.DoesNotExist:
        return JsonResponse({'error': 'Event not found'}, status=404)
    except Exception as e:
        logger.error(f"Error analyzing event: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)


# Health Check Endpoints
from django.views.decorators.http import require_GET


@require_GET
async def health_check(request):
    """Basic health check - is app running?"""
    return JsonResponse({'status': 'ok'})


@require_GET
async def readiness_check(request):
    """Readiness check - are all dependencies available?"""
    checks = {}

    # Check database
    try:
        await sync_to_async(Repository.objects.count)()
        checks['database'] = 'ok'
    except Exception as e:
        checks['database'] = f'error: {str(e)}'

    # Check Redis
    try:
        import redis
        import os
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        redis_client = redis.from_url(redis_url, decode_responses=True)
        redis_client.ping()
        checks['redis'] = 'ok'
    except Exception as e:
        checks['redis'] = f'error: {str(e)}'

    # Check OpenAI
    try:
        from .llm_bot import llm_bot
        if llm_bot.api_key:
            checks['openai'] = 'ok'
        else:
            checks['openai'] = 'disabled'
    except Exception as e:
        checks['openai'] = f'error: {str(e)}'

    # Check Celery (via Redis broker)
    try:
        from github_bot_project.celery import app as celery_app
        celery_app.control.inspect().stats()
        checks['celery'] = 'ok'
    except Exception as e:
        checks['celery'] = f'error: {str(e)}'

    # Overall status
    all_ok = all(
        status == 'ok' for status in checks.values()
        if status != 'disabled'
    )
    status_code = 200 if all_ok else 503

    return JsonResponse({
        'status': 'ready' if all_ok else 'not_ready',
        'checks': checks
    }, status=status_code)
