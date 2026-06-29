from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class LearningOverview(BaseModel):
    suggestions: int
    pending: int
    approved: int
    published: int
    knowledge_items: Annotated[int, Field(alias="knowledgeItems")]
    active_experiments: Annotated[int, Field(alias="activeExperiments")]

    model_config = ConfigDict(populate_by_name=True)


class LearningSuggestionCreate(BaseModel):
    source_type: Annotated[str, Field(alias="sourceType")] = "manual"
    source_record_id: Annotated[str | None, Field(alias="sourceRecordId")] = None
    target_type: Annotated[str, Field(alias="targetType")] = "外呼话术"
    title: str = Field(min_length=1, max_length=160)
    summary: str = ""
    proposed_content: Annotated[str, Field(alias="proposedContent")] = ""
    evidence_text: Annotated[str, Field(alias="evidenceText")] = ""
    status: str = "待审核"
    impact_score: Annotated[int, Field(alias="impactScore", ge=0, le=100)] = 60

    model_config = ConfigDict(populate_by_name=True)


class LearningSuggestionUpdate(BaseModel):
    status: str | None = None
    reviewer: str | None = None
    review_note: Annotated[str | None, Field(alias="reviewNote")] = None
    rollback_point: Annotated[str | None, Field(alias="rollbackPoint")] = None

    model_config = ConfigDict(populate_by_name=True)


class LearningSuggestionRead(LearningSuggestionCreate):
    id: str
    reviewer: str | None
    review_note: Annotated[str | None, Field(alias="reviewNote")]
    rollback_point: Annotated[str | None, Field(alias="rollbackPoint")]
    created_at: Annotated[datetime, Field(alias="createdAt")]
    reviewed_at: Annotated[datetime | None, Field(alias="reviewedAt")]
    published_at: Annotated[datetime | None, Field(alias="publishedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class KnowledgeBaseItemRead(BaseModel):
    id: str
    title: str
    category: str
    content: str
    status: str
    version: str
    source_suggestion_id: Annotated[str | None, Field(alias="sourceSuggestionId")]
    created_at: Annotated[datetime, Field(alias="createdAt")]
    updated_at: Annotated[datetime, Field(alias="updatedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LearningExperimentRead(BaseModel):
    id: str
    name: str
    target_type: Annotated[str, Field(alias="targetType")]
    status: str
    hypothesis: str
    variant: str
    sample_size: Annotated[int, Field(alias="sampleSize")]
    success_metric: Annotated[str, Field(alias="successMetric")]
    result_summary: Annotated[str, Field(alias="resultSummary")]
    started_at: Annotated[datetime | None, Field(alias="startedAt")]
    ended_at: Annotated[datetime | None, Field(alias="endedAt")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
