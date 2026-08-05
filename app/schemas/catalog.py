from typing import Any, Literal, Optional

from fastapi import Query
from pydantic import Field

from app.schemas.common import CamelModel

KnowledgeType = Literal["concept", "skill", "problem_model", "strategy", "activity"]
GradeTerm = Literal["一年级上册", "一年级下册", "二年级上册", "二年级下册"]
KnowledgeScope = Literal["core", "supplement"]
KnowledgeStatus = Literal["draft", "active", "disabled"]
Importance = Literal["core", "important", "general"]
CognitiveLevel = Literal["remember", "understand", "apply", "analyze"]
RelationType = Literal["prerequisite", "parallel", "cross"]
MappingType = Literal["introduction", "exercise", "review", "application"]
AlignmentType = Literal["equivalent", "narrower", "broader", "related"]


class CatalogNodeCreate(CamelModel):
    space_code: str = "default"
    edition_code: str = "pep_math_2024_63"
    parent_id: Optional[int] = None
    level: Literal[1, 2, 3, 4]
    node_type: str
    title: str
    sort_order: int = 0


class CatalogNodeUpdate(CamelModel):
    title: Optional[str] = None
    status: Optional[KnowledgeStatus] = None
    row_version: int


class CatalogNodeMove(CamelModel):
    sort_order: int
    row_version: int


class KnowledgeCreate(CamelModel):
    canonical_id: str
    group_node_id: int
    knowledge_name: str
    knowledge_type: KnowledgeType
    grade_term: GradeTerm
    scope: KnowledgeScope
    cognitive_level: CognitiveLevel
    importance: Importance
    aliases: list[str] = Field(default_factory=list)
    core_keywords: list[str] = Field(default_factory=list)
    derivative_keywords: list[str] = Field(default_factory=list)
    ocr_signals: list[str] = Field(default_factory=list)
    exercise_signature: Optional[str] = None
    solution_feature: Optional[str] = None
    scene_feature: Optional[str] = None
    numeric_feature: Optional[str] = None
    row_version: int = 0


class KnowledgeUpdate(CamelModel):
    knowledge_name: Optional[str] = None
    knowledge_type: Optional[KnowledgeType] = None
    grade_term: Optional[GradeTerm] = None
    scope: Optional[KnowledgeScope] = None
    cognitive_level: Optional[CognitiveLevel] = None
    importance: Optional[Importance] = None
    aliases: Optional[list[str]] = None
    core_keywords: Optional[list[str]] = None
    derivative_keywords: Optional[list[str]] = None
    ocr_signals: Optional[list[str]] = None
    exercise_signature: Optional[str] = None
    solution_feature: Optional[str] = None
    scene_feature: Optional[str] = None
    numeric_feature: Optional[str] = None
    row_version: int


class KnowledgeStatusOperation(CamelModel):
    canonical_id: str
    status: KnowledgeStatus
    row_version: int


class KnowledgeStatusBatch(CamelModel):
    operations: list[KnowledgeStatusOperation]


class CatalogKnowledgeAttach(CamelModel):
    space_code: str = "default"
    edition_code: str = "pep_math_2024_63"
    group_node_id: int
    canonical_id: str
    sort_order: int = 0


class KnowledgeNodeMove(CamelModel):
    sort_order: int
    row_version: int


class TextbookMappingCreate(CamelModel):
    space_code: str = "default"
    edition_code: str = "pep_math_2024_63"
    canonical_id: str
    catalog_node_id: Optional[int] = None
    textbook_path: str
    mapping_type: MappingType
    alignment_type: AlignmentType = "equivalent"
    edition_label: Optional[str] = None
    edition_keywords: list[str] = Field(default_factory=list)
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    evidence: Optional[str] = None


class RelationCreate(CamelModel):
    space_code: str = "default"
    edition_code: Optional[str] = "pep_math_2024_63"
    from_canonical_id: str
    to_canonical_id: str
    relation_type: RelationType
    basis: Optional[str] = None
    note: Optional[str] = None


class RelationOperation(RelationCreate):
    operation: Literal["add", "disable", "restore"] = "add"


class RelationBatch(CamelModel):
    operations: list[RelationOperation]


class PolicyMappingCreate(CamelModel):
    space_code: str = "default"
    canonical_id: str
    policy_rule_id: int
    applicable_condition: dict[str, Any] = Field(default_factory=dict)
    basis: Optional[str] = None


class SearchRequest(CamelModel):
    keyword: Optional[str] = None
    canonical_id: Optional[str] = None
    grade_term: Optional[GradeTerm] = None
    knowledge_type: Optional[KnowledgeType] = None
    scope: Optional[KnowledgeScope] = None
    status: Optional[KnowledgeStatus] = None
    page_num: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)
    release_version: Optional[str] = None


class DetailsRequest(CamelModel):
    canonical_ids: list[str]
    release_version: Optional[str] = None


class ScopeRequest(CamelModel):
    canonical_ids: list[str] = Field(default_factory=list)
    edition_code: Optional[str] = None
    grade_term: Optional[GradeTerm] = None
    rule_version: Optional[str] = None
    question_context: dict[str, Any] = Field(default_factory=dict)


def catalog_query_params(
    edition_code: str = Query("pep_math_2024_63", alias="editionCode"),
    space_code: str = Query("default", alias="spaceCode"),
) -> tuple[str, str]:
    return edition_code, space_code
