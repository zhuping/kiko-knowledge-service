from celery import Celery

from app.core.config import settings

celery = Celery(
    "kiko-knowledge-service",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.classification", "app.workers.maintenance"],
)
celery.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_default_queue="knowledge-classification",
    beat_schedule={
        "recover-classification-tasks": {
            "task": "knowledge.recover_classification_tasks",
            "schedule": 30.0,
            "options": {"queue": "knowledge-maintenance"},
        }
    },
)
