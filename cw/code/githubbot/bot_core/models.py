from django.db import models
from django.utils import timezone
from datetime import timedelta

# Create your models here.


class Application(models.Model):
    """Maps application names to GitHub repos for issue creation"""
    name = models.CharField(max_length=100, unique=True)
    github_repo = models.CharField(max_length=200)  # e.g., "org/mobile-app"
    description = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.github_repo})"

    class Meta:
        ordering = ['name']


class IssueConversation(models.Model):
    """Tracks multi-step conversation state for issue creation"""
    class State(models.TextChoices):
        AWAITING_APP = 'awaiting_app', 'Awaiting App Selection'
        AWAITING_DESCRIPTION = 'awaiting_description', 'Awaiting Description'
        AWAITING_FORM = 'awaiting_form', 'Awaiting Form Submission'
        VALIDATING = 'validating', 'AI Validating'
        AWAITING_REVISION = 'awaiting_revision', 'Awaiting Revision'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    user_jid = models.CharField(max_length=200, db_index=True)
    channel_jid = models.CharField(max_length=200, blank=True)  # Where to send replies
    state = models.CharField(max_length=30, choices=State.choices, default=State.AWAITING_APP)
    issue_title = models.CharField(max_length=500)
    selected_app = models.ForeignKey(Application, on_delete=models.SET_NULL, null=True, blank=True)

    # Legacy field (kept for backward compatibility)
    issue_description = models.TextField(blank=True)

    # Enhanced issue fields (optional, used for detailed mode)
    description = models.TextField(blank=True)
    screenshot_urls = models.JSONField(default=list, blank=True)  # List of URL strings
    reproduction_steps = models.TextField(blank=True)
    environment = models.TextField(blank=True)
    expected_behavior = models.TextField(blank=True)
    actual_behavior = models.TextField(blank=True)

    # Validation tracking
    validation_attempts = models.IntegerField(default=0)
    validation_score = models.IntegerField(null=True, blank=True)  # 0-100
    validation_feedback = models.JSONField(null=True, blank=True)  # Store full validation result
    validation_feedback_rating = models.IntegerField(null=True, blank=True)  # User feedback: 1=helpful, -1=not helpful

    # Feature tracking
    is_enhanced = models.BooleanField(default=False)  # Track if detailed mode was used
    is_urgent = models.BooleanField(default=False)  # --urgent flag to skip validation

    # GitHub result
    github_issue_url = models.URLField(blank=True)
    github_issue_number = models.IntegerField(null=True, blank=True)

    # Timestamps
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Issue '{self.issue_title[:50]}' by {self.user_jid} ({self.state})"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def is_expired(self):
        return timezone.now() > self.expires_at

    def is_active(self):
        return self.state in [
            self.State.AWAITING_APP,
            self.State.AWAITING_DESCRIPTION,
            self.State.AWAITING_FORM,
            self.State.AWAITING_REVISION
        ] and not self.is_expired()

    class Meta:
        ordering = ['-created_at']

class Repository(models.Model):
    full_name = models.CharField(max_length=200, unique=True)
    github_id = models.IntegerField(unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name

class WebhookEvent(models.Model):
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE)
    event_type = models.CharField(max_length=50)
    payload = models.JSONField()
    processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Actor who triggered the event
    actor_login = models.CharField(max_length=100, null=True, blank=True)
    actor_avatar_url = models.URLField(max_length=500, null=True, blank=True)
    
    # Common fields for most events
    ref = models.CharField(max_length=200, null=True, blank=True)  # Branch/tag name
    action = models.CharField(max_length=50, null=True, blank=True)  # e.g. opened, closed, merged
    title = models.CharField(max_length=500, null=True, blank=True)  # PR/Issue title
    number = models.IntegerField(null=True, blank=True)  # PR/Issue number
    html_url = models.URLField(max_length=500, null=True, blank=True)  # Link to the event
    body = models.TextField(null=True, blank=True)  # PR/Issue description or commit message
    
    # For commits
    before = models.CharField(max_length=40, null=True, blank=True)  # Previous commit SHA
    after = models.CharField(max_length=40, null=True, blank=True)  # New commit SHA
    commits_count = models.IntegerField(null=True, blank=True)  # Number of commits
    
    # For PR events
    base_ref = models.CharField(max_length=200, null=True, blank=True)  # Target branch
    head_ref = models.CharField(max_length=200, null=True, blank=True)  # Source branch
    merged = models.BooleanField(null=True)  # Whether PR was merged

    def __str__(self):
        return f"{self.event_type} - {self.repository.full_name}"
        
    def get_summary(self):
        """Returns a human-readable summary of the event"""
        if self.event_type == 'push':
            branch = self.ref.replace('refs/heads/', '') if self.ref else 'unknown branch'
            commits = f"{self.commits_count} commit{'s' if self.commits_count != 1 else ''}"
            return f"Push to {branch} ({commits}) by {self.actor_login}"
        return f"{self.event_type} by {self.actor_login}"


class ZoomCommand(models.Model):
    """Store Zoom bot command events"""
    user_jid = models.CharField(max_length=200)
    user_name = models.CharField(max_length=200)
    command = models.CharField(max_length=500)
    raw_data = models.JSONField()  # Store the full request data for analysis
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.command} by {self.user_name}"

    class Meta:
        ordering = ['-created_at']


class TrackedIssue(models.Model):
    """
    Tracks issues created by our system (via Zoom or Project Pulse).

    This model is the central record for tracking issues that we create,
    allowing us to:
    1. Map GitHub issues back to their origin (Zoom or Project Pulse)
    2. Forward status updates from GitHub webhooks to Project Pulse
    3. Track all issues in a unified dashboard
    """
    class Source(models.TextChoices):
        ZOOM_CHAT = 'zoom_chat', 'Zoom Chat'
        PROJECT_PULSE = 'project_pulse', 'Project Pulse'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'        # Created locally, awaiting GitHub
        ACTIVE = 'active', 'Active'           # GitHub issue created successfully
        FAILED = 'failed', 'Failed'           # GitHub creation failed

    # GitHub reference (nullable until GitHub issue created)
    github_repo = models.CharField(max_length=200, db_index=True)  # e.g., "org/repo"
    github_issue_number = models.IntegerField(null=True, blank=True, db_index=True)
    github_issue_url = models.URLField(max_length=500, null=True, blank=True)

    # Status for create-first pattern
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # Origin tracking
    source = models.CharField(max_length=20, choices=Source.choices, db_index=True)
    project_pulse_ticket_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    zoom_conversation_id = models.IntegerField(null=True, blank=True)

    # Metadata
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    created_by = models.CharField(max_length=200)  # user identifier
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Error tracking for failed issues
    error_message = models.TextField(blank=True)

    def __str__(self):
        issue_num = f"#{self.github_issue_number}" if self.github_issue_number else "(pending)"
        return f"{self.title[:50]} - {self.github_repo} {issue_num} [{self.source}]"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['source']),
            models.Index(fields=['status']),
            models.Index(fields=['project_pulse_ticket_id']),
            models.Index(fields=['github_repo', 'github_issue_number']),
        ]
        # Ensure unique GitHub issue per repo (when issue number is set)
        constraints = [
            models.UniqueConstraint(
                fields=['github_repo', 'github_issue_number'],
                name='unique_github_issue',
                condition=models.Q(github_issue_number__isnull=False)
            )
        ]
