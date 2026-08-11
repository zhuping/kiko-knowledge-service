from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel

KnowledgeType = Literal["concept", "skill", "problem_model", "strategy", "activity"]
GradeTerm = Literal["g1_t1", "g1_t2", "g2_t1", "g2_t2"]
KnowledgeScope = Literal["core", "supplement"]
KnowledgeStatus = Literal["pending", "published"]
KnowledgeBaseStatus = Literal["pending", "published", "offline"]
RelationStatus = Literal["pending", "published"]
RelationType = Literal["prerequisite", "parallel", "cross"]

GRADE_TERM_LABELS = {
    "g1_t1": "一年级上册",
    "g1_t2": "一年级下册",
    "g2_t1": "二年级上册",
    "g2_t2": "二年级下册",
}
SUBJECT_LABELS = {"math": "数学"}
KNOWLEDGE_TYPE_LABELS = {
    "concept": "概念",
    "skill": "技能",
    "problem_model": "问题模型",
    "strategy": "策略",
    "activity": "活动",
}
SCOPE_LABELS = {"core": "核心", "supplement": "补充"}
RELATION_TYPE_LABELS = {
    "prerequisite": "前置",
    "parallel": "平行",
    "cross": "交叉",
}


class KnowledgeBaseCreate(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    grade_term_code: GradeTerm
    subject_code: Literal["math"]
    textbook_edition_code: str
    row_version: int = 0


class KnowledgeBaseUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    row_version: int


class MappingCreate(CamelModel):
    catalog_node_id: int
    canonical_id: str
    row_version: int


class KnowledgeCreate(CamelModel):
    canonical_id: str | None = None
    knowledge_name: str = Field(min_length=1, max_length=100)
    knowledge_type: KnowledgeType
    grade_term_code: GradeTerm
    scope: KnowledgeScope
    ocr_signals: list[str] = Field(default_factory=list)
    exercise_signature: str | None = None
    row_version: int = 0


class KnowledgeUpdate(CamelModel):
    knowledge_name: str | None = Field(default=None, min_length=1, max_length=100)
    knowledge_type: KnowledgeType | None = None
    grade_term_code: GradeTerm | None = None
    scope: KnowledgeScope | None = None
    ocr_signals: list[str] | None = None
    exercise_signature: str | None = None
    row_version: int


class RelationCreate(CamelModel):
    canonical_id: str
    prerequisite_canonical_ids: list[str] = Field(default_factory=list)
    parallel_canonical_ids: list[str] = Field(default_factory=list)
    cross_canonical_ids: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=1000)
    row_version: int = 0


class RelationUpdate(CamelModel):
    operation: Literal["upsert", "delete"] = "upsert"
    relation_type: RelationType | None = None
    from_canonical_id: str | None = None
    to_canonical_id: str | None = None
    note: str | None = Field(default=None, max_length=1000)
    row_version: int


class KnowledgeSearch(CamelModel):
    keyword: str | None = None
    canonical_id: str | None = None
    grade_term_code: GradeTerm | None = None
    subject_code: str | None = None
    textbook_edition_code: str | None = None
    candidate_for_knowledge_base_id: int | None = None
    knowledge_type: KnowledgeType | None = None
    scope: KnowledgeScope | None = None
    knowledge_base_id: int | None = None
    status: KnowledgeStatus | None = None
    page_num: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)


class RelationSearch(CamelModel):
    canonical_id: str | None = None
    knowledge_name: str | None = None
    grade_term_code: GradeTerm | None = None
    knowledge_type: KnowledgeType | None = None
    knowledge_base_id: int | None = None
    status: RelationStatus | None = None
    page_num: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)


class OpenSearch(CamelModel):
    grade_term_code: GradeTerm | None = None
    subject_code: Literal["math"] | None = None
    textbook_edition_code: str | None = None
    release_version: str | None = None


class DetailsRequest(CamelModel):
    canonical_ids: list[str]
    release_version: str | None = None
