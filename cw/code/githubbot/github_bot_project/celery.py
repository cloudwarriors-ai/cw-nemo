"""Celery app initialization"""
import os
from celery import Celery

# Set default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'github_bot_project.settings')

# Create Celery app
app = Celery('github_bot_project')

# Load config from celeryconfig.py
app.config_from_object('celeryconfig', namespace='CELERY')

# Auto-discover tasks from installed apps
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for testing Celery setup"""
    print(f'Request: {self.request!r}')
