# Windows event loop fix - MUST be at top before any other imports
import sys
if sys.platform == 'win32':
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

"""
LiveKit + Simli Avatar Agent.

Real-time avatar bot that uses:
- LiveKit for WebRTC infrastructure
- Simli for avatar video generation (<300ms)
- OpenAI Realtime Model for voice processing
- DataChannel for receiving text queries from Flask

Matches official Simli + LiveKit documentation exactly:
https://docs.simli.com/integrations/livekit
"""

import json
import logging
import os

from dotenv import load_dotenv

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
)
from livekit.plugins import openai, simli
import aiohttp

# Topic for receiving text queries from Flask
QUERY_TOPIC = "qa.query"

# Monkey-patch aiohttp to use a different User-Agent
# Simli API blocks aiohttp's default User-Agent with 500 errors
_original_client_session = aiohttp.ClientSession

def _patched_client_session(*args, **kwargs):
    headers = kwargs.get('headers', {})
    if isinstance(headers, dict):
        headers.setdefault('User-Agent', 'python-requests/2.32.5')
    else:
        # headers is a list of tuples or similar
        headers = dict(headers)
        headers.setdefault('User-Agent', 'python-requests/2.32.5')
    kwargs['headers'] = headers
    return _original_client_session(*args, **kwargs)

aiohttp.ClientSession = _patched_client_session

logger = logging.getLogger("simli-avatar")
logger.setLevel(logging.INFO)

load_dotenv(override=True)


async def entrypoint(ctx: JobContext):
    """
    Main entry point for the avatar agent.

    Follows the official Simli + LiveKit pattern exactly from:
    https://docs.simli.com/integrations/livekit

    Also listens for text queries from Flask via DataChannel.

    NOTE: Do NOT call ctx.connect() - the session.start() handles room connection.
    """
    logger.info(f"Avatar agent starting in room: {ctx.room.name}")
    face_id = os.getenv("SIMLI_FACE_ID", "tmp9i8bbq7c")
    logger.info(f"Using SIMLI_FACE_ID: {face_id}")

    # Create agent session with OpenAI Realtime Model
    # This is the documented pattern - unified voice model
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(voice="alloy"),
    )

    # Create Simli avatar
    # Increase max_idle_time from default 30s to 300s (5 minutes)
    # to prevent avatar from disconnecting during pauses
    simli_avatar = simli.AvatarSession(
        simli_config=simli.SimliConfig(
            api_key=os.getenv("SIMLI_API_KEY"),
            face_id=face_id,
            max_idle_time=300,  # 5 minutes instead of 30 seconds
        ),
    )

    # Start avatar (joins room as video participant)
    logger.info("Starting Simli avatar...")
    await simli_avatar.start(session, room=ctx.room)
    logger.info("Simli avatar started")

    # Start the agent session
    logger.info("Starting agent session...")
    await session.start(
        agent=Agent(
            instructions="""You are QA Bot, a helpful assistant for the Cloud Warriors QA team.
            You help with software testing questions, issue tracking, and team coordination.
            Keep responses concise and helpful."""
        ),
        room=ctx.room,
    )

    logger.info("Avatar agent running - listening for queries")

    # Register handler for text queries from Flask
    @ctx.room.on("data_received")
    def on_data_received(data: rtc.DataPacket):
        """Handle incoming data messages (text queries from Flask)."""
        if data.topic == QUERY_TOPIC:
            try:
                message = json.loads(data.data.decode("utf-8"))
                query = message.get("query", "")
                speaker = message.get("speaker", "User")
                logger.info(f"Received query from {speaker}: {query[:50]}...")

                # Use session.say() to speak the response
                # For now, echo that we received the query and let OpenAI handle it
                # In production, we'd call our QA Brain here
                asyncio.create_task(handle_text_query(session, query, speaker))

            except Exception as e:
                logger.error(f"Error processing data message: {e}")


async def handle_text_query(session: AgentSession, query: str, speaker: str):
    """
    Handle a text query received via DataChannel.

    For now, this injects the query into the OpenAI session.
    In production, we'd call our QA Brain and use session.say().
    """
    try:
        # Option 1: Use session.say() to speak a pre-generated response
        # response = await call_qa_brain(query)  # TODO: integrate QA Brain
        # await session.say(response)

        # Option 2: For testing, just acknowledge and let OpenAI process
        # The agent will hear this as if a user spoke it
        logger.info(f"Processing query: {query}")

        # Create a synthetic user message for the agent to respond to
        # This triggers the OpenAI Realtime model to generate a response
        await session.say(f"Let me help you with that. {query}")

    except Exception as e:
        logger.error(f"Error handling text query: {e}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # NOTE: Do NOT use WorkerType.ROOM - it's not in the Simli docs
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
