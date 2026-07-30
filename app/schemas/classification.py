from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CurriculumContext(BaseModel):
    active_package_id: str
    active_package_version: str = "latest_stable"
    active_node_ids: list[str] = Field(default_factory=list)
    learned_through_node_id: str | None = None
    previous_package_ids: list[str] = Field(default_factory=list)
    later_package_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def distinct_packages(self):
        package_ids = [
            self.active_package_id,
            *self.previous_package_ids,
            *self.later_package_ids,
        ]
        if len(package_ids) != len(set(package_ids)):
            raise ValueError("课程上下文中的知识包不能重复")
        return self


class QuestionInput(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    options: list[str] = Field(default_factory=list, max_length=100)
    answer: str | dict | list | None = None
    analysis: str | None = Field(default=None, max_length=20_000)
    structured_content: dict | None = None
    media_urls: list[str] = Field(default_factory=list, max_length=10)


class ClassificationCreate(BaseModel):
    client_request_id: str = Field(min_length=1, max_length=128)
    source_question_id: str | None = Field(default=None, max_length=128)
    curriculum_context: CurriculumContext
    question: QuestionInput


class ClassifierDecision(BaseModel):
    primary_objective_id: str | None
    secondary_objective_ids: list[str] = Field(default_factory=list, max_length=4)
    match_type: Literal["direct", "variant", "composite", "extension", "unmatched"]
    evidence_exemplar_ids: list[str] = Field(default_factory=list, max_length=5)
    task_signature: dict = Field(default_factory=dict)
    reason_summary: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unmatched_has_no_objectives(self):
        if self.match_type == "unmatched" and (
            self.primary_objective_id
            or self.secondary_objective_ids
            or self.evidence_exemplar_ids
        ):
            raise ValueError("unmatched 不能包含目标或正向证据")
        if self.match_type != "unmatched" and not self.primary_objective_id:
            raise ValueError("匹配结果必须包含主要目标")
        return self


class FeedbackCreate(BaseModel):
    feedback_request_id: str | None = Field(default=None, max_length=128)
    confirmed: bool
    corrected_primary_objective_id: str | None = None
    corrected_secondary_objective_ids: list[str] = Field(default_factory=list)
    corrected_match_type: (
        Literal["direct", "variant", "composite", "extension", "unmatched"] | None
    ) = None
    corrected_scope_status: (
        Literal[
            "in_scope",
            "previous_scope",
            "later_scope",
            "cross_scope",
            "unknown_scope",
        ]
        | None
    ) = None
    reason: str | None = Field(default=None, max_length=2000)
