from datetime import datetime

from slack_sdk.web.async_client import AsyncWebClient

from .sessions import SessionStore

COMMAND_PREFIX = "!"

HELP_TEXT = (
    "*사용 가능한 명령어*\n"
    "• `!clear` — 현재 대화 세션 초기화\n"
    "• `!resume` — 이 채널의 최근 세션 목록\n"
    "• `!help` — 이 도움말"
)


class CommandHandler:
    def __init__(self, sessions: SessionStore) -> None:
        self.sessions = sessions

    async def try_handle(
        self,
        *,
        prompt: str,
        channel: str,
        thread_key: str,
        reply_thread_ts: str | None,
        slack_client: AsyncWebClient,
    ) -> bool:
        """If prompt is a bang command, handle it and return True."""
        stripped = prompt.strip()
        if not stripped.startswith(COMMAND_PREFIX):
            return False

        parts = stripped.split(maxsplit=1)
        cmd = parts[0][len(COMMAND_PREFIX):].lower()

        if cmd == "clear":
            removed = await self.sessions.delete(channel, thread_key)
            msg = (
                "🧹 세션 초기화. 다음 메시지부터 새 세션으로 시작합니다."
                if removed
                else "_저장된 세션이 없어요._"
            )
            await slack_client.chat_postMessage(
                channel=channel, thread_ts=reply_thread_ts, text=msg,
            )
            return True

        if cmd == "resume":
            sessions = await self.sessions.list_recent(channel, limit=10)
            if not sessions:
                text = "_저장된 세션 없음_"
            else:
                lines = ["*최근 세션 (최신순)*"]
                for s in sessions:
                    preview = (s["first_prompt"] or "_(미리보기 없음)_").replace("\n", " ")[:80]
                    when = datetime.fromtimestamp(s["last_seen"]).strftime("%m-%d %H:%M")
                    sid = (s["session_id"] or "")[:8]
                    tk = s["thread_key"]
                    lines.append(f"• `{sid}` · _{when}_ · `{tk[:10]}` · {preview}")
                text = "\n".join(lines)
            await slack_client.chat_postMessage(
                channel=channel, thread_ts=reply_thread_ts, text=text,
            )
            return True

        if cmd == "help":
            await slack_client.chat_postMessage(
                channel=channel, thread_ts=reply_thread_ts, text=HELP_TEXT,
            )
            return True

        return False
