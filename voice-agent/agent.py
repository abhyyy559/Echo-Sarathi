"""LiveKit Agents worker entrypoint for the voice calling runtime.

Handles playground-* (browser) and phone-* (Twilio bridge) rooms.

Run locally:
    python agent.py dev        # dev worker against LIVEKIT_URL
    python agent.py start      # production mode
"""

from __future__ import annotations

import logging
import sys

from livekit import agents
from livekit.agents import JobContext, WorkerOptions, cli

from app.config import get_settings
from app.pipeline import run_session
from app.rooms import is_handled_room

logger = logging.getLogger("voice_agent")


async def entrypoint(ctx: JobContext) -> None:
    """Job callback: accept playground rooms, close anything else.

    Returning from this function ends the job for the room gracefully while
    the worker keeps serving other rooms.
    """
    room_name = ctx.room.name or ""
    if not is_handled_room(room_name):
        logger.info("Ignoring job for unhandled room %r", room_name)
        return

    settings = get_settings()
    for missing in settings.missing_required():
        logger.error("Missing required environment variable: %s", missing)

    await run_session(ctx, settings)


def main() -> None:
    """Configure logging and start the LiveKit worker."""
    # Bare `python agent.py` (docker compose, systemd) starts in PRODUCTION
    # mode: dev mode hard-codes http://localhost:7880 and ignores ws_url/api
    # credentials, which is unreachable from inside the compose network (the
    # worker then retries 127.0.0.1:7880 forever). `python agent.py dev` is
    # still available for running the worker on the host.
    if len(sys.argv) < 2:
        sys.argv = [sys.argv[0], "start"]
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info(
        "Starting voice-agent worker (playground + phone rooms) against %s",
        settings.livekit_url,
    )
    agents.cli.run_app(
        # url/api_key/api_secret are passed explicitly: WorkerOptions otherwise
        # reads LIVEKIT_URL straight from the environment, which in compose is
        # the BROWSER-facing host address (localhost) and never resolves inside
        # the container network. Settings resolves LIVEKIT_URL_INTERNAL first.
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            ws_url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
    )


if __name__ == "__main__":
    main()
