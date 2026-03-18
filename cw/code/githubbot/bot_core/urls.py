from django.urls import path, re_path
from . import views
from .api import issue_api

app_name = 'bot_core'  # Add namespace

urlpatterns = [
    path('webhook/', views.webhook, name='webhook'),  # GitHub needs trailing slash
    path('events/', views.list_events, name='list_events'),
    path('webhooks/', views.webhook_list, name='webhook_list'),
    re_path(r'^command/?$', views.zoom_command, name='zoom_command'),  # Works with or without slash
    re_path(r'^issue-command/?$', views.issue_command, name='issue_command'),  # GitHub Issue Maker bot

    # New API endpoints for Project Pulse integration
    path('api/issues/', issue_api.create_issue_api, name='create_issue_api'),
    path('api/issues/<int:issue_id>/', issue_api.get_tracked_issue, name='get_tracked_issue'),
    path('api/issues/github/<path:repo>/<int:issue_number>/', issue_api.get_tracked_issue_by_github, name='get_tracked_issue_by_github'),
    path('api/applications/', issue_api.list_applications, name='list_applications'),

    # Health check endpoints
    path('health/', views.health_check, name='health_check'),
    path('health/ready/', views.readiness_check, name='readiness_check'),
]
