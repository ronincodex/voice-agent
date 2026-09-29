"""Local test runner for the voice agent pipeline.

This script connects to a Daily room and runs the agent pipeline.
It is used for local development and testing before telephony integration.

Usage:
    python scripts/run_local_agent.py --language hi-IN
"""

import argparse
import asyncio
import os
import sys
from typing import Any

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

from pipecat.transports.daily.transport import DailyParams, DailyTransport  # noqa: E402
from pipecat.workers.runner import WorkerRunner  # noqa: E402

from voice_agent.config.languages import get_language_config  # noqa: E402
from voice_agent.pipeline.agent_pipeline import create_agent_pipeline  # noqa: E402
from voice_agent.pipeline.nodes import build_initial_node  # noqa: E402

# Strong references to fire-and-forget tasks. Without this, asyncio may
# garbage-collect the task before it runs (the classic asyncio footgun).
_background_tasks: set[asyncio.Task[Any]] = set()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the voice agent locally")
    parser.add_argument(
        "--language",
        default="hi-IN",
        choices=["hi-IN", "en-IN", "ta-IN"],
        help="Language code for the conversation",
    )
    args = parser.parse_args()

    room_url = os.getenv("DAILY_ROOM_URL")
    if not room_url:
        logger.error(
            "DAILY_ROOM_URL environment variable is not set. "
            "Create a room at https://dashboard.daily.co/rooms "
            "and add the URL to your .env file."
        )
        sys.exit(1)

    logger.info(f"Starting voice agent in {args.language}...")

    # Create the Daily transport here. This is the "Adapter" step:
    # the caller knows which transport to use; the pipeline does not.
    transport = DailyTransport(
        room_url=room_url,
        token=None,
        bot_name="AI Assistant",
        params=DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    task, flow_manager = await create_agent_pipeline(
        transport=transport,
        language_code=args.language,
    )

    lang_config = get_language_config(args.language)

    async def _start_flow() -> None:
        """Initialize the Flows graph after the pipeline is ready."""
        await asyncio.sleep(2.0)
        try:
            await flow_manager.initialize(build_initial_node(lang_config))
            logger.info("Flow initialized")
        except Exception as e:
            logger.error(f"Flow initialization failed: {e}")

    flow_start_task = asyncio.create_task(_start_flow())
    _background_tasks.add(flow_start_task)
    flow_start_task.add_done_callback(_background_tasks.discard)

    logger.info("Pipeline created. Starting conversation...")
    runner = WorkerRunner()
    await runner.add_workers(task)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
