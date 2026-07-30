from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.http import ok, request_id_context
from app.core.database import DbSession
from app.core.security import ClientAppDependency
from app.domains.classification.service import (
    create_feedback,
    create_task,
    task_data,
)
from app.models import ClientApp
from app.schemas.classification import ClassificationCreate, FeedbackCreate

router = APIRouter(tags=["classifications"])


@router.post("/classifications", status_code=status.HTTP_202_ACCEPTED)
def post_classification(
    data: ClassificationCreate,
    db: Session = DbSession,
    client: ClientApp = ClientAppDependency,
):
    task = create_task(db, client, data)
    return JSONResponse(
        {
            "data": {"classification_id": task.id, "status": task.status},
            "request_id": request_id_context.get(),
        },
        status_code=202,
    )


@router.get("/classifications/{classification_id}")
def get_classification(
    classification_id: str,
    db: Session = DbSession,
    client: ClientApp = ClientAppDependency,
):
    return ok(task_data(db, client, classification_id))


@router.post("/classifications/{classification_id}/feedback", status_code=201)
def post_feedback(
    classification_id: str,
    data: FeedbackCreate,
    db: Session = DbSession,
    client: ClientApp = ClientAppDependency,
):
    feedback = create_feedback(db, client, classification_id, data)
    return ok({"feedback_id": feedback.id, "status": feedback.status})
