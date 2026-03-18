"""Celery configuration for async task processing"""
import os
from celery.schedules import crontab

# Celery broker and result backend
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')

# Task configuration
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TIMEZONE = 'UTC'
CELERY_ENABLE_UTC = True

# Task routing (commented out - use default queue for simplicity)
# CELERY_TASK_ROUTES = {
#     'bot_core.tasks.validate_and_notify_issue': {'queue': 'validation'},
#     'bot_core.tasks.cleanup_old_conversations': {'queue': 'cleanup'},
#     'bot_core.tasks.cleanup_validation_feedback': {'queue': 'cleanup'},
# }

# Task time limits (prevent stuck tasks)
CELERY_TASK_TIME_LIMIT = 30  # 30 seconds hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 25  # 25 seconds soft limit

# Task retry configuration
CELERY_TASK_ACKS_LATE = True  # Acknowledge task after completion
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Disable prefetching for better distribution

# Beat schedule (periodic tasks)
CELERY_BEAT_SCHEDULE = {
    'cleanup-conversations-daily': {
        'task': 'bot_core.tasks.cleanup_old_conversations',
        'schedule': crontab(hour=2, minute=0),  # 2 AM daily
    },
    'cleanup-validation-feedback-weekly': {
        'task': 'bot_core.tasks.cleanup_validation_feedback',
        'schedule': crontab(hour=3, minute=0, day_of_week=0),  # Sunday 3 AM
    },
}

# Result backend configuration
CELERY_RESULT_EXPIRES = 3600  # Results expire after 1 hour

# Worker configuration
CELERYD_MAX_TASKS_PER_CHILD = 1000  # Restart worker after 1000 tasks (prevent memory leaks)
