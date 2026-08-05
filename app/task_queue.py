from __future__ import annotations

import os

from celery import Celery


def _redis_url() -> str:
    return os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")


celery_app = Celery(
    "reward_delivery_reliability_platform",
    broker=_redis_url(),
    backend=os.getenv("CELERY_RESULT_BACKEND", _redis_url()),
    include=["app.tasks"],
)
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"], timezone="UTC")


def uses_async_worker() -> bool:
    return os.getenv("EXECUTION_MODE", "sync").lower() == "celery"


def dependency_health() -> dict[str, str]:
    """Return mode-aware dependency states for the public health endpoint.

    Redis and Celery are intentionally optional in the local synchronous mode.
    Reporting them as ``not_required`` prevents a working SQLite demo from being
    presented as degraded while keeping strict checks in Celery mode.
    """
    if not uses_async_worker():
        return {"redis": "not_required", "worker": "not_required"}

    redis_ok = worker_ok = False
    try:
        connection = celery_app.connection_for_read()
        connection.ensure_connection(max_retries=1)
        redis_ok = True
        connection.release()
    except Exception:
        redis_ok = False
    if redis_ok:
        try:
            worker_ok = bool(celery_app.control.ping(timeout=0.7))
        except Exception:
            worker_ok = False
    return {
        "redis": "healthy" if redis_ok else "unavailable",
        "worker": "healthy" if worker_ok else "unavailable",
    }


def dispatch_reliability_run(run_id: int) -> str:
    if uses_async_worker():
        celery_app.send_task("app.tasks.execute_reliability_run", args=[run_id])
        return "queued"
    from .reliability import execute_reliability_run

    execute_reliability_run(run_id)
    return "completed"


def dispatch_reward_batch(batch_id: str) -> str:
    """Run the business delivery batch through the configured execution mode."""
    if uses_async_worker():
        celery_app.send_task("app.tasks.process_reward_batch", args=[batch_id])
        return "queued"
    from .reward_batches import process_reward_batch

    process_reward_batch(batch_id)
    return "completed"
