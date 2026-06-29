from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


TaskChannel = Literal["collector", "call", "dm"]


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    channel: TaskChannel
    target_count: Annotated[int, Field(ge=0, alias="targetCount")] = 0
    concurrency: Annotated[int, Field(ge=1, le=50)] = 1
    script_id: Annotated[str | None, Field(alias="scriptId")] = None
    scheduled_at: Annotated[datetime | None, Field(alias="scheduledAt")] = None


class TaskRead(BaseModel):
    id: str
    name: str
    channel: TaskChannel
    status: str
    target_count: Annotated[int, Field(alias="targetCount")]
    completed_count: Annotated[int, Field(alias="completedCount")]
    connected_count: Annotated[int, Field(alias="connectedCount")]
    intent_count: Annotated[int, Field(alias="intentCount")]
    failed_count: Annotated[int, Field(alias="failedCount")]
    concurrency: int
    script_id: Annotated[str | None, Field(alias="scriptId")]
    scheduled_at: Annotated[datetime | None, Field(alias="scheduledAt")]
    started_at: Annotated[datetime | None, Field(alias="startedAt")]
    finished_at: Annotated[datetime | None, Field(alias="finishedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OutboundTaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    lead_ids: Annotated[list[str], Field(alias="leadIds", min_length=1)]
    concurrency: Annotated[int, Field(ge=1, le=50)] = 5
    script_id: Annotated[str | None, Field(alias="scriptId")] = None
    scheduled_at: Annotated[datetime | None, Field(alias="scheduledAt")] = None


class CallScriptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    opening: str = Field(min_length=1)
    qualification: str = Field(min_length=1)
    objection: str = Field(min_length=1)
    closing: str = Field(min_length=1)
    is_active: Annotated[bool, Field(alias="isActive")] = True


class CallScriptRead(CallScriptCreate):
    id: str
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CallRecordRead(BaseModel):
    id: str
    task_id: Annotated[str, Field(alias="taskId")]
    lead_id: Annotated[str, Field(alias="leadId")]
    merchant_name: Annotated[str, Field(alias="merchantName")]
    phone: str | None
    ai_seat: Annotated[str, Field(alias="aiSeat")]
    duration_seconds: Annotated[int, Field(alias="durationSeconds")]
    intent_level: Annotated[str, Field(alias="intentLevel")]
    current_node: Annotated[str, Field(alias="currentNode")]
    outcome: str
    transcript: str
    need_handoff: Annotated[bool, Field(alias="needHandoff")]
    recall_at: Annotated[datetime | None, Field(alias="recallAt")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RecallRuleRead(BaseModel):
    id: str
    name: str
    no_answer_interval_minutes: Annotated[int, Field(alias="noAnswerIntervalMinutes")]
    busy_interval_minutes: Annotated[int, Field(alias="busyIntervalMinutes")]
    max_attempts: Annotated[int, Field(alias="maxAttempts")]
    quiet_start: Annotated[str, Field(alias="quietStart")]
    quiet_end: Annotated[str, Field(alias="quietEnd")]
    enabled: bool

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OutboundOverview(BaseModel):
    ai_seats: Annotated[int, Field(alias="aiSeats")]
    active_calls: Annotated[int, Field(alias="activeCalls")]
    needs_handoff: Annotated[int, Field(alias="needsHandoff")]
    silent_alerts: Annotated[int, Field(alias="silentAlerts")]
    today_calls: Annotated[int, Field(alias="todayCalls")]
    connected_rate: Annotated[int, Field(alias="connectedRate")]
    intent_count: Annotated[int, Field(alias="intentCount")]
