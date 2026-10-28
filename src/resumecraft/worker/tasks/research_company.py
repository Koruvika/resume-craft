from typing import Any

import structlog
from celery import Task

from resumecraft.core.celery_app import celery_app
from resumecraft.services import company_service
from resumecraft.worker.tasks._runner import run_task

logger = structlog.get_logger(__name__)


async def _work(session, task, update_progress) -> dict[str, Any]:
    return await company_service.run_research(session, task, update_progress)


@celery_app.task(name="resumecraft.worker.tasks.research_company", bind=True)
def research_company(self: Task, task_id: str) -> None:
    logger.info("research_company_task_started", task_id=task_id)
    run_task(task_id, _work)
