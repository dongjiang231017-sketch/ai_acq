from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings


def get_redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def enqueue_dm_task(task_id: str) -> None:
    try:
        get_redis_client().rpush(settings.dm_queue_name, task_id)
    except RedisError as exc:
        raise RuntimeError(f"Redis enqueue failed: {exc}") from exc


def pop_dm_task(timeout_seconds: int = 5) -> str | None:
    try:
        item = get_redis_client().blpop(settings.dm_queue_name, timeout=timeout_seconds)
    except RedisError as exc:
        raise RuntimeError(f"Redis pop failed: {exc}") from exc
    if not item:
        return None
    _, task_id = item
    return str(task_id)
