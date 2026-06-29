from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class DmAccountCreate(BaseModel):
    platform: str = Field(min_length=1, max_length=40)
    account_name: Annotated[str, Field(alias="accountName", min_length=1, max_length=120)]
    login_label: Annotated[str | None, Field(alias="loginLabel")] = None
    status: str = "待登录"
    browser_profile_key: Annotated[str | None, Field(alias="browserProfileKey")] = None
    browser_profile_path: Annotated[str | None, Field(alias="browserProfilePath")] = None
    session_status: Annotated[str | None, Field(alias="sessionStatus")] = "未登录"
    risk_status: Annotated[str | None, Field(alias="riskStatus")] = "正常"
    daily_limit: Annotated[int, Field(alias="dailyLimit", ge=1, le=5000)] = 200
    min_send_interval_seconds: Annotated[int, Field(alias="minSendIntervalSeconds", ge=0, le=3600)] = 45
    cooldown_until: Annotated[datetime | None, Field(alias="cooldownUntil")] = None

    model_config = ConfigDict(populate_by_name=True)


class DmAccountRead(DmAccountCreate):
    id: str
    sent_today: Annotated[int, Field(alias="sentToday")]
    last_sent_at: Annotated[datetime | None, Field(alias="lastSentAt")]
    last_sync_at: Annotated[datetime | None, Field(alias="lastSyncAt")]
    last_login_check_at: Annotated[datetime | None, Field(alias="lastLoginCheckAt")]
    last_error: Annotated[str | None, Field(alias="lastError")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DmAccountLoginSession(BaseModel):
    account_id: Annotated[str, Field(alias="accountId")]
    platform: str
    account_name: Annotated[str, Field(alias="accountName")]
    login_url: Annotated[str, Field(alias="loginUrl")]
    profile_key: Annotated[str, Field(alias="profileKey")]
    profile_path: Annotated[str, Field(alias="profilePath")]
    session_status: Annotated[str | None, Field(alias="sessionStatus")]
    risk_status: Annotated[str | None, Field(alias="riskStatus")]
    embedded_mode: Annotated[str, Field(alias="embeddedMode")]
    isolated: bool = True

    model_config = ConfigDict(populate_by_name=True)


class DmAccountLoginWindow(DmAccountLoginSession):
    launched: bool
    launch_message: Annotated[str, Field(alias="launchMessage")]

    model_config = ConfigDict(populate_by_name=True)


class DmAccountInlineLogin(BaseModel):
    phone_number: Annotated[str, Field(alias="phoneNumber", min_length=5, max_length=30)]
    verification_code: Annotated[str, Field(alias="verificationCode", min_length=4, max_length=12)]
    agreement_accepted: Annotated[bool, Field(alias="agreementAccepted")] = True

    model_config = ConfigDict(populate_by_name=True)


class DmAccountUpdate(BaseModel):
    account_name: Annotated[str | None, Field(alias="accountName", min_length=1, max_length=120)] = None
    login_label: Annotated[str | None, Field(alias="loginLabel")] = None
    status: str | None = None
    browser_profile_key: Annotated[str | None, Field(alias="browserProfileKey")] = None
    browser_profile_path: Annotated[str | None, Field(alias="browserProfilePath")] = None
    session_status: Annotated[str | None, Field(alias="sessionStatus")] = None
    risk_status: Annotated[str | None, Field(alias="riskStatus")] = None
    daily_limit: Annotated[int | None, Field(alias="dailyLimit", ge=1, le=5000)] = None
    min_send_interval_seconds: Annotated[int | None, Field(alias="minSendIntervalSeconds", ge=0, le=3600)] = None
    cooldown_until: Annotated[datetime | None, Field(alias="cooldownUntil")] = None
    last_error: Annotated[str | None, Field(alias="lastError")] = None

    model_config = ConfigDict(populate_by_name=True)


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


class DmPlatformConfigCreate(BaseModel):
    platform: str = Field(min_length=1, max_length=40)
    home_url: Annotated[str, Field(alias="homeUrl")] = ""
    inbox_url: Annotated[str, Field(alias="inboxUrl")] = ""
    merchant_search_url: Annotated[str, Field(alias="merchantSearchUrl")] = ""
    login_check_selector: Annotated[str, Field(alias="loginCheckSelector")] = ""
    risk_check_selector: Annotated[str, Field(alias="riskCheckSelector")] = ""
    merchant_link_selector: Annotated[str, Field(alias="merchantLinkSelector")] = ""
    message_button_selector: Annotated[str, Field(alias="messageButtonSelector")] = ""
    input_selector: Annotated[str, Field(alias="inputSelector")] = ""
    send_button_selector: Annotated[str, Field(alias="sendButtonSelector")] = ""
    sent_success_selector: Annotated[str, Field(alias="sentSuccessSelector")] = ""
    unread_selector: Annotated[str, Field(alias="unreadSelector")] = ""
    conversation_item_selector: Annotated[str, Field(alias="conversationItemSelector")] = ""
    conversation_title_selector: Annotated[str, Field(alias="conversationTitleSelector")] = ""
    message_text_selector: Annotated[str, Field(alias="messageTextSelector")] = ""
    enabled: bool = True

    model_config = ConfigDict(populate_by_name=True)


class DmPlatformConfigRead(DmPlatformConfigCreate):
    id: str
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DmPlatformConfigUpdate(BaseModel):
    platform: str | None = None
    home_url: Annotated[str | None, Field(alias="homeUrl")] = None
    inbox_url: Annotated[str | None, Field(alias="inboxUrl")] = None
    merchant_search_url: Annotated[str | None, Field(alias="merchantSearchUrl")] = None
    login_check_selector: Annotated[str | None, Field(alias="loginCheckSelector")] = None
    risk_check_selector: Annotated[str | None, Field(alias="riskCheckSelector")] = None
    merchant_link_selector: Annotated[str | None, Field(alias="merchantLinkSelector")] = None
    message_button_selector: Annotated[str | None, Field(alias="messageButtonSelector")] = None
    input_selector: Annotated[str | None, Field(alias="inputSelector")] = None
    send_button_selector: Annotated[str | None, Field(alias="sendButtonSelector")] = None
    sent_success_selector: Annotated[str | None, Field(alias="sentSuccessSelector")] = None
    unread_selector: Annotated[str | None, Field(alias="unreadSelector")] = None
    conversation_item_selector: Annotated[str | None, Field(alias="conversationItemSelector")] = None
    conversation_title_selector: Annotated[str | None, Field(alias="conversationTitleSelector")] = None
    message_text_selector: Annotated[str | None, Field(alias="messageTextSelector")] = None
    enabled: bool | None = None

    model_config = ConfigDict(populate_by_name=True)


class DmSyncResult(BaseModel):
    checked: int
    new_replies: Annotated[int, Field(alias="newReplies")]
    needs_handoff: Annotated[int, Field(alias="needsHandoff")]

    model_config = ConfigDict(populate_by_name=True)


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
    browser_profile_root: Annotated[str, Field(alias="browserProfileRoot")]
    browser_headless: Annotated[bool, Field(alias="browserHeadless")]
    browser_channel: Annotated[str, Field(alias="browserChannel")]
    browser_live_send_enabled: Annotated[bool, Field(alias="browserLiveSendEnabled")]

    model_config = ConfigDict(populate_by_name=True)
