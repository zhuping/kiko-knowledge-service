from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.http import ok
from app.core.database import DbSession
from app.core.errors import ApiError
from app.core.security import AdminContext, get_admin_context, require_role
from app.core.serialization import model_dict
from app.domains.access import service as access_service
from app.domains.feedback.service import review_feedback
from app.domains.gold_regression import service as regression_service
from app.models import (
    AuditLog,
    ClassificationFeedback,
    ClassificationTask,
    ClientApp,
    FeedbackReview,
    GoldTestCase,
    RegressionRun,
)
from app.schemas.admin import (
    ClientAppCreate,
    FeedbackReviewCreate,
    GoldTestCreate,
)

router = APIRouter(prefix="/admin", tags=["admin-operations"])


@router.get("/client-apps")
def client_apps(
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    require_role(actor, "admin")
    rows = db.scalars(select(ClientApp).order_by(ClientApp.code)).all()
    return ok([model_dict(item, exclude={"secret_digest"}) for item in rows])


@router.post("/client-apps", status_code=201)
def post_client_app(
    data: ClientAppCreate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    client, token = access_service.create_client_app(db, actor, data)
    return ok(
        {
            **model_dict(client, exclude={"secret_digest"}),
            "api_key": token,
        }
    )


@router.post("/client-apps/{client_id}/rotate-key")
def rotate_client_key(
    client_id: str,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    client, token = access_service.rotate_key(db, actor, client_id)
    return ok({"id": client.id, "key_id": client.key_id, "api_key": token})


@router.post("/client-apps/{client_id}/disable")
def disable_client(
    client_id: str,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    return ok(
        model_dict(
            access_service.set_status(db, actor, client_id, "disabled"),
            exclude={"secret_digest"},
        )
    )


@router.post("/client-apps/{client_id}/enable")
def enable_client(
    client_id: str,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    return ok(
        model_dict(
            access_service.set_status(db, actor, client_id, "active"),
            exclude={"secret_digest"},
        )
    )


@router.get("/feedback")
def feedback_list(
    status: str | None = None,
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    require_role(_actor, "reviewer", "admin")
    query = select(ClassificationFeedback).order_by(
        ClassificationFeedback.created_at.desc()
    )
    if status:
        query = query.where(ClassificationFeedback.status == status)
    return ok([model_dict(item) for item in db.scalars(query)])


@router.get("/feedback/{feedback_id}")
def feedback_detail(
    feedback_id: str,
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    require_role(_actor, "reviewer", "admin")
    feedback = db.get(ClassificationFeedback, feedback_id)
    if not feedback:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "反馈不存在")
    review = db.scalar(
        select(FeedbackReview).where(FeedbackReview.feedback_id == feedback.id)
    )
    return ok(
        {
            **model_dict(feedback),
            "review": model_dict(review) if review else None,
        }
    )


@router.post("/feedback/{feedback_id}/review")
def post_feedback_review(
    feedback_id: str,
    data: FeedbackReviewCreate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    return ok(model_dict(review_feedback(db, actor, feedback_id, data)))


@router.get("/classifications")
def classifications(
    status: str | None = None,
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    require_role(_actor, "viewer", "editor", "reviewer", "publisher", "admin")
    query = select(ClassificationTask).order_by(ClassificationTask.created_at.desc())
    if status:
        query = query.where(ClassificationTask.status == status)
    rows = db.scalars(query.limit(200)).all()
    return ok(
        [
            model_dict(
                item,
                exclude={"request_json", "failure_message"},
            )
            for item in rows
        ]
    )


@router.get("/classifications/{task_id}")
def classification_detail(
    task_id: str,
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    require_role(_actor, "viewer", "editor", "reviewer", "publisher", "admin")
    task = db.get(ClassificationTask, task_id)
    if not task:
        raise ApiError(404, "CLASSIFICATION_NOT_FOUND", "判断任务不存在")
    return ok(model_dict(task))


@router.get("/gold-tests")
def gold_tests(
    package_id: str | None = None,
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    require_role(_actor, "reviewer", "admin")
    query = select(GoldTestCase).order_by(GoldTestCase.created_at.desc())
    if package_id:
        query = query.where(GoldTestCase.package_id == package_id)
    return ok([model_dict(item) for item in db.scalars(query)])


@router.post("/gold-tests", status_code=201)
def post_gold_test(
    data: GoldTestCreate,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    return ok(model_dict(regression_service.create_case(db, actor, data)))


@router.post("/regression-runs/{version_id}", status_code=201)
def post_regression_run(
    version_id: str,
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    return ok(model_dict(regression_service.run(db, actor, version_id)))


@router.get("/regression-runs")
def regression_runs(
    db: Session = DbSession,
    _actor: AdminContext = Depends(get_admin_context),
):
    require_role(_actor, "reviewer", "publisher", "admin")
    rows = db.scalars(
        select(RegressionRun).order_by(RegressionRun.started_at.desc())
    ).all()
    return ok([model_dict(item) for item in rows])


@router.get("/audit-logs")
def audit_logs(
    db: Session = DbSession,
    actor: AdminContext = Depends(get_admin_context),
):
    require_role(actor, "viewer", "reviewer", "publisher", "admin")
    rows = db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500)
    ).all()
    return ok([model_dict(item) for item in rows])
