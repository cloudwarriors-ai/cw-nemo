"""
URL configuration for github_bot_project project.

For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include
from bot_core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    # Mount webhook under /api for GitHub
    path('api/webhook/', views.webhook, name='webhook'),
    # Mount other URLs at root
    path('', include('bot_core.urls')),
]
