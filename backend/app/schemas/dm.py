from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class DmAccountCreate(BaseModel):
    platform: str = Field(min_length=1, max_length=40)
    account_name: Annotated[str, Field(alias="accountName", min_length=1, max_length=120)]
    login_label: Annotated[str | None, Field(alias="loginLabel")] = None
    status: str = "待登录"
    daily_limit: Annotated[int, Field(alias="dailyLimit", ge=1, le=5000)] = 200

    model_config = ConfigDict(populate_by_name=True)


class DmAccountRead(DmAccountCreate):
    id: str
    sent_today: Annotated[int, Field(alias="sentToday")]
    last_sync_at: Annotated[datetime | None, Field(alias="lastSyncAt")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DmTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    platform: str = "通用"
    content: str = Field(min_length=1)
    is_active: Annotated[bool, Field(alias="isActive")] = True

    model_config = ConfigDict(populate_by_name=True)


class DmTemplateRead(DmTemplateCreate):
    id: str
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DmTaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    lead_ids: Annotated[list[str], Field(alias="leadIds", min_length=1)]
    account_id: Annotated[str | None, Field(alias="accountId")] = None
    template_id: Annotated[str | None, Field(alias="templateId")] = None
    scheduled_at: Annotated[datetime | None, Field(alias="scheduledAt")] = None

    model_config = ConfigDict(populate_by_name=True)


class DmConversationRead(BaseModel):
    id: str
    task_id: Annotated[str, Field(alias="taskId")]
    lead_id: Annotated[str, Field(alias="leadId")]
    account_id: Annotated[str | None, Field(alias="accountId")]
    platform: str
    merchant_name: Annotated[str, Field(alias="merchantName")]
    status: str
    intent_level: Annotated[str, Field(alias="intentLevel")]
    last_message: Annotated[str, Field(alias="lastMessage")]
    last_message_at: Annotated[datetime | None, Field(alias="lastMessageAt")]
    need_handoff: Annotated[bool, Field(alias="needHandoff")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DmMessageRead(BaseModel):
    id: str
    conversation_id: Annotated[str, Field(alias="conversationId")]
    direction: str
    content: str
    status: str
    external_message_id: Annotated[str | None, Field(alias="externalMessageId")]
    raw_payload: Annotated[str | None, Field(alias="rawPayload")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DmOverview(BaseModel):
    accounts: int
    active_accounts: Annotated[int, Field(alias="activeAccounts")]
    today_sent: Annotated[int, Field(alias="todaySent")]
    replies: int
    needs_handoff: Annotated[int, Field(alias="needsHandoff")]
    intent_count: Annotated[int, Field(alias="intentCount")]

    model_config = ConfigDict(populate_by_name=True)


class DmConfigRead(BaseModel):
    gateway_mode: Annotated[str, Field(alias="gatewayMode")]
    queue_enabled: Annotated[bool, Field(alias="queueEnabled")]
    queue_name: Annotated[str, Field(alias="queueName")]
    redis_url_configured: Annotated[bool, Field(alias="redisUrlConfigured")]

    model_config = ConfigDict(populate_by_name=True)
