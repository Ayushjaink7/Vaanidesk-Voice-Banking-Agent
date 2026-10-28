"""MongoDB (permanent records) and Redis (fast, temporary state).

MongoDB keeps every call, its turns and its summary.
Redis keeps things that are short-lived or need to be fast:
  session:{call_id}   live conversation state, expires when the call goes idle
  nlu:{hash}          cached LLM results for repeated phrases
  rl:{ip}:{minute}    request counter for rate limiting
  queue:summaries     post-call jobs for the worker
  stats:cache         cached dashboard numbers
"""
import json
import time

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from redis.asyncio import Redis

from .config import settings

SUMMARY_QUEUE = "queue:summaries"
FAILED_QUEUE = "queue:summaries:failed"
STATS_KEY = "stats:cache"


def connect_mongo() -> AsyncIOMotorDatabase:
    # tz_aware: dates come back with a timezone, so the frontend shows correct local times
    return AsyncIOMotorClient(settings.mongo_url, tz_aware=True)[settings.mongo_db]


def connect_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    # The dashboard lists newest calls first and filters by status.
    await db.calls.create_index([("started_at", -1)])
    await db.calls.create_index("status")
    await db.calls.create_index("customer_id")


# ---------- session state (Redis) ----------

def _session_key(call_id: str) -> str:
    return f"session:{call_id}"


async def save_session(redis: Redis, call_id: str, session: dict) -> None:
    # Every save refreshes the TTL, so only idle calls expire.
    await redis.set(_session_key(call_id), json.dumps(session), ex=settings.session_ttl_seconds)


async def load_session(redis: Redis, call_id: str) -> dict | None:
    raw = await redis.get(_session_key(call_id))
    return json.loads(raw) if raw else None


async def delete_session(redis: Redis, call_id: str) -> None:
    await redis.delete(_session_key(call_id))


# ---------- rate limiting (Redis) ----------

async def allow_request(redis: Redis, client_id: str, limit: int) -> bool:
    """Fixed-window limiter: at most `limit` requests per client per minute."""
    key = f"rl:{client_id}:{int(time.time() // 60)}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    return count <= limit
