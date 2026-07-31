"""
Global rate limiter, shared across every worker process via Redis.

Fixed-window counter per user: INCR a per-user key, set it to expire after
WINDOW_SECONDS on its first increment. The counter lives in Redis, not this
process's memory, so every worker reads/writes the SAME count — a user
can't dodge the limit by landing on a different worker.
"""
from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis

from app.auth import get_current_user_id
from app.config import settings

redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)

WINDOW_SECONDS = 60    # per this many seconds, per user


async def enforce_rate_limit(user_id: str = Depends(get_current_user_id)) -> None:
    key = f"ratelimit:{user_id}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, WINDOW_SECONDS)
    if count > settings.RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
        )