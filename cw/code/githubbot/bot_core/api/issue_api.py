"""
API endpoints for external services (Project Pulse) to create and manage GitHub issues.

Endpoints:
- POST /api/issues/ - Create a GitHub issue
- GET /api/applications/ - List available applications
- GET /api/issues/<id>/ - Get tracked issue details
"""
import os
import json
import logging
import hmac
import hashlib

from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from asgiref.sync import sync_to_async

from bot_core.models import Application, TrackedIssue

logger = logging.getLogger(__name__)

# API secret for authentication
API_SECRET = os.environ.get('PROJECT_PULSE_API_SECRET', '')


def verify_api_key(request) -> bool:
    """
    Verify the API key from the request header.

    Args:
        request: Django request object

    Returns:
        True if API key is valid, False otherwise
    """
    if not API_SECRET:
        logger.warning("PROJECT_PULSE_API_SECRET not configured - API authentication disabled")
        return True  # Allow if not configured (for development)

    api_key = request.headers.get('X-API-Key', '')
    if not api_key:
        return False

    return hmac.compare_digest(api_key, API_SECRET)


@csrf_exempt
@require_POST
async def create_issue_api(request):
    """
    API endpoint for external services (Project Pulse) to create GitHub issues.

    Request body:
    {
        "title": "Issue title",
        "description": "Issue description",
        "application_id": 1,  // or "application_name": "App Name"
        "project_pulse_ticket_id": "PP-123",  // Optional, for tracking
        "submitter_name": "John Doe"
    }

    Response:
    {
        "success": true,
        "tracked_issue_id": 1,
        "github_issue_number": 42,
        "github_issue_url": "https://github.com/org/repo/issues/42"
    }
    """
    # Verify API key
    if not verify_api_key(request):
        return JsonResponse({'error': 'Invalid or missing API key'}, status=401)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Validate required fields
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    submitter_name = data.get('submitter_name', 'Project Pulse')

    if not title:
        return JsonResponse({'error': 'title is required'}, status=400)

    # Get application by ID or name
    application_id = data.get('application_id')
    application_name = data.get('application_name')

    if not application_id and not application_name:
        return JsonResponse({'error': 'application_id or application_name is required'}, status=400)

    def _get_application():
        if application_id:
            return Application.objects.filter(id=application_id, is_active=True).first()
        else:
            return Application.objects.filter(name__iexact=application_name, is_active=True).first()

    app = await sync_to_async(_get_application)()

    if not app:
        return JsonResponse({'error': 'Application not found or inactive'}, status=404)

    # Optional tracking fields
    project_pulse_ticket_id = data.get('project_pulse_ticket_id')

    # CREATE-FIRST PATTERN:
    # 1. Create TrackedIssue with status='pending'
    def _create_tracked_issue():
        return TrackedIssue.objects.create(
            github_repo=app.github_repo,
            status=TrackedIssue.Status.PENDING,
            source=TrackedIssue.Source.PROJECT_PULSE,
            project_pulse_ticket_id=project_pulse_ticket_id,
            title=title,
            description=description,
            created_by=submitter_name
        )

    tracked_issue = await sync_to_async(_create_tracked_issue)()

    # 2. Try to create GitHub issue
    from bot_core.github_bot import github_bot

    if not github_bot or not github_bot.enabled:
        # Delete the tracked issue and return error
        await sync_to_async(tracked_issue.delete)()
        return JsonResponse({
            'error': 'GitHub integration is not configured'
        }, status=503)

    # Format the issue body
    body = f"{description}\n\n---\n_Submitted via Project Pulse by {submitter_name}_"

    issue_number, issue_url = await sync_to_async(github_bot.create_issue)(
        app.github_repo,
        title,
        body
    )

    # 3. Handle result
    if issue_number and issue_url:
        # Success - update TrackedIssue
        def _update_success():
            tracked_issue.github_issue_number = issue_number
            tracked_issue.github_issue_url = issue_url
            tracked_issue.status = TrackedIssue.Status.ACTIVE
            tracked_issue.save()

        await sync_to_async(_update_success)()

        logger.info(f"Created GitHub issue #{issue_number} for Project Pulse ticket {project_pulse_ticket_id}")

        return JsonResponse({
            'success': True,
            'tracked_issue_id': tracked_issue.id,
            'github_issue_number': issue_number,
            'github_issue_url': issue_url,
            'github_repo': app.github_repo
        }, status=201)
    else:
        # GitHub creation failed - delete TrackedIssue and return error
        await sync_to_async(tracked_issue.delete)()

        logger.error(f"Failed to create GitHub issue for Project Pulse ticket {project_pulse_ticket_id}")

        return JsonResponse({
            'error': 'Failed to create GitHub issue',
            'details': 'The GitHub API returned an error. Check repository access.'
        }, status=502)


@csrf_exempt
@require_GET
async def list_applications(request):
    """
    List available applications for issue creation.

    Response:
    {
        "applications": [
            {
                "id": 1,
                "name": "Mobile App",
                "github_repo": "org/mobile-app",
                "description": "iOS and Android mobile application"
            }
        ]
    }
    """
    # Verify API key
    if not verify_api_key(request):
        return JsonResponse({'error': 'Invalid or missing API key'}, status=401)

    def _get_apps():
        return list(Application.objects.filter(is_active=True).values(
            'id', 'name', 'github_repo', 'description'
        ))

    apps = await sync_to_async(_get_apps)()

    return JsonResponse({'applications': apps})


@csrf_exempt
@require_GET
async def get_tracked_issue(request, issue_id):
    """
    Get details of a tracked issue.

    Response:
    {
        "id": 1,
        "title": "Issue title",
        "github_repo": "org/repo",
        "github_issue_number": 42,
        "github_issue_url": "https://...",
        "status": "active",
        "source": "project_pulse",
        "project_pulse_ticket_id": "PP-123",
        "created_at": "2025-01-30T12:00:00Z"
    }
    """
    # Verify API key
    if not verify_api_key(request):
        return JsonResponse({'error': 'Invalid or missing API key'}, status=401)

    def _get_issue():
        return TrackedIssue.objects.filter(id=issue_id).first()

    issue = await sync_to_async(_get_issue)()

    if not issue:
        return JsonResponse({'error': 'Tracked issue not found'}, status=404)

    return JsonResponse({
        'id': issue.id,
        'title': issue.title,
        'description': issue.description,
        'github_repo': issue.github_repo,
        'github_issue_number': issue.github_issue_number,
        'github_issue_url': issue.github_issue_url,
        'status': issue.status,
        'source': issue.source,
        'project_pulse_ticket_id': issue.project_pulse_ticket_id,
        'zoom_conversation_id': issue.zoom_conversation_id,
        'created_by': issue.created_by,
        'created_at': issue.created_at.isoformat(),
        'updated_at': issue.updated_at.isoformat()
    })


@csrf_exempt
@require_GET
async def get_tracked_issue_by_github(request, repo, issue_number):
    """
    Get tracked issue by GitHub repo and issue number.

    URL: /api/issues/github/<repo>/<issue_number>/
    Example: /api/issues/github/org/repo/42/

    Response: Same as get_tracked_issue
    """
    # Verify API key
    if not verify_api_key(request):
        return JsonResponse({'error': 'Invalid or missing API key'}, status=401)

    def _get_issue():
        return TrackedIssue.objects.filter(
            github_repo=repo,
            github_issue_number=issue_number
        ).first()

    issue = await sync_to_async(_get_issue)()

    if not issue:
        return JsonResponse({'error': 'Tracked issue not found'}, status=404)

    return JsonResponse({
        'id': issue.id,
        'title': issue.title,
        'description': issue.description,
        'github_repo': issue.github_repo,
        'github_issue_number': issue.github_issue_number,
        'github_issue_url': issue.github_issue_url,
        'status': issue.status,
        'source': issue.source,
        'project_pulse_ticket_id': issue.project_pulse_ticket_id,
        'zoom_conversation_id': issue.zoom_conversation_id,
        'created_by': issue.created_by,
        'created_at': issue.created_at.isoformat(),
        'updated_at': issue.updated_at.isoformat()
    })
