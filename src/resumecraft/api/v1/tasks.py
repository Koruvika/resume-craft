import uuid

from fastapi import APIRouter

from resumecraft.api.deps import CurrentUserDep, DbSession
from resumecraft.api.responses import INVALID_INPUT, UNAUTHENTICATED, not_found
from resumecraft.schemas.task import TaskResponse
from resumecraft.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    responses={401: UNAUTHENTICATED, 404: not_found("task"), 422: INVALID_INPUT},
)
async def get_task(task_id: uuid.UUID, db: DbSession, user: CurrentUserDep) -> TaskResponse:
    task = await task_service.get_task_for_user(db, task_id, user.user_id)
    return TaskResponse.model_validate(task)
