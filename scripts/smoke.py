"""Smoke test: submit a trivial prompt and print the result."""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from open_kknaks import ClaudeClient, RedisBroker


async def main() -> None:
    broker = RedisBroker(
        url=os.environ["REDIS_URL"],
        namespace=os.environ["REDIS_NAMESPACE"],
    )
    await broker.connect()
    client = ClaudeClient(broker=broker)

    task_id = await client.submit("Say the word 'pong' and nothing else.")
    print(f"submitted: {task_id}")

    task = await client.result(task_id, timeout=120)
    print(f"status: {task.status}")
    print(f"result: {task.result}")

    await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
