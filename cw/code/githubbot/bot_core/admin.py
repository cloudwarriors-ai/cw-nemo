from django.contrib import admin
from .models import Repository, WebhookEvent, ZoomCommand, Application, IssueConversation


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'github_id', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('full_name',)


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'repository', 'actor_login', 'action', 'created_at')
    list_filter = ('event_type', 'action', 'repository')
    search_fields = ('actor_login', 'title')
    date_hierarchy = 'created_at'


@admin.register(ZoomCommand)
class ZoomCommandAdmin(admin.ModelAdmin):
    list_display = ('command', 'user_name', 'user_jid', 'created_at')
    search_fields = ('command', 'user_name')
    date_hierarchy = 'created_at'


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('name', 'github_repo', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'github_repo', 'description')
    list_editable = ('is_active',)


@admin.register(IssueConversation)
class IssueConversationAdmin(admin.ModelAdmin):
    list_display = ('issue_title', 'user_jid', 'state', 'selected_app', 'github_issue_number', 'created_at')
    list_filter = ('state', 'selected_app')
    search_fields = ('issue_title', 'user_jid', 'issue_description')
    date_hierarchy = 'created_at'
    readonly_fields = ('github_issue_url', 'github_issue_number')
