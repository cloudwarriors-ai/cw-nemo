from .zoom_bot import ZoomChatBot

# Initialize the Zoom bot when Django starts
try:
    zoom_bot = ZoomChatBot()
    #zoom_bot.announce_online()
except Exception as e:
    print(f"Failed to initialize Zoom bot: {e}")
    zoom_bot = None