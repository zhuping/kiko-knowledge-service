from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.core.security import AdminContext, require_role
from app.core.time import utcnow
from app.domains.classification.runtime import (
    _choose,
    normalize_question,
    retrieve,
)
from app.models import GoldTestCase, Objective, PackageVersion, RegressionRun
from app.providers import classifier
from app.repositories import catalog as catalog_repo
from app.schemas.admin import GoldTestCreate


def create_case(db: Session, actor: AdminContext, data: GoldTestCreate) -> GoldTestCase:
    require_role(actor, "reviewer", "admin", package_id=data.package_id)
    if not catalog_repo.get_package(db, data.package_id):
        raise ApiError(404, "UNKNOWN_PACKAGE", "知识包不存在")
    case = GoldTestCase(
        package_id=data.package_id,
        question_json=data.question,
        scope_context_json=data.scope_context,
        expected_json=data.expected,
        status="active",
    )
    db.add(case)
    db.commit()
    return case


def _gold_scope(
    db: Session, version_id: str, objective: Objective, context: dict
) -> str:
    if not context:
        return "unknown_scope"
    path = catalog_repo.node_path(db, objective.node_id)
    active = set(context.get("active_node_ids") or [])
    if active and any(item.logical_id in active for item in path):
        return "in_scope"
    learned = context.get("learned_through_node_id")
    if not learned:
        return "in_scope"
    learned_node = next(
        (
            item
            for item in catalog_repo.list_nodes(db, version_id)
            if item.logical_id == learned
        ),
        None,
    )
    if not learned_node:
        return "unknown_scope"
    learned_position = tuple(
        item.order_no for item in catalog_repo.node_path(db, learned_node.id)
    )
    position = tuple(item.order_no for item in path)
    return "previous_scope" if position <= learned_position else "later_scope"


def run(
    db: Session,
    actor: AdminContext,
    version_id: str,
    classify_fn=None,
) -> RegressionRun:
    version = db.get(PackageVersion, version_id)
    if not version:
        raise ApiError(404, "PACKAGE_VERSION_NOT_FOUND", "知识包版本不存在")
    require_role(actor, "reviewer", "admin", package_id=version.package_id)
    cases = (
        db.query(GoldTestCase)
        .filter_by(package_id=version.package_id, status="active")
        .all()
    )
    regression = RegressionRun(
        package_version_id=version.id,
        classifier_version=settings.classifier_version,
        started_at=utcnow(),
    )
    db.add(regression)
    db.commit()
    classify_fn = classify_fn or classifier.classify
    rows = []
    try:
        for case in cases:
            request = {"question": case.question_json}
            question = normalize_question(request)
            candidates, exemplars, links = retrieve(db, [version.id], question)
            db.commit()
            decision = (
                _choose(question, candidates, exemplars, links, classify_fn)
                if candidates
                else None
            )
            primary = (
                db.get(Objective, decision.primary_objective_id)
                if decision and decision.primary_objective_id
                else None
            )
            predicted_scope = (
                _gold_scope(
                    db,
                    version.id,
                    primary,
                    case.scope_context_json or {},
                )
                if primary
                else "unknown_scope"
            )
            rows.append(
                {
                    "expected": case.expected_json,
                    "top5": [item.objective.logical_id for item in candidates[:5]],
                    "primary": primary.logical_id if primary else None,
                    "match_type": decision.match_type if decision else "unmatched",
                    "scope_status": predicted_scope,
                    "evidence_valid": bool(
                        not decision
                        or decision.match_type == "unmatched"
                        or decision.evidence_exemplar_ids
                        and all(
                            item in exemplars for item in decision.evidence_exemplar_ids
                        )
                    ),
                }
            )
    except classifier.ClassifierUnavailable:
        rows = []
    metrics = _metrics(rows, len(cases))
    regression = db.get(RegressionRun, regression.id)
    regression.metrics_json = metrics
    regression.passed = metrics["passed"]
    regression.completed_at = utcnow()
    version = db.get(PackageVersion, version.id)
    if version.status in {"draft", "in_review"}:
        version.benchmark_result_json = metrics
    db.commit()
    return regression


def _metrics(rows: list[dict], total: int) -> dict:
    if not total or len(rows) != total:
        return {
            "top5_recall": 0,
            "primary_accuracy": 0,
            "later_scope_precision": 0,
            "later_scope_false_positive": 1,
            "evidence_validity": 0,
            "invalid_objective_ids": 0,
            "passed": False,
            "case_count": total,
        }
    top5 = sum(
        row["expected"].get("primary_objective_id") in row["top5"] for row in rows
    )
    primary = sum(
        row["expected"].get("primary_objective_id") == row["primary"] for row in rows
    )
    predicted_later = [row for row in rows if row["scope_status"] == "later_scope"]
    correct_later = sum(
        row["expected"].get("scope_status") == "later_scope" for row in predicted_later
    )
    false_later = len(predicted_later) - correct_later
    later_precision = correct_later / len(predicted_later) if predicted_later else 1
    false_positive = false_later / total
    evidence_validity = sum(row["evidence_valid"] for row in rows) / total
    metrics = {
        "top5_recall": top5 / total,
        "primary_accuracy": primary / total,
        "later_scope_precision": later_precision,
        "later_scope_false_positive": false_positive,
        "evidence_validity": evidence_validity,
        "invalid_objective_ids": 0,
        "case_count": total,
    }
    metrics["passed"] = (
        metrics["top5_recall"] >= 0.95
        and metrics["primary_accuracy"] >= 0.9
        and metrics["later_scope_precision"] >= 0.95
        and metrics["later_scope_false_positive"] <= 0.02
        and metrics["evidence_validity"] == 1
    )
    return metrics
