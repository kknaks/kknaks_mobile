import logging
import os
import re
import time
from typing import Any

from open_kknaks import ClaudeClient
from slack_sdk.web.async_client import AsyncWebClient

from .commands import resolve_model
from .files import SEND_FILE_RE
from .sessions import SessionStore

logger = logging.getLogger(__name__)

MENTION_RE = re.compile(r"<@[A-Z0-9]+>\s*")
UPDATE_INTERVAL_SEC = 1.5
MAX_SLACK_MSG_LEN = 38000

_TOOL_INPUT_KEYS = (
    "command",
    "file_path",
    "path",
    "pattern",
    "query",
    "url",
    "description",
    "prompt",
)

FILE_SEND_INSTRUCTION = (
    "When the user explicitly asks to send, share, or download a file, "
    "include the absolute path in your response using this exact format:\n"
    "<send-file>/absolute/path/to/file.ext</send-file>\n"
    "The bridge will upload the tagged file to Slack. "
    "You do NOT need to Read the file first — just include the correct path. "
    "Use this only when the user wants to receive the file, not for paths "
    "you merely mention in an explanation. "
    "For attached files from the user, their absolute paths are provided in "
    "the prompt inside `[첨부 파일: ...]` markers — you can Read them directly."
)


def strip_mention(text: str) -> str:
    return MENTION_RE.sub("", text or "").strip()


def summarize_tool_input(inp: Any) -> str:
    if isinstance(inp, dict):
        for key in _TOOL_INPUT_KEYS:
            val = inp.get(key)
            if val:
                return str(val).replace("\n", " ")[:160]
        return str(inp).replace("\n", " ")[:160]
    return str(inp or "").replace("\n", " ")[:160]


class ClaudeRunner:
    def __init__(
        self,
        client: ClaudeClient,
        sessions: SessionStore,
        *,
        extra_dirs: list[str] | None = None,
    ) -> None:
        self.client = client
        self.sessions = sessions
        self.extra_dirs = list(extra_dirs or [])

    async def handle(
        self,
        *,
        prompt: str,
        channel: str,
        thread_key: str,
        reply_thread_ts: str | None,
        slack_client: AsyncWebClient,
        attached_files: list[str] | None = None,
    ) -> None:
        if not prompt and not attached_files:
            return

        # Inject attached file paths into the prompt so Claude can Read them.
        full_prompt = prompt or "첨부된 파일을 확인해줘."
        if attached_files:
            attach_block = "\n".join(f"[첨부 파일: {p}]" for p in attached_files)
            full_prompt = f"{full_prompt}\n\n{attach_block}"

        session_id = await self.sessions.get(channel, thread_key)
        mode = await self.sessions.get_mode(channel)
        model = resolve_model(await self.sessions.get_model(channel))

        placeholder = await slack_client.chat_postMessage(
            channel=channel,
            thread_ts=reply_thread_ts,
            text="⏳ thinking…",
        )
        msg_ts = placeholder["ts"]

        task_id = await self.client.submit(
            full_prompt,
            session_id=session_id,
            model=model,
            append_system_prompt=FILE_SEND_INSTRUCTION,
            add_dirs=self.extra_dirs or None,
        )
        logger.info(
            "submitted task=%s channel=%s thread=%s session=%s attached=%d",
            task_id, channel, thread_key, session_id, len(attached_files or []),
        )

        timeline: list[dict] = []
        delta_buffer = ""
        last_update = 0.0

        start_time = time.monotonic()
        total_tokens = 0
        tool_uses = 0
        final_cost = 0.0

        def append_text(t: str) -> None:
            if not t:
                return
            if timeline and timeline[-1]["type"] == "text":
                timeline[-1]["content"] += t
            else:
                timeline.append({"type": "text", "content": t})

        def build_footer() -> str:
            elapsed = time.monotonic() - start_time
            parts = [f"⏱ {elapsed:.1f}s"]
            if total_tokens:
                parts.append(f"🪙 {total_tokens:,}")
            if tool_uses:
                parts.append(f"🔧 ×{tool_uses}")
            if final_cost > 0:
                parts.append(f"💵 ${final_cost:.4f}")
            return "_" + " · ".join(parts) + "_"

        def render() -> str:
            parts: list[str] = []
            for item in timeline:
                if item["type"] == "text":
                    if item["content"]:
                        parts.append(item["content"])
                elif item["type"] == "tool":
                    parts.append(f"🔧 `{item['name']}` {item['input']}")
            if not parts:
                parts.append("⏳ thinking…")
            parts.append(build_footer())
            body = "\n\n".join(parts)
            if len(body) > MAX_SLACK_MSG_LEN:
                body = "…" + body[-MAX_SLACK_MSG_LEN:]
            return body

        async def flush(force: bool = False) -> None:
            nonlocal last_update
            now = time.monotonic()
            if not force and now - last_update < UPDATE_INTERVAL_SEC:
                return
            try:
                await slack_client.chat_update(
                    channel=channel, ts=msg_ts, text=render(),
                )
                last_update = now
            except Exception as e:
                logger.warning("chat_update failed: %s", e)

        try:
            async for event in self.client.stream(task_id):
                if event.type == "text":
                    t = event.text or ""
                    if not t:
                        continue
                    if t == delta_buffer:
                        delta_buffer = ""
                        continue
                    append_text(t)
                    delta_buffer += t
                    await flush()
                    continue

                delta_buffer = ""

                if event.type == "init" and event.session_id:
                    await self.sessions.set(
                        channel, thread_key, event.session_id,
                        first_prompt=prompt,
                    )
                elif event.type == "tool_use":
                    if mode == "log":
                        timeline.append({
                            "type": "tool",
                            "name": event.tool_name or "?",
                            "input": summarize_tool_input(event.tool_input),
                        })
                        await flush()
                elif event.type == "progress":
                    if event.total_tokens:
                        total_tokens = event.total_tokens
                    if event.tool_uses is not None:
                        tool_uses = event.tool_uses
                    await flush()
                elif event.type == "cost":
                    if event.cost_usd:
                        final_cost = event.cost_usd
        except Exception as e:
            logger.exception("stream failed")
            append_text(f"\n\n❌ error: {e}")
        finally:
            try:
                final_task = await self.client.broker.get_task(task_id)
                if final_task and final_task.usage:
                    u = final_task.usage
                    sum_tokens = (
                        (u.input_tokens or 0)
                        + (u.output_tokens or 0)
                        + (u.cache_read_tokens or 0)
                        + (u.cache_write_tokens or 0)
                    )
                    if sum_tokens:
                        total_tokens = sum_tokens
                    if u.cost_usd:
                        final_cost = u.cost_usd
            except Exception:
                logger.debug("final task fetch failed", exc_info=True)

            # Extract <send-file> tags and strip them from displayed text.
            paths_to_upload: list[str] = []
            for item in timeline:
                if item["type"] == "text":
                    for m in SEND_FILE_RE.findall(item["content"]):
                        p = m.strip()
                        if p:
                            paths_to_upload.append(p)
                    item["content"] = SEND_FILE_RE.sub("", item["content"]).strip()
            timeline[:] = [
                it for it in timeline
                if it["type"] != "text" or it["content"]
            ]

            await flush(force=True)

            # Upload tagged files as thread attachments.
            for path in paths_to_upload:
                if not os.path.isfile(path):
                    await self._notify(
                        slack_client, channel, reply_thread_ts,
                        f"⚠ 파일 없음: `{path}`",
                    )
                    continue
                try:
                    await slack_client.files_upload_v2(
                        channel=channel,
                        thread_ts=reply_thread_ts,
                        file=path,
                        filename=os.path.basename(path),
                    )
                    logger.info("uploaded file: %s", path)
                except Exception as e:
                    logger.exception("file upload failed: %s", path)
                    await self._notify(
                        slack_client, channel, reply_thread_ts,
                        f"⚠ 업로드 실패 `{os.path.basename(path)}`: {e}",
                    )

    @staticmethod
    async def _notify(
        slack_client: AsyncWebClient,
        channel: str,
        thread_ts: str | None,
        text: str,
    ) -> None:
        try:
            await slack_client.chat_postMessage(
                channel=channel, thread_ts=thread_ts, text=text,
            )
        except Exception:
            logger.warning("notify failed: %s", text, exc_info=True)
