from typing import Any

import structlog
from celery import Task

from resumecraft.core.celery_app import celery_app
from resumecraft.services import resume_service
from resumecraft.worker.tasks._runner import run_job_task

logger = structlog.get_logger(__name__)


async def _work(session, job, update_progress) -> dict[str, Any]:
    return await resume_service.parse_upload(session, job, update_progress)


@celery_app.task(name="resumecraft.worker.tasks.parse_resume", bind=True)
def parse_resume(self: Task, job_id: str) -> None:
    logger.info("parse_resume_task_started", job_id=job_id)
    run_job_task(job_id, _work)
