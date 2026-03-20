# Windows event loop fix - MUST be at top before any other imports
import sys
if sys.platform == 'win32':
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

"""
Audio-only LiveKit Agent for testing voice response times.

Uses OpenAI Realtime Model (unified STT + LLM + TTS) without Simli avatar.
This tests the core voice pipeline latency and quality.
"""

import logging
import os

from dotenv import load_dotenv

from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import openai

logger = logging.getLogger("qa_agent.audio_test")
logger.setLevel(logging.INFO)

load_dotenv()


async def entrypoint(ctx: JobContext):
    """
    Audio-only agent entry point.

    Tests the OpenAI Realtime Model voice pipeline without avatar.
    """
    logger.info(f"Audio test agent starting in room: {ctx.room.name}")

    # Create agent session with OpenAI Realtime Model only
    # This is the same model used with Simli, just without the avatar
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(voice="alloy"),
    )

    # Start the agent session (audio only, no avatar)
    logger.info("Starting audio-only agent session...")
    await session.start(
        agent=Agent(
            instructions="""You are QA Bot, a helpful assistant for the Cloud Warriors QA team.
            You help with software testing questions, issue tracking, and team coordination.
            Keep responses concise and helpful. This is an audio test - respond naturally."""
        ),
        room=ctx.room,
    )

    logger.info("Audio test agent running - listening for voice queries")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
