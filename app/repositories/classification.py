from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models import (
    ClassificationCandidate,
    ClassificationEvidence,
    ClassificationFeedback,
    ClassificationResult,
    ClassificationResultObjective,
    ClassificationTask,
    ClassificationTaskPackage,
)


def get_task(db: Session, task_id: str, *, lock: bool = False):
    query = select(ClassificationTask).where(ClassificationTask.id == task_id)
    return db.scalar(query.with_for_update() if lock else query)


def find_idempotent_task(db: Session, client_app_id: str, client_request_id: str):
    return db.scalar(
        select(ClassificationTask).where(
            ClassificationTask.client_app_id == client_app_id,
            ClassificationTask.client_request_id == client_request_id,
        )
    )


def task_packages(db: Session, task_id: str):
    return list(
        db.scalars(
            select(ClassificationTaskPackage).where(
                ClassificationTaskPackage.task_id == task_id
            )
        )
    )


def recent_task_count(db: Session, client_app_id: str) -> int:
    since = utcnow() - timedelta(minutes=1)
    return (
        db.scalar(
            select(func.count(ClassificationTask.id)).where(
                ClassificationTask.client_app_id == client_app_id,
                ClassificationTask.created_at >= since,
            )
        )
        or 0
    )


def clear_result(db: Session, task_id: str) -> None:
    result = db.scalar(
        select(ClassificationResult).where(ClassificationResult.task_id == task_id)
    )
    if result:
        db.execute(
            delete(ClassificationEvidence).where(
                ClassificationEvidence.result_id == result.id
            )
        )
        db.execute(
            delete(ClassificationResultObjective).where(
                ClassificationResultObjective.result_id == result.id
            )
        )
        db.delete(result)
    db.execute(
        delete(ClassificationCandidate).where(
            ClassificationCandidate.task_id == task_id
        )
    )


def get_result(db: Session, task_id: str):
    return db.scalar(
        select(ClassificationResult).where(ClassificationResult.task_id == task_id)
    )


def result_objectives(db: Session, result_id: str):
    return list(
        db.scalars(
            select(ClassificationResultObjective)
            .where(ClassificationResultObjective.result_id == result_id)
            .order_by(ClassificationResultObjective.rank_no)
        )
    )


def result_evidence(db: Session, result_id: str):
    return list(
        db.scalars(
            select(ClassificationEvidence).where(
                ClassificationEvidence.result_id == result_id
            )
        )
    )


def find_feedback(db: Session, client_app_id: str, request_id: str):
    return db.scalar(
        select(ClassificationFeedback).where(
            ClassificationFeedback.client_app_id == client_app_id,
            ClassificationFeedback.feedback_request_id == request_id,
        )
    )
