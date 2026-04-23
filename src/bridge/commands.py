from datetime import datetime

from slack_sdk.web.async_client import AsyncWebClient

from .sessions import SessionStore

COMMAND_PREFIX = "!"

VALID_MODES = ("quiet", "log")

VALID_MODELS = ("opusm", "opus", "sonnet", "haiku")

MODEL_ALIASES: dict[str, str] = {
    "opusm": "claude-opus-4-7[1m]",
}

HELP_TEXT = (
    "*사용 가능한 명령어*\n"
    "• `!clear` — 현재 대화 세션 초기화\n"
    "• `!resume` — 이 채널의 최근 세션 목록\n"
    "• `!mode [quiet|log]` — 출력 모드 조회/설정 (기본 quiet, log는 tool 호출 표시)\n"
    "• `!model [opusm|opus|sonnet|haiku|default]` — 모델 조회/설정 (default=시스템 기본값)\n"
    "• `!help` — 이 도움말"
)


def resolve_model(alias: str | None) -> str | None:
    """Map a bridge alias to the model ID passed to Claude Code CLI.

    None → use system default. Unknown aliases pass through unchanged
    (defensive: shouldn't happen since !model validates).
    """
    if not alias:
        return None
    return MODEL_ALIASES.get(alias, alias)


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

        if cmd == "mode":
            if len(parts) < 2:
                current = await self.sessions.get_mode(channel)
                text = f"_현재 모드: `{current}`_ (옵션: {', '.join(f'`{m}`' for m in VALID_MODES)})"
            else:
                arg = parts[1].strip().lower()
                if arg not in VALID_MODES:
                    text = (
                        f"⚠ 알 수 없는 모드 `{arg}`. "
                        f"사용 가능: {', '.join(f'`{m}`' for m in VALID_MODES)}"
                    )
                else:
                    await self.sessions.set_mode(channel, arg)
                    text = f"✅ 모드 변경: `{arg}`"
            await slack_client.chat_postMessage(
                channel=channel, thread_ts=reply_thread_ts, text=text,
            )
            return True

        if cmd == "model":
            if len(parts) < 2:
                current = await self.sessions.get_model(channel)
                label = f"`{current}`" if current else "`default` _(시스템 기본값)_"
                text = (
                    f"_현재 모델: {label}_ "
                    f"(옵션: {', '.join(f'`{m}`' for m in VALID_MODELS)}, `default`)"
                )
            else:
                arg = parts[1].strip().lower()
                if arg == "default":
                    await self.sessions.delete_model(channel)
                    text = "✅ 모델: `default` _(시스템 기본값)_"
                elif arg not in VALID_MODELS:
                    text = (
                        f"⚠ 알 수 없는 모델 `{arg}`. "
                        f"사용 가능: {', '.join(f'`{m}`' for m in VALID_MODELS)}, `default`"
                    )
                else:
                    await self.sessions.set_model(channel, arg)
                    text = f"✅ 모델 변경: `{arg}`"
            await slack_client.chat_postMessage(
                channel=channel, thread_ts=reply_thread_ts, text=text,
            )
            return True

        if cmd == "help":
            await slack_client.chat_postMessage(
                channel=channel, thread_ts=reply_thread_ts, text=HELP_TEXT,
            )
            return True

        await slack_client.chat_postMessage(
            channel=channel,
            thread_ts=reply_thread_ts,
            text=f"⚠ 알 수 없는 명령어 `!{cmd}`. `!help` 로 사용 가능한 명령 확인",
        )
        return True
