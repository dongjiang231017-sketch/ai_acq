from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel as BaseModel


class LeadCollectionTaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = "amap"
    cities: list[str] = Field(min_length=1)
    categories: list[str] = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    target_per_keyword: Annotated[int, Field(ge=1, le=200, alias="targetPerKeyword")] = 60
    remark: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class LeadCollectionTaskRead(BaseModel):
    id: str
    name: str
    provider: str
    cities: list[str]
    categories: list[str]
    keywords: list[str]
    target_per_keyword: Annotated[int, Field(alias="targetPerKeyword")]
    status: str
    last_run_status: Annotated[str | None, Field(alias="lastRunStatus")]
    remark: str | None
    owner_user_id: Annotated[str | None, Field(alias="ownerUserId")]
    created_by_user_id: Annotated[str | None, Field(alias="createdByUserId")]
    created_at: Annotated[datetime, Field(alias="createdAt")]
    updated_at: Annotated[datetime, Field(alias="updatedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LeadCollectionRunRead(BaseModel):
    id: str
    task_id: Annotated[str, Field(alias="taskId")]
    provider: str
    status: str
    requested_count: Annotated[int, Field(alias="requestedCount")]
    fetched_count: Annotated[int, Field(alias="fetchedCount")]
    inserted_count: Annotated[int, Field(alias="insertedCount")]
    duplicate_count: Annotated[int, Field(alias="duplicateCount")]
    failed_count: Annotated[int, Field(alias="failedCount")]
    error_message: Annotated[str | None, Field(alias="errorMessage")]
    started_at: Annotated[datetime, Field(alias="startedAt")]
    finished_at: Annotated[datetime | None, Field(alias="finishedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RawLeadRecordRead(BaseModel):
    id: str
    task_id: Annotated[str, Field(alias="taskId")]
    run_id: Annotated[str, Field(alias="runId")]
    lead_id: Annotated[str | None, Field(alias="leadId")]
    owner_user_id: Annotated[str | None, Field(alias="ownerUserId")]
    provider: str
    source_poi_id: Annotated[str, Field(alias="sourcePoiId")]
    name: str
    city: str | None
    district: str | None
    category: str | None
    phone: str | None
    address: str | None
    source_url: Annotated[str | None, Field(alias="sourceUrl")]
    longitude: str | None
    latitude: str | None
    import_status: Annotated[str, Field(alias="importStatus")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
