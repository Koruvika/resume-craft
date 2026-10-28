from celery import Celery

from resumecraft.core.config import Settings


def configure_celery(app: Celery, settings: Settings) -> None:
    app.conf.update(
        broker_url=settings.redis_url,
        result_backend=settings.celery_result_backend_url,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_default_queue="default",
        task_routes={"resumecraft.worker.tasks.*": {"queue": "default"}},
        # Reliability: ack after execution, requeue lost workers.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        # Global autoretry for tasks that raise; run_task-wrapped tasks swallow their own
        # errors (they mark the Task row FAILED instead).
        task_autoretry_for=(Exception,),
        task_annotations={"*": {"max_retries": settings.celery_max_retries}},
        task_default_retry_delay=settings.celery_retry_delay,
        task_soft_time_limit=settings.celery_soft_time_limit,
        task_time_limit=settings.celery_hard_time_limit,
        # Memory hardening for long-running workers.
        worker_prefetch_multiplier=1,
        worker_max_tasks_per_child=20,
        worker_concurrency=settings.celery_concurrency,
        result_expires=86400,
        task_events=True,
    )
