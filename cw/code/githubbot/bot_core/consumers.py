import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import WebhookEvent

class GitHubEventConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("github_events", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("github_events", self.channel_name)

    async def receive(self, text_data):
        pass  # We don't expect to receive messages from the client

    async def github_event(self, event):
        """Handle github.event type messages"""
        await self.send(text_data=json.dumps(event['data']))

    async def container_heartbeat(self, event):
        """Handle container heartbeat messages"""
        data = event['data']

        # Add visual indicators for container status
        status = data.get('status', '')
        if status == 'unhealthy':
            data['alert_level'] = 'danger'
            data['icon'] = ''
        else:
            data['alert_level'] = 'success'
            data['icon'] = ''

        # Format the summary for better display
        summary = data.get('summary', '')
        if not summary.startswith("Container Heartbeat:"):
            data['summary'] = f"Container Heartbeat: {summary}"

        # Send the event data to the WebSocket client
        await self.send(text_data=json.dumps(data))

    @database_sync_to_async
    def get_latest_events(self):
        events = WebhookEvent.objects.select_related('repository').order_by('-created_at')[:50]
        return [{
            'id': event.id,
            'summary': event.get_summary(),
            'repository': event.repository.full_name,
            'created_at': event.created_at.isoformat(),
            'actor_avatar': event.actor_avatar_url,
            'html_url': event.html_url,
            'type': event.event_type,
        } for event in events]
