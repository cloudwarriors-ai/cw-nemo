#!/bin/bash
# Start ngrok in the background
ngrok http --domain=gitbot.ngrok.app 5000 &

# Start Django
python manage.py runserver 0.0.0.0:5000