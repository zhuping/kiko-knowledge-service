from app.celery_app import celery
from app.domains.classification.runtime import process_task


@celery.task(name="knowledge.classify", queue="knowledge-classification")
def classify_task(task_id: str) -> None:
    process_task(task_id)
