from typing import Any

import structlog
from celery import Task

from resumecraft.core.celery_app import celery_app
from resumecraft.services import company_research_service
from resumecraft.worker.tasks._runner import run_job_task

logger = structlog.get_logger(__name__)


async def _work(session, job, update_progress) -> dict[str, Any]:
    return await company_research_service.run_research(session, job, update_progress)


@celery_app.task(name="resumecraft.worker.tasks.company_research", bind=True)
def company_research(self: Task, job_id: str) -> None:
    logger.info("company_research_task_started", job_id=job_id)
    run_job_task(job_id, _work)
