"""Background worker: turns ended calls into summaries.

The API pushes a call id onto the Redis list `queue:summaries` when a call
ends. This process waits on that list (BRPOP) and handles one job at a time.
Run more copies of it to process more calls in parallel.

Run:  python -m app.worker
"""
import asyncio
import logging

from .config import settings
from .storage import FAILED_QUEUE, STATS_KEY, SUMMARY_QUEUE, connect_mongo, connect_redis
from .summary import summarize_call

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("vaanidesk.worker")


def make_llm():
    if not settings.groq_api_key:
        return None
    from groq import AsyncGroq
    return AsyncGroq(api_key=settings.groq_api_key)


async def handle_one(db, redis, llm, timeout: int = 5) -> str | None:
    """Wait for one job and process it. Returns the call id, or None if the queue was empty."""
    item = await redis.brpop(SUMMARY_QUEUE, timeout=timeout)
    if not item:
        return None
    _, call_id = item
    try:
        result = await summarize_call(db, llm, call_id)
        await redis.delete(STATS_KEY)  # dashboard numbers changed
        log.info("summarized %s: %s", call_id, result and result["disposition"])
    except Exception:
        log.exception("failed to summarize %s", call_id)
        await redis.lpush(FAILED_QUEUE, call_id)  # keep it for inspection / retry
    return call_id


async def main() -> None:
    db, redis, llm = connect_mongo(), connect_redis(), make_llm()
    log.info("worker started (LLM summaries: %s)", "on" if llm else "off, using rules")
    while True:
        await handle_one(db, redis, llm)


if __name__ == "__main__":
    asyncio.run(main())
