from typing import Any

import structlog
from celery import Task

from resumecraft.core.celery_app import celery_app
from resumecraft.schemas.resume import GenerateResumeRequest
from resumecraft.services import resume_service
from resumecraft.worker.tasks._runner import run_job_task

logger = structlog.get_logger(__name__)


async def _work(session, job, update_progress) -> dict[str, Any]:
    request = GenerateResumeRequest.model_validate(job.input)
    generated = await resume_service.generate(session, job, update_progress, request)
    return generated.model_dump()


@celery_app.task(name="resumecraft.worker.tasks.generate_resume", bind=True)
def generate_resume(self: Task, job_id: str) -> None:
    logger.info("generate_resume_task_started", job_id=job_id)
    run_job_task(job_id, _work)
