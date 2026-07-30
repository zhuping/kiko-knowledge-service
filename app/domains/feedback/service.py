from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import AdminContext, require_role
from app.core.time import utcnow
from app.domains.audit.service import record
from app.models import ClassificationFeedback, FeedbackReview
from app.schemas.admin import FeedbackReviewCreate


def review_feedback(
    db: Session,
    actor: AdminContext,
    feedback_id: str,
    data: FeedbackReviewCreate,
) -> ClassificationFeedback:
    require_role(actor, "reviewer", "admin")
    feedback = db.get(ClassificationFeedback, feedback_id)
    if not feedback:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "反馈不存在")
    if feedback.status not in {"submitted", "in_review"}:
        raise ApiError(409, "FEEDBACK_CONFLICT", "反馈已处理")
    review = FeedbackReview(
        feedback_id=feedback.id,
        reviewer_subject=actor.subject,
        decision=data.decision,
        action_type=data.action_type,
        review_note=data.review_note,
        reviewed_at=utcnow(),
    )
    feedback.status = data.decision
    db.add(review)
    record(
        db,
        actor_type="admin",
        actor_id=actor.subject,
        action=f"feedback.{data.decision}",
        resource_type="classification_feedback",
        resource_id=feedback.id,
        after={"action_type": data.action_type},
    )
    db.commit()
    return feedback
