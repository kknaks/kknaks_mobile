import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import redis.asyncio as aioredis
from open_kknaks import ClaudeClient, RedisBroker
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from src.bridge.app import create_app
from src.bridge.commands import CommandHandler
from src.bridge.runner import ClaudeRunner
from src.bridge.sessions import SessionStore


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    redis_url = os.environ["REDIS_URL"]
    namespace = os.environ["REDIS_NAMESPACE"]
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    upload_dir = Path(
        os.environ.get("UPLOAD_DIR", "/tmp/kknaks_mobile_uploads")
    )
    upload_dir.mkdir(parents=True, exist_ok=True)

    broker = RedisBroker(url=redis_url, namespace=namespace)
    await broker.connect()
    client = ClaudeClient(broker=broker)

    redis_client = aioredis.from_url(redis_url, decode_responses=True)
    sessions = SessionStore(redis_client, namespace=namespace)

    runner = ClaudeRunner(
        client=client,
        sessions=sessions,
        # extra_dirs currently disabled — open-kknaks' --add-dir placement
        # collides with Claude CLI's variadic parser and eats the prompt.
        # Uploads are stored under WORK_DIR instead, so no --add-dir needed.
    )
    commands = CommandHandler(sessions=sessions)
    app = await create_app(
        runner=runner,
        commands=commands,
        upload_dir=upload_dir,
        bot_token=bot_token,
    )

    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    try:
        await handler.start_async()
    finally:
        await broker.close()
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
