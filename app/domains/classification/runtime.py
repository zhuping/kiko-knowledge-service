from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import ApiError
from app.core.time import utcnow
from app.models import (
    ClassificationCandidate,
    ClassificationEvidence,
    ClassificationResult,
    ClassificationResultObjective,
    Exemplar,
    ExemplarObjective,
    Objective,
)
from app.providers import classifier
from app.repositories import catalog as catalog_repo
from app.repositories import classification as task_repo
from app.schemas.classification import ClassifierDecision

TERMINAL_STATES = {"completed", "needs_review", "failed"}


@dataclass
class Candidate:
    objective: Objective
    score: float
    feature_scores: dict
    exemplar_ids: list[str]
    conflicts: list[str]

    def prompt_data(
        self, exemplars: dict[str, Exemplar], links: list[ExemplarObjective]
    ) -> dict:
        positive_ids = {
            link.exemplar_id
            for link in links
            if link.objective_id == self.objective.id
            and link.role in {"primary", "supporting"}
        }
        summaries = [
            {
                "exemplar_id": item.id,
                "type": item.exemplar_type,
                "question": item.question_text[:500],
                "task_signature": item.task_signature_json,
            }
            for item in exemplars.values()
            if item.id in positive_ids and item.exemplar_type != "counterexample"
        ][:3]
        return {
            "objective_id": self.objective.id,
            "name": self.objective.name,
            "definition": self.objective.definition,
            "required_concepts": self.objective.required_concepts_json,
            "required_actions": self.objective.required_actions_json,
            "exclusions": self.objective.exclusions_json,
            "exemplars": summaries,
        }


def normalize_question(request_json: dict) -> str:
    question = request_json["question"]
    chunks = [question.get("text") or "", *(question.get("options") or [])]
    for field in ("answer", "analysis", "structured_content"):
        value = question.get(field)
        if value is not None:
            chunks.append(
                value
                if isinstance(value, str)
                else json.dumps(value, sort_keys=True, ensure_ascii=False)
            )
    text = "\n".join(chunks)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({"，": ",", "。": ".", "：": ":", "；": ";"}))
    return re.sub(r"\s+", " ", text).strip()[: settings.max_question_chars]


def _tokens(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text.lower())
    words = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", compact))
    grams = {
        compact[index : index + size]
        for size in (2, 3)
        for index in range(max(0, len(compact) - size + 1))
    }
    return {item for item in words | grams if item}


def _coverage(query: set[str], value: str) -> float:
    if not query:
        return 0
    return len(query & _tokens(value)) / len(query)


def retrieve(
    db: Session, version_ids: list[str], question: str
) -> tuple[list[Candidate], dict, list]:
    objectives = [
        objective
        for version_id in version_ids
        for objective in catalog_repo.list_objectives(db, version_id, active_only=True)
    ]
    exemplars_list = [
        exemplar
        for version_id in version_ids
        for exemplar in catalog_repo.list_exemplars(db, version_id, active_only=True)
    ]
    exemplars = {item.id: item for item in exemplars_list}
    links = catalog_repo.list_exemplar_links(db, list(exemplars))
    links_by_objective: dict[str, list[ExemplarObjective]] = {}
    for link in links:
        links_by_objective.setdefault(link.objective_id, []).append(link)
    query_tokens = _tokens(question)
    candidates = []
    for objective in objectives:
        objective_text = " ".join(
            [
                objective.name,
                objective.definition,
                objective.attainment,
                json.dumps(objective.required_concepts_json, ensure_ascii=False),
                json.dumps(objective.required_actions_json, ensure_ascii=False),
                json.dumps(objective.match_hints_json or [], ensure_ascii=False),
            ]
        )
        objective_score = _coverage(query_tokens, objective_text)
        positive_score = 0.0
        positive_ids = []
        conflicts = []
        for link in links_by_objective.get(objective.id, []):
            exemplar = exemplars.get(link.exemplar_id)
            if not exemplar:
                continue
            exemplar_text = " ".join(
                [
                    exemplar.question_text,
                    exemplar.solution_text or "",
                    json.dumps(exemplar.task_signature_json, ensure_ascii=False),
                ]
            )
            score = _coverage(query_tokens, exemplar_text)
            if exemplar.exemplar_type == "counterexample" or link.role == "distractor":
                if score >= 0.35:
                    conflicts.append(exemplar.id)
            elif score > positive_score:
                positive_score = score
                positive_ids = [exemplar.id]
        hint_score = (
            1.0
            if any(
                str(hint).lower() in question.lower()
                for hint in objective.match_hints_json or []
            )
            else 0.0
        )
        score = max(
            0.0,
            min(
                1.0,
                objective_score * 0.25
                + positive_score * 0.65
                + hint_score * 0.10
                - min(0.25, len(conflicts) * 0.1),
            ),
        )
        # ponytail: lexical floor rejects one-character noise; tune from gold data.
        if score >= 0.1:
            candidates.append(
                Candidate(
                    objective,
                    score,
                    {
                        "objective": round(objective_score, 5),
                        "exemplar": round(positive_score, 5),
                        "hint": hint_score,
                    },
                    positive_ids,
                    conflicts,
                )
            )
    candidates.sort(key=lambda item: (-item.score, item.objective.id))
    return candidates[:10], exemplars, links


def validate_decision(
    decision: ClassifierDecision,
    candidates: list[Candidate],
    exemplars: dict[str, Exemplar],
    links: list[ExemplarObjective],
) -> None:
    candidate_ids = {item.objective.id for item in candidates}
    selected = [
        item
        for item in [decision.primary_objective_id, *decision.secondary_objective_ids]
        if item
    ]
    if len(selected) != len(set(selected)) or not set(selected) <= candidate_ids:
        raise ValueError("模型返回了候选列表外或重复的目标")
    allowed_evidence = {
        (link.exemplar_id, link.objective_id)
        for link in links
        if link.role in {"primary", "supporting"}
        and link.objective_id in set(selected)
        and link.exemplar_id in exemplars
        and exemplars[link.exemplar_id].exemplar_type != "counterexample"
    }
    for exemplar_id in decision.evidence_exemplar_ids:
        if not any(item[0] == exemplar_id for item in allowed_evidence):
            raise ValueError("模型返回了无效或无授权的正向证据")


def confidence(decision: ClassifierDecision, candidates: list[Candidate]) -> float:
    if decision.match_type == "unmatched" or not candidates:
        return 0.0
    chosen = next(
        item
        for item in candidates
        if item.objective.id == decision.primary_objective_id
    )
    runner_up = next(
        (item.score for item in candidates if item.objective.id != chosen.objective.id),
        0.0,
    )
    margin = max(0.0, chosen.score - runner_up)
    agrees = chosen.objective.id == candidates[0].objective.id
    evidence = bool(decision.evidence_exemplar_ids)
    value = (
        chosen.score * 0.65
        + margin * 0.15
        + (0.1 if agrees else 0)
        + (0.1 if evidence else 0)
        - min(0.2, len(chosen.conflicts) * 0.1)
    )
    return round(max(0.0, min(1.0, value)), 4)


def _node_position(db: Session, node_id: str) -> tuple[int, ...]:
    return tuple(item.order_no for item in catalog_repo.node_path(db, node_id))


def calculate_scope(
    db: Session,
    task,
    selected_ids: list[str],
    score: float,
    match_type: str,
) -> str:
    if match_type == "unmatched" or not selected_ids:
        return "unknown_scope"
    packages = task_repo.task_packages(db, task.id)
    roles = {item.package_version_id: item.role for item in packages}
    objectives = [db.get(Objective, item) for item in selected_ids]
    selected_roles = {roles.get(item.package_version_id) for item in objectives if item}
    if len(selected_roles) > 1:
        return "cross_scope"
    role = next(iter(selected_roles), None)
    if role == "previous":
        return "previous_scope"
    if role == "later":
        return "later_scope" if score >= 0.85 else "unknown_scope"
    context = task.request_json.get("curriculum_context")
    if not context:
        return "unknown_scope"
    active_nodes = set(context.get("active_node_ids") or [])
    if active_nodes:
        inside = []
        for objective in objectives:
            path_ids = {
                item.logical_id
                for item in catalog_repo.node_path(db, objective.node_id)
            }
            inside.append(bool(path_ids & active_nodes))
        if all(inside):
            return "in_scope"
        if any(inside):
            return "cross_scope"
        active_node_rows = [
            item
            for item in catalog_repo.list_nodes(db, task.active_package_version_id)
            if item.logical_id in active_nodes
        ]
        if not active_node_rows:
            return "unknown_scope"
        active_positions = [_node_position(db, item.id) for item in active_node_rows]
        selected_positions = [_node_position(db, item.node_id) for item in objectives]
        if all(position < min(active_positions) for position in selected_positions):
            return "previous_scope"
        if all(position > max(active_positions) for position in selected_positions):
            return "later_scope" if score >= 0.85 else "unknown_scope"
        return "cross_scope"
    learned = context.get("learned_through_node_id")
    if learned:
        learned_node = next(
            (
                item
                for item in catalog_repo.list_nodes(db, task.active_package_version_id)
                if item.logical_id == learned
            ),
            None,
        )
        if not learned_node:
            return "unknown_scope"
        positions = [_node_position(db, item.node_id) for item in objectives]
        learned_position = _node_position(db, learned_node.id)
        earlier = [position <= learned_position for position in positions]
        if all(earlier):
            return "previous_scope"
        if any(earlier):
            return "cross_scope"
        return "later_scope" if score >= 0.85 else "unknown_scope"
    return "in_scope"


def _choose(question, candidates, exemplars, links, classify_fn):
    prompt = [item.prompt_data(exemplars, links) for item in candidates]
    last_error = None
    for _attempt in range(2):
        try:
            decision = classify_fn(question, prompt)
            validate_decision(decision, candidates, exemplars, links)
            return decision
        except (ValueError, ApiError) as exc:
            last_error = exc
    raise classifier.ClassifierUnavailable("模型输出未通过程序校验") from last_error


def _persist_candidates(db: Session, task_id: str, candidates: list[Candidate]) -> None:
    for rank, item in enumerate(candidates[:5], start=1):
        db.add(
            ClassificationCandidate(
                task_id=task_id,
                objective_id=item.objective.id,
                rank_no=rank,
                retrieval_score=Decimal(str(round(item.score, 5))),
                feature_score_json=item.feature_scores,
                matched_exemplar_ids_json=item.exemplar_ids,
                conflicts_json=item.conflicts,
                created_at=utcnow(),
            )
        )


def _persist_result(
    db: Session,
    task,
    decision: ClassifierDecision,
    candidates: list[Candidate],
    exemplars: dict[str, Exemplar],
    score: float,
) -> None:
    selected = [
        item
        for item in [decision.primary_objective_id, *decision.secondary_objective_ids]
        if item
    ]
    scope = calculate_scope(db, task, selected, score, decision.match_type)
    result = ClassificationResult(
        task_id=task.id,
        primary_objective_id=decision.primary_objective_id,
        match_type=decision.match_type,
        scope_status=scope,
        confidence_score=Decimal(str(score)),
        requires_confirmation=score < 0.85,
        reason_summary=decision.reason_summary,
        task_signature_json=decision.task_signature,
        classifier_version=settings.classifier_version,
        prompt_version=settings.classifier_prompt_version,
        created_at=utcnow(),
    )
    db.add(result)
    for rank, objective_id in enumerate(selected, start=1):
        db.add(
            ClassificationResultObjective(
                result_id=result.id,
                objective_id=objective_id,
                role="primary" if rank == 1 else "secondary",
                rank_no=rank,
            )
        )
    for exemplar_id in decision.evidence_exemplar_ids:
        exemplar = exemplars[exemplar_id]
        objective_id = next(
            item
            for item in selected
            if db.query(ExemplarObjective)
            .filter_by(exemplar_id=exemplar.id, objective_id=item)
            .first()
        )
        db.add(
            ClassificationEvidence(
                result_id=result.id,
                exemplar_id=exemplar.id,
                objective_id=objective_id,
                reason_summary=decision.reason_summary[:500],
                display_level=exemplar.display_level,
                created_at=utcnow(),
            )
        )
    task.status = (
        "completed"
        if decision.match_type == "unmatched" or score >= 0.65
        else "needs_review"
    )
    task.completed_at = utcnow()


def process_task(task_id: str, classify_fn=None) -> None:
    classify_fn = classify_fn or classifier.classify
    with SessionLocal() as db:
        task = task_repo.get_task(db, task_id, lock=True)
        if not task or task.status in TERMINAL_STATES:
            return
        if task.status == "processing" and task.processing_started_at:
            elapsed = (utcnow() - task.processing_started_at).total_seconds()
            if elapsed < settings.classification_timeout_seconds:
                return
        task.status = "processing"
        task.processing_started_at = utcnow()
        db.commit()
        question = normalize_question(task.request_json)
        version_ids = [
            item.package_version_id for item in task_repo.task_packages(db, task.id)
        ]
        candidates, exemplars, links = retrieve(db, version_ids, question)
        db.commit()  # Do not hold a transaction during the model call.
        try:
            if candidates:
                decision = _choose(question, candidates, exemplars, links, classify_fn)
            else:
                decision = ClassifierDecision(
                    primary_objective_id=None,
                    match_type="unmatched",
                    reason_summary="当前知识包没有足够证据完成匹配",
                )
            score = confidence(decision, candidates)
            task = task_repo.get_task(db, task.id, lock=True)
            if task.status != "processing":
                db.rollback()
                return
            task_repo.clear_result(db, task.id)
            _persist_candidates(db, task.id, candidates)
            _persist_result(db, task, decision, candidates, exemplars, score)
            db.commit()
        except classifier.ClassifierUnavailable as exc:
            db.rollback()
            task = task_repo.get_task(db, task_id, lock=True)
            task_repo.clear_result(db, task.id)
            _persist_candidates(db, task.id, candidates)
            task.status = "needs_review"
            task.failure_code = "CLASSIFIER_UNAVAILABLE"
            task.failure_message = str(exc)[:512]
            task.completed_at = utcnow()
            db.commit()
        except Exception as exc:
            db.rollback()
            task = task_repo.get_task(db, task_id, lock=True)
            if task and task.status == "processing":
                task.status = "failed"
                task.failure_code = "CLASSIFICATION_FAILED"
                task.failure_message = type(exc).__name__
                task.completed_at = utcnow()
                db.commit()
            raise
