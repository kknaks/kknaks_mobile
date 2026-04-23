import time

import redis.asyncio as aioredis


class SessionStore:
    def __init__(
        self,
        redis_client: aioredis.Redis,
        *,
        namespace: str,
        ttl_seconds: int = 604800,
    ) -> None:
        self.redis = redis_client
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds

    def _session_key(self, channel: str, thread_key: str) -> str:
        return f"{self.namespace}:session:{channel}:{thread_key}"

    def _meta_key(self, channel: str, thread_key: str) -> str:
        return f"{self.namespace}:session_meta:{channel}:{thread_key}"

    def _index_key(self, channel: str) -> str:
        return f"{self.namespace}:session_index:{channel}"

    def _mode_key(self, channel: str) -> str:
        return f"{self.namespace}:mode:{channel}"

    async def get(self, channel: str, thread_key: str) -> str | None:
        return await self.redis.get(self._session_key(channel, thread_key))

    async def set(
        self,
        channel: str,
        thread_key: str,
        session_id: str,
        *,
        first_prompt: str | None = None,
    ) -> None:
        now = time.time()
        meta_key = self._meta_key(channel, thread_key)

        pipe = self.redis.pipeline()
        pipe.set(
            self._session_key(channel, thread_key),
            session_id,
            ex=self.ttl_seconds,
        )
        pipe.hset(meta_key, mapping={
            "session_id": session_id,
            "last_seen": str(now),
        })
        if first_prompt:
            pipe.hsetnx(meta_key, "first_prompt", first_prompt[:200])
        pipe.expire(meta_key, self.ttl_seconds)
        pipe.zadd(self._index_key(channel), {thread_key: now})
        await pipe.execute()

    async def delete(self, channel: str, thread_key: str) -> bool:
        pipe = self.redis.pipeline()
        pipe.delete(self._session_key(channel, thread_key))
        pipe.delete(self._meta_key(channel, thread_key))
        pipe.zrem(self._index_key(channel), thread_key)
        results = await pipe.execute()
        return bool(results[0])

    async def get_mode(self, channel: str) -> str:
        val = await self.redis.get(self._mode_key(channel))
        return val or "quiet"

    async def set_mode(self, channel: str, mode: str) -> None:
        await self.redis.set(self._mode_key(channel), mode)

    async def list_recent(
        self,
        channel: str,
        *,
        limit: int = 10,
    ) -> list[dict]:
        thread_keys = await self.redis.zrevrange(
            self._index_key(channel), 0, limit - 1,
        )
        out: list[dict] = []
        for tk in thread_keys:
            meta = await self.redis.hgetall(self._meta_key(channel, tk))
            if not meta:
                continue
            out.append({
                "thread_key": tk,
                "session_id": meta.get("session_id"),
                "first_prompt": meta.get("first_prompt", ""),
                "last_seen": float(meta.get("last_seen", "0")),
            })
        return out
