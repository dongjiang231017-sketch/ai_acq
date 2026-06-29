from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class IntentOverview(BaseModel):
    total_customers: Annotated[int, Field(alias="totalCustomers")]
    high_intent: Annotated[int, Field(alias="highIntent")]
    needs_handoff: Annotated[int, Field(alias="needsHandoff")]
    pending_work_orders: Annotated[int, Field(alias="pendingWorkOrders")]
    dnc_blocked: Annotated[int, Field(alias="dncBlocked")]

    model_config = ConfigDict(populate_by_name=True)


class IntentCustomerRead(BaseModel):
    id: str
    lead_id: Annotated[str | None, Field(alias="leadId")]
    merchant_name: Annotated[str, Field(alias="merchantName")]
    platform: str
    city: str
    category: str
    contact_name: Annotated[str | None, Field(alias="contactName")]
    phone: str | None
    intent_level: Annotated[str, Field(alias="intentLevel")]
    intent_score: Annotated[int, Field(alias="intentScore")]
    source_channels: Annotated[str, Field(alias="sourceChannels")]
    latest_signal: Annotated[str, Field(alias="latestSignal")]
    evidence_summary: Annotated[str, Field(alias="evidenceSummary")]
    owner_name: Annotated[str, Field(alias="ownerName")]
    follow_status: Annotated[str, Field(alias="followStatus")]
    next_follow_at: Annotated[datetime | None, Field(alias="nextFollowAt")]
    need_handoff: Annotated[bool, Field(alias="needHandoff")]
    dnc_status: Annotated[bool, Field(alias="dncStatus")]
    created_at: Annotated[datetime, Field(alias="createdAt")]
    updated_at: Annotated[datetime, Field(alias="updatedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class IntentCustomerUpdate(BaseModel):
    owner_name: Annotated[str | None, Field(alias="ownerName")] = None
    follow_status: Annotated[str | None, Field(alias="followStatus")] = None
    intent_level: Annotated[str | None, Field(alias="intentLevel")] = None
    intent_score: Annotated[int | None, Field(alias="intentScore", ge=0, le=100)] = None
    latest_signal: Annotated[str | None, Field(alias="latestSignal")] = None
    next_follow_at: Annotated[datetime | None, Field(alias="nextFollowAt")] = None
    need_handoff: Annotated[bool | None, Field(alias="needHandoff")] = None
    dnc_status: Annotated[bool | None, Field(alias="dncStatus")] = None

    model_config = ConfigDict(populate_by_name=True)


class IntentEventCreate(BaseModel):
    source_type: Annotated[str, Field(alias="sourceType")] = "manual"
    source_record_id: Annotated[str | None, Field(alias="sourceRecordId")] = None
    channel: str = "manual"
    intent_level: Annotated[str, Field(alias="intentLevel")] = "C"
    summary: str = ""
    evidence_text: Annotated[str, Field(alias="evidenceText")] = ""
    need_handoff: Annotated[bool, Field(alias="needHandoff")] = False

    model_config = ConfigDict(populate_by_name=True)


class IntentEventRead(IntentEventCreate):
    id: str
    customer_id: Annotated[str, Field(alias="customerId")]
    lead_id: Annotated[str | None, Field(alias="leadId")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class FollowUpWorkOrderRead(BaseModel):
    id: str
    customer_id: Annotated[str, Field(alias="customerId")]
    title: str
    owner_name: Annotated[str, Field(alias="ownerName")]
    status: str
    priority: str
    sla_due_at: Annotated[datetime | None, Field(alias="slaDueAt")]
    last_note: Annotated[str, Field(alias="lastNote")]
    closed_reason: Annotated[str | None, Field(alias="closedReason")]
    created_at: Annotated[datetime, Field(alias="createdAt")]
    updated_at: Annotated[datetime, Field(alias="updatedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
