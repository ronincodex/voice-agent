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

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

from pipecat.workers.runner import WorkerRunner  # noqa: E402

from voice_agent.pipeline.agent_pipeline import create_agent_pipeline  # noqa: E402

# ===== CRITICAL: Load .env BEFORE any os.getenv() calls =====
# This must run before we read DAILY_ROOM_URL from the environment.
# Pydantic Settings loads .env for its own class, but the standard
# os.getenv() function does NOT read .env files. We bridge that gap here.

# Add the src directory to the Python path so we can import voice_agent
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


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
    task = await create_agent_pipeline(
        room_url=room_url,
        language_code=args.language,
    )

    logger.info("Pipeline created. Starting conversation...")
    runner = WorkerRunner()
    await runner.add_workers(task)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
