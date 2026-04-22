"""File I/O helpers for Slack ↔ local bridging."""

import logging
import re
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

# Claude signals outbound file uploads with this tag.
SEND_FILE_RE = re.compile(r"<send-file>(.+?)</send-file>", re.DOTALL)

_SAFE_NAME_RE = re.compile(r"[^\w.\-]")


async def download_slack_file(
    file_info: dict,
    dest_dir: Path,
    bot_token: str,
) -> Path:
    """Download a Slack file to dest_dir and return its local path."""
    url = file_info.get("url_private_download") or file_info.get("url_private")
    if not url:
        raise ValueError("file_info has no download URL")

    file_id = file_info.get("id") or "unknown"
    original = file_info.get("name") or "file"
    safe = _SAFE_NAME_RE.sub("_", original)
    dest = dest_dir / f"{file_id}-{safe}"

    dest_dir.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {bot_token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            content = await resp.read()

    dest.write_bytes(content)
    logger.info("downloaded %s (%d B) -> %s", original, len(content), dest)
    return dest
