from datetime import timedelta

from sqlalchemy import or_, select

from app.celery_app import celery
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.time import utcnow
from app.models import ClassificationTask
from app.workers.classification import classify_task


@celery.task(
    name="knowledge.recover_classification_tasks", queue="knowledge-maintenance"
)
def recover_classification_tasks() -> int:
    now = utcnow()
    deadline = now - timedelta(seconds=settings.classification_timeout_seconds)
    dispatch_deadline = now - timedelta(
        seconds=settings.classification_dispatch_wait_seconds
    )
    task_ids = []
    with SessionLocal() as db:
        tasks = list(
            db.scalars(
                select(ClassificationTask)
                .where(
                    ClassificationTask.retry_count
                    < settings.classification_max_retries,
                    or_(
                        (
                            (ClassificationTask.status == "received")
                            & (ClassificationTask.created_at < dispatch_deadline)
                        ),
                        (
                            (ClassificationTask.status == "processing")
                            & (ClassificationTask.processing_started_at < deadline)
                        ),
                    ),
                )
                .with_for_update(skip_locked=True)
            )
        )
        for task in tasks:
            task.retry_count += 1
            task.status = "received"
            task.processing_started_at = None
            task_ids.append(task.id)
        db.commit()
    for task_id in task_ids:
        classify_task.delay(task_id)
    return len(task_ids)
