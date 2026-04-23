import logging
import os
from contextlib import suppress
from pathlib import Path

from slack_bolt.async_app import AsyncApp

from .commands import CommandHandler
from .files import download_slack_file
from .runner import ClaudeRunner, strip_mention

logger = logging.getLogger(__name__)

_ALLOWED_SUBTYPES: set[str | None] = {None, "file_share"}


async def create_app(
    runner: ClaudeRunner,
    commands: CommandHandler,
    *,
    upload_dir: Path,
    bot_token: str,
) -> AsyncApp:
    app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])

    auth = await app.client.auth_test()
    bot_user_id: str = auth["user_id"]
    bot_mention_tag = f"<@{bot_user_id}>"
    logger.info("bot user id: %s", bot_user_id)

    allowed_users: set[str] = {
        u.strip()
        for u in os.environ.get("ALLOWED_SLACK_USERS", "").split(",")
        if u.strip()
    }
    if allowed_users:
        logger.info("allowed slack users: %s", sorted(allowed_users))
    else:
        logger.warning(
            "ALLOWED_SLACK_USERS is empty — all incoming messages will be ignored. "
            "Set it in .env (comma-separated user IDs, e.g. U0123,U0456)."
        )

    def _authorized(event: dict) -> bool:
        user = event.get("user")
        if user in allowed_users:
            return True
        logger.info("ignoring message from unauthorized user: %s", user)
        return False

    async def collect_attachments(event: dict) -> list[str]:
        files = event.get("files") or []
        paths: list[str] = []
        for f in files:
            if f.get("mode") in ("hidden_by_limit", "tombstone"):
                continue
            try:
                dest = await download_slack_file(f, upload_dir, bot_token)
                paths.append(str(dest))
            except Exception:
                logger.exception("download failed: %s", f.get("id"))
        return paths

    async def dispatch(
        *,
        raw_text: str,
        channel: str,
        thread_key: str,
        reply_thread_ts: str | None,
        slack_client,
        attached_files: list[str] | None = None,
    ) -> None:
        prompt = strip_mention(raw_text)
        if not prompt and not attached_files:
            return

        try:
            if prompt and await commands.try_handle(
                prompt=prompt,
                channel=channel,
                thread_key=thread_key,
                reply_thread_ts=reply_thread_ts,
                slack_client=slack_client,
            ):
                return

            await runner.handle(
                prompt=prompt,
                channel=channel,
                thread_key=thread_key,
                reply_thread_ts=reply_thread_ts,
                slack_client=slack_client,
                attached_files=attached_files,
            )
        finally:
            for p in attached_files or []:
                with suppress(FileNotFoundError):
                    os.unlink(p)

    @app.event("app_mention")
    async def on_mention(event, client, logger):
        if not _authorized(event):
            return
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        logger.info("mention channel=%s thread=%s", channel, thread_ts)
        attached = await collect_attachments(event)
        await dispatch(
            raw_text=event.get("text", ""),
            channel=channel,
            thread_key=thread_ts,
            reply_thread_ts=thread_ts,
            slack_client=client,
            attached_files=attached or None,
        )

    @app.event("message")
    async def on_message(event, client, logger):
        if event.get("bot_id"):
            return
        if event.get("user") == bot_user_id:
            return
        subtype = event.get("subtype")
        if subtype not in _ALLOWED_SUBTYPES:
            return
        if not _authorized(event):
            return

        channel = event["channel"]
        channel_type = event.get("channel_type")
        text = event.get("text", "")

        if channel_type == "im":
            thread_ts_in = event.get("thread_ts")
            if thread_ts_in:
                thread_key = thread_ts_in
                reply_thread_ts: str | None = thread_ts_in
            else:
                thread_key = "main"
                reply_thread_ts = None
        elif channel_type in ("channel", "group"):
            thread_ts = event.get("thread_ts")
            if not thread_ts:
                return
            if bot_mention_tag in text:
                return
            existing = await runner.sessions.get(channel, thread_ts)
            if not existing:
                return
            thread_key = thread_ts
            reply_thread_ts = thread_ts
        else:
            return

        attached = await collect_attachments(event)
        logger.info(
            "message channel=%s type=%s thread=%s attached=%d",
            channel, channel_type, thread_key, len(attached),
        )
        await dispatch(
            raw_text=text,
            channel=channel,
            thread_key=thread_key,
            reply_thread_ts=reply_thread_ts,
            slack_client=client,
            attached_files=attached or None,
        )

    return app
