from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.http import request_id_context
from app.core.time import utcnow
from app.models import AuditLog


def record(
    db: Session,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before,
            after_json=after,
            request_id=request_id_context.get() or None,
            created_at=utcnow(),
        )
    )
