from __future__ import annotations

import json
import re
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessError
from app.models import (
    AuditLog,
    Job,
    KnowledgeObject,
    KnowledgeRelation,
    TextbookMapping,
)
from app.models.base import utc_now
from app.modules.catalog.service import (
    _change,
    _write_terms,
    ensure_context,
    knowledge_payload,
    mapping_payload,
    relation_payload,
)

IMPORT_SHEET = "knowledge_points"
IMPORT_HEADERS = (
    "canonical_id",
    "type",
    "name",
    "grade_term",
    "scope",
    "pep24_path",
    "ocr_signals",
    "exercise_signature",
    "prerequisites",
)
MAX_IMPORT_ROWS = 1000
MAX_IMPORT_BYTES = 10 * 1024 * 1024
CANONICAL_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
KNOWLEDGE_TYPES = {"concept", "skill", "problem_model", "strategy", "activity"}
GRADE_TERMS = {"一年级上册", "一年级下册", "二年级上册", "二年级下册"}
SCOPES = {"core", "supplement"}


def _error(row_number: int, field: str, reason: str, suggestion: str) -> dict[str, Any]:
    return {
        "rowNumber": row_number,
        "field": field,
        "reason": reason,
        "suggestion": suggestion,
    }


def _validate_workbook(
    content: bytes,
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise BusinessError("FILE_INVALID", "Excel 文件无法读取", 422) from exc

    if IMPORT_SHEET not in workbook.sheetnames:
        return (
            0,
            [
                _error(
                    0,
                    "knowledge_points",
                    "缺少 knowledge_points 工作表",
                    "请使用模板或将主工作表重命名为 knowledge_points",
                )
            ],
            [],
            [],
        )

    sheet = workbook[IMPORT_SHEET]
    header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
    headers = tuple(
        str(value).strip() if value is not None else "" for value in header_row
    )
    missing_headers = [header for header in IMPORT_HEADERS if header not in headers]
    if missing_headers:
        return (
            0,
            [
                _error(
                    1,
                    "表头",
                    f"缺少必填列：{', '.join(missing_headers)}",
                    "请使用系统提供的 Excel 模板",
                )
            ],
            [],
            [],
        )

    header_indexes = {header: headers.index(header) for header in IMPORT_HEADERS}
    rows = [
        row
        for row in sheet.iter_rows(min_row=2, values_only=True)
        if any(value is not None and str(value).strip() for value in row)
    ]
    errors: list[dict[str, Any]] = []
    if not rows:
        errors.append(
            _error(2, "knowledge_points", "没有可导入的数据", "至少填写一行知识点数据")
        )
    if len(rows) > MAX_IMPORT_ROWS:
        errors.append(
            _error(
                0,
                "数据行数",
                f"单次最多导入 {MAX_IMPORT_ROWS} 行",
                "请拆分 Excel 文件后分批上传",
            )
        )

    required_fields = (
        "canonical_id",
        "type",
        "name",
        "grade_term",
        "scope",
        "pep24_path",
    )
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        record: dict[str, Any] = {}
        for field in IMPORT_HEADERS:
            value = (
                row[header_indexes[field]] if header_indexes[field] < len(row) else None
            )
            record[field] = str(value).strip() if value is not None else ""
        for field in required_fields:
            if not record[field]:
                errors.append(_error(row_number, field, "不能为空", "请补充该字段"))
        for field in ("ocr_signals", "prerequisites"):
            value = record[field]
            if not value:
                record[field] = []
                continue
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = None
            if not isinstance(parsed, list):
                errors.append(
                    _error(
                        row_number,
                        field,
                        "必须是 JSON 数组",
                        '例如填写 [] 或 ["关键词"]',
                    )
                )
            else:
                record[field] = parsed
        if record["canonical_id"]:
            if not CANONICAL_ID.fullmatch(record["canonical_id"]):
                errors.append(
                    _error(
                        row_number,
                        "canonical_id",
                        "格式无效",
                        "请使用小写语义段并用英文句点分隔",
                    )
                )
            if record["canonical_id"] in seen_ids:
                errors.append(
                    _error(
                        row_number,
                        "canonical_id",
                        "文件内重复",
                        "每个 canonical_id 只能出现一次",
                    )
                )
            seen_ids.add(record["canonical_id"])
        for field, allowed in (
            ("type", KNOWLEDGE_TYPES),
            ("grade_term", GRADE_TERMS),
            ("scope", SCOPES),
        ):
            if record[field] and record[field] not in allowed:
                errors.append(
                    _error(row_number, field, "枚举值无效", "请按模板中的允许值填写")
                )
        records.append(record)

    relations: list[dict[str, Any]] = []
    if "prerequisites" in workbook.sheetnames:
        relation_sheet = workbook["prerequisites"]
        relation_header_row = next(
            relation_sheet.iter_rows(min_row=1, max_row=1, values_only=True), ()
        )
        relation_headers = tuple(
            str(value).strip() if value is not None else ""
            for value in relation_header_row
        )
        relation_fields = ("from_canonical_id", "to_canonical_id", "relation_type")
        missing_relation_headers = [
            field for field in relation_fields if field not in relation_headers
        ]
        if missing_relation_headers:
            errors.append(
                _error(
                    1,
                    "prerequisites",
                    f"缺少必填列：{', '.join(missing_relation_headers)}",
                    "请使用系统提供的 Excel 模板",
                )
            )
        else:
            relation_indexes = {
                field: relation_headers.index(field) for field in relation_fields
            }
            for row_number, row in enumerate(
                relation_sheet.iter_rows(min_row=2, values_only=True), start=2
            ):
                if not any(value is not None and str(value).strip() for value in row):
                    continue
                relation = {
                    field: str(row[relation_indexes[field]]).strip()
                    if row[relation_indexes[field]] is not None
                    else ""
                    for field in relation_fields
                }
                for field in relation_fields:
                    if not relation[field]:
                        errors.append(
                            _error(row_number, field, "不能为空", "请补充该字段")
                        )
                if relation["relation_type"] not in {"prerequisite"}:
                    errors.append(
                        _error(
                            row_number,
                            "relation_type",
                            "只支持 prerequisite",
                            "请按模板填写",
                        )
                    )
                relation["row_number"] = row_number
                relations.append(relation)

    return len(rows), errors, records, relations


def _job_response(job: Job) -> dict[str, Any]:
    payload = job.payload_json or {}
    errors = payload.get("errors", [])
    terminal = job.status in {"success", "failed", "cancelled"}
    return {
        "jobId": job.id,
        "jobType": job.job_type,
        "status": job.status,
        "totalCount": job.total_count,
        "successCount": job.success_count,
        "failureCount": job.failure_count,
        "progressPercent": 100 if terminal else 0,
        "errorFileId": job.error_file,
        "canRetry": False,
        "errorCount": len(errors),
        "committed": bool(payload.get("committed")),
        "canCommit": job.status == "success" and not payload.get("committed"),
    }


def create_import_job(
    session: Session,
    filename: str,
    content: bytes,
    actor: str,
    request_id: str,
) -> Job:
    if not filename.lower().endswith(".xlsx"):
        raise BusinessError("FILE_INVALID", "仅支持 .xlsx 格式的 Excel 文件", 422)
    if len(content) > MAX_IMPORT_BYTES:
        raise BusinessError("FILE_TOO_LARGE", "Excel 文件不能超过 10 MB", 413)

    total_count, errors, records, relations = _validate_workbook(content)
    status = "failed" if errors else "success"
    job = Job(
        job_type="import",
        status=status,
        total_count=total_count,
        success_count=total_count if not errors else 0,
        failure_count=0 if not errors else total_count,
        # ponytail: keep validated rows in job JSON for V1.
        # Move to file storage before larger imports.
        payload_json={
            "filename": filename,
            "errors": errors,
            "rows": records if not errors else [],
            "relations": relations if not errors else [],
        },
        created_by=actor,
    )
    session.add(job)
    session.flush()
    session.add(
        AuditLog(
            actor_id=actor,
            action="import.create",
            entity_type="job",
            entity_key=str(job.id),
            summary=filename,
            request_id=request_id,
            created_at=utc_now(),
        )
    )
    session.commit()
    return job


def get_job(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise BusinessError("NOT_FOUND", "任务不存在", 404)
    return job


def list_job_errors(
    session: Session, job_id: int, page_num: int = 1, page_size: int = 10
) -> tuple[int, list[dict[str, Any]]]:
    errors = (get_job(session, job_id).payload_json or {}).get("errors", [])
    start = (page_num - 1) * page_size
    return len(errors), errors[start : start + page_size]


def commit_import_job(
    session: Session, job_id: int, actor: str, request_id: str
) -> Job:
    job = get_job(session, job_id)
    payload = job.payload_json or {}
    if payload.get("committed"):
        return job
    if job.status != "success":
        raise BusinessError(
            "VALIDATION_FAILED", "只有预校验通过的任务才能确认导入", 422
        )

    records = payload.get("rows", [])
    relations = payload.get("relations", [])
    if not records:
        raise BusinessError(
            "VALIDATION_FAILED", "任务没有可提交的数据，请重新上传 Excel", 422
        )
    canonical_ids = [record["canonical_id"] for record in records]
    existing_ids = set(
        session.scalars(
            select(KnowledgeObject.canonical_id).where(
                KnowledgeObject.canonical_id.in_(canonical_ids)
            )
        )
    )
    if existing_ids:
        raise BusinessError(
            "CONFLICT",
            f"知识点已存在：{', '.join(sorted(existing_ids)[:5])}",
            409,
        )

    known_ids = set(canonical_ids)
    missing_relation_ids = {
        value
        for relation in relations
        for value in (relation["from_canonical_id"], relation["to_canonical_id"])
        if value not in known_ids
    }
    if missing_relation_ids:
        raise BusinessError(
            "VALIDATION_FAILED",
            "前置关系引用不存在的知识点："
            f"{', '.join(sorted(missing_relation_ids)[:5])}",
            422,
        )

    space, edition = ensure_context(session)
    knowledge_by_id: dict[str, KnowledgeObject] = {}
    try:
        for record in records:
            knowledge = KnowledgeObject(
                canonical_id=record["canonical_id"],
                name=record["name"],
                type=record["type"],
                grade_term=record["grade_term"],
                scope=record["scope"],
                cognitive_level="understand",
                importance="general",
                exercise_signature=record["exercise_signature"] or None,
                created_by=actor,
                updated_by=actor,
            )
            session.add(knowledge)
            session.flush()
            _write_terms(
                session,
                knowledge,
                {
                    "aliases": [],
                    "core_keywords": [],
                    "derivative_keywords": [],
                    "ocr_signals": record["ocr_signals"],
                },
            )
            mapping = TextbookMapping(
                space_id=space.id,
                edition_id=edition.id,
                knowledge_id=knowledge.id,
                textbook_path=record["pep24_path"],
                mapping_type="introduction",
                alignment_type="equivalent",
                edition_keywords=[],
            )
            session.add(mapping)
            session.flush()
            _change(
                session,
                space.id,
                "knowledge_object",
                knowledge.canonical_id,
                knowledge_payload(session, knowledge),
                actor,
            )
            _change(
                session,
                space.id,
                "textbook_mapping",
                str(mapping.id),
                mapping_payload(session, mapping),
                actor,
            )
            knowledge_by_id[knowledge.canonical_id] = knowledge

        for item in relations:
            relation = KnowledgeRelation(
                space_id=space.id,
                from_knowledge_id=knowledge_by_id[item["from_canonical_id"]].id,
                to_knowledge_id=knowledge_by_id[item["to_canonical_id"]].id,
                relation_type=item["relation_type"],
                edition_id=edition.id,
            )
            session.add(relation)
            session.flush()
            _change(
                session,
                space.id,
                "knowledge_relation",
                str(relation.id),
                relation_payload(relation),
                actor,
            )

        payload["committed"] = True
        payload["committedAt"] = utc_now().isoformat()
        job.payload_json = payload
        session.add(
            AuditLog(
                actor_id=actor,
                action="import.commit",
                entity_type="job",
                entity_key=str(job.id),
                summary=payload.get("filename"),
                request_id=request_id,
                created_at=utc_now(),
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return job


def job_response(job: Job) -> dict[str, Any]:
    return _job_response(job)
