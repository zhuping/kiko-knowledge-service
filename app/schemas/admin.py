from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PackageCreate(BaseModel):
    code: str = Field(min_length=1, max_length=96)
    subject_code: str = Field(min_length=1, max_length=32)
    grade: int = Field(ge=1, le=20)
    semester: str = Field(min_length=1, max_length=16)
    edition: str = Field(min_length=1, max_length=128)
    publisher: str | None = Field(default=None, max_length=128)
    curriculum_standard: str | None = Field(default=None, max_length=128)
    regions: list[str] | None = None
    initial_version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")


class VersionCreate(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    based_on_version_id: str | None = None
    release_notes: str | None = Field(default=None, max_length=10_000)


class NodeCreate(BaseModel):
    logical_id: str | None = None
    parent_id: str | None = None
    node_type: Literal["chapter", "unit", "lesson", "topic"]
    code: str = Field(min_length=1, max_length=96)
    name: str = Field(min_length=1, max_length=128)
    order_no: int = Field(ge=0)
    source: dict | None = None


class NodeUpdate(BaseModel):
    parent_id: str | None = None
    node_type: Literal["chapter", "unit", "lesson", "topic"] | None = None
    code: str | None = Field(default=None, min_length=1, max_length=96)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    order_no: int | None = Field(default=None, ge=0)
    source: dict | None = None
    status: Literal["active", "deprecated"] | None = None
    lock_version: int = Field(ge=1)


class ObjectiveCreate(BaseModel):
    logical_id: str | None = None
    node_id: str
    code: str = Field(min_length=1, max_length=96)
    name: str = Field(min_length=1, max_length=128)
    definition: str = Field(min_length=1, max_length=10_000)
    attainment: str = Field(min_length=1, max_length=10_000)
    required_concepts: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    allowed_variations: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    match_hints: list[str] | None = None
    source: dict


class ObjectiveUpdate(BaseModel):
    node_id: str | None = None
    code: str | None = Field(default=None, min_length=1, max_length=96)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    definition: str | None = Field(default=None, min_length=1, max_length=10_000)
    attainment: str | None = Field(default=None, min_length=1, max_length=10_000)
    required_concepts: list[str] | None = None
    required_actions: list[str] | None = None
    allowed_variations: list[str] | None = None
    exclusions: list[str] | None = None
    match_hints: list[str] | None = None
    source: dict | None = None
    status: Literal["active", "deprecated"] | None = None
    lock_version: int = Field(ge=1)


class RelationCreate(BaseModel):
    source_objective_id: str
    target_objective_id: str
    relation_type: Literal[
        "prerequisite_of",
        "equivalent_to",
        "supersedes",
        "split_from",
        "merged_into",
    ]
    is_required: bool = True
    metadata: dict | None = None

    @model_validator(mode="after")
    def no_self_relation(self):
        if self.source_objective_id == self.target_objective_id:
            raise ValueError("目标不能关联自身")
        return self


class MappingCreate(BaseModel):
    objective_id: str
    namespace: str = Field(min_length=1, max_length=64)
    external_id: str = Field(min_length=1, max_length=128)
    metadata: dict | None = None


class ExemplarObjectiveInput(BaseModel):
    objective_id: str
    role: Literal["primary", "supporting", "distractor"]


class ExemplarCreate(BaseModel):
    logical_id: str | None = None
    exemplar_type: Literal["prototype", "boundary", "counterexample"]
    source_type: Literal["textbook", "workbook", "teacher", "feedback"]
    source: dict
    question_text: str = Field(min_length=1, max_length=20_000)
    options: list[str] | None = None
    answer: dict | list | str | None = None
    solution_text: str | None = Field(default=None, max_length=20_000)
    task_signature: dict
    media: list[dict] | None = None
    display_level: Literal["reference", "excerpt", "full"] = "reference"
    objectives: list[ExemplarObjectiveInput] = Field(min_length=1)


class ReviewDecision(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class ClientAppCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    allowed_package_ids: list[str] | None = None
    allowed_media_hosts: list[str] | None = None
    rate_limit_per_minute: int = Field(default=60, ge=1, le=100_000)


class ImportCreate(BaseModel):
    format: Literal["json", "csv"]
    content: str = Field(min_length=1, max_length=10_000_000)


class GoldTestCreate(BaseModel):
    package_id: str
    question: dict
    scope_context: dict | None = None
    expected: dict


class FeedbackReviewCreate(BaseModel):
    decision: Literal["accepted", "rejected", "duplicate"]
    action_type: Literal["record_only", "exemplar_candidate", "knowledge_gap"]
    review_note: str = Field(min_length=1, max_length=2000)
