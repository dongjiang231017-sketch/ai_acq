from datetime import datetime
from typing import Annotated, Any

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel as BaseModel


class CommentInterceptSourceCreate(BaseModel):
    platform: str = Field(min_length=1, max_length=40)
    source_type: Annotated[str, Field(alias="sourceType", max_length=40)] = "视频链接"
    name: str = Field(min_length=1, max_length=160)
    keyword: str = ""
    video_url: Annotated[str, Field(alias="videoUrl")] = ""
    video_title: Annotated[str, Field(alias="videoTitle", max_length=240)] = ""
    owner_account_id: Annotated[str | None, Field(alias="ownerAccountId")] = None
    sync_frequency_minutes: Annotated[int, Field(alias="syncFrequencyMinutes", ge=5, le=10080)] = 120
    keyword_rules: Annotated[str, Field(alias="keywordRules")] = "合作,价格,报名,入驻,求资料,想了解,加我"
    auto_reply_enabled: Annotated[bool, Field(alias="autoReplyEnabled")] = False
    human_confirm_required: Annotated[bool, Field(alias="humanConfirmRequired")] = True

    model_config = ConfigDict(populate_by_name=True)


class CommentInterceptSourceRead(CommentInterceptSourceCreate):
    id: str
    sync_status: Annotated[str, Field(alias="syncStatus")]
    last_sync_at: Annotated[datetime | None, Field(alias="lastSyncAt")]
    last_error: Annotated[str | None, Field(alias="lastError")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SocialCommentRead(BaseModel):
    id: str
    source_id: Annotated[str, Field(alias="sourceId")]
    platform: str
    external_comment_id: Annotated[str, Field(alias="externalCommentId")]
    video_url: Annotated[str, Field(alias="videoUrl")]
    author_name: Annotated[str, Field(alias="authorName")]
    author_profile_url: Annotated[str, Field(alias="authorProfileUrl")]
    content: str
    city: str
    category: str
    like_count: Annotated[int, Field(alias="likeCount")]
    reply_count: Annotated[int, Field(alias="replyCount")]
    intent_score: Annotated[int, Field(alias="intentScore")]
    intent_level: Annotated[str, Field(alias="intentLevel")]
    status: str
    risk_status: Annotated[str, Field(alias="riskStatus")]
    commented_at: Annotated[datetime | None, Field(alias="commentedAt")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CommentSyncResult(BaseModel):
    source_id: Annotated[str, Field(alias="sourceId")]
    imported: int
    skipped: int
    total_comments: Annotated[int, Field(alias="totalComments")]
    message: str

    model_config = ConfigDict(populate_by_name=True)


class BrowserCapturedComment(BaseModel):
    external_comment_id: Annotated[str | None, Field(alias="externalCommentId", max_length=120)] = None
    author_name: Annotated[str, Field(alias="authorName", min_length=1, max_length=120)]
    author_profile_url: Annotated[str, Field(alias="authorProfileUrl")] = ""
    content: str = Field(min_length=1, max_length=1200)
    video_url: Annotated[str, Field(alias="videoUrl")] = ""
    city: str = "待识别"
    category: str = "待识别"
    like_count: Annotated[int, Field(alias="likeCount", ge=0)] = 0
    reply_count: Annotated[int, Field(alias="replyCount", ge=0)] = 0
    commented_at: Annotated[datetime | None, Field(alias="commentedAt")] = None
    raw_payload: Annotated[dict[str, Any] | None, Field(alias="rawPayload")] = None

    model_config = ConfigDict(populate_by_name=True)


class BrowserCommentCaptureRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=40)
    page_url: Annotated[str, Field(alias="pageUrl")] = ""
    page_title: Annotated[str, Field(alias="pageTitle", max_length=240)] = ""
    comments: list[BrowserCapturedComment] = Field(default_factory=list, max_length=200)

    model_config = ConfigDict(populate_by_name=True)


class BrowserDmAction(BaseModel):
    author_name: Annotated[str, Field(alias="authorName", min_length=1, max_length=120)]
    profile_url: Annotated[str, Field(alias="profileUrl")] = ""
    status: str = Field(min_length=1, max_length=60)
    sent: bool = False
    send_clicked: Annotated[bool, Field(alias="sendClicked")] = False
    sent_confirmed: Annotated[bool, Field(alias="sentConfirmed")] = False
    receipt_status: Annotated[str, Field(alias="receiptStatus", max_length=60)] = ""
    receipt_message: Annotated[str, Field(alias="receiptMessage", max_length=500)] = ""
    outgoing_content: Annotated[str, Field(alias="outgoingContent")] = ""
    message: str = Field(default="", max_length=500)
    url: str = ""
    raw_payload: Annotated[dict[str, Any] | None, Field(alias="rawPayload")] = None

    model_config = ConfigDict(populate_by_name=True)


class BrowserDmActionRecordRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=40)
    account_id: Annotated[str | None, Field(alias="accountId")] = None
    message_content: Annotated[str, Field(alias="messageContent")] = ""
    actions: list[BrowserDmAction] = Field(default_factory=list, max_length=120)

    model_config = ConfigDict(populate_by_name=True)


class BrowserDmActionRecordResult(BaseModel):
    source_id: Annotated[str, Field(alias="sourceId")]
    task_id: Annotated[str | None, Field(alias="taskId")]
    recorded: int
    sent: int
    drafts: int
    failed: int
    lead_ids: Annotated[list[str], Field(alias="leadIds")]
    conversation_ids: Annotated[list[str], Field(alias="conversationIds")]
    message: str

    model_config = ConfigDict(populate_by_name=True)


class CommentAutomationQueueItem(BaseModel):
    source_id: Annotated[str, Field(alias="sourceId")]
    source_name: Annotated[str, Field(alias="sourceName")]
    platform: str
    source_type: Annotated[str, Field(alias="sourceType")]
    keyword: str
    video_url: Annotated[str, Field(alias="videoUrl")]
    sync_status: Annotated[str, Field(alias="syncStatus")]
    last_sync_at: Annotated[datetime | None, Field(alias="lastSyncAt")]
    next_run_at: Annotated[datetime | None, Field(alias="nextRunAt")]
    due: bool
    status: str
    blocked_reason: Annotated[str, Field(alias="blockedReason")]
    next_account_id: Annotated[str | None, Field(alias="nextAccountId")]
    next_account_name: Annotated[str | None, Field(alias="nextAccountName")]
    eligible_account_count: Annotated[int, Field(alias="eligibleAccountCount")]
    remaining_quota: Annotated[int, Field(alias="remainingQuota")]
    risk_status: Annotated[str, Field(alias="riskStatus")]
    selector_profile: Annotated[str, Field(alias="selectorProfile")]
    live_send_supported: Annotated[bool, Field(alias="liveSendSupported")]

    model_config = ConfigDict(populate_by_name=True)


class CommentAutomationQueueOverview(BaseModel):
    items: list[CommentAutomationQueueItem]
    due_count: Annotated[int, Field(alias="dueCount")]
    ready_count: Annotated[int, Field(alias="readyCount")]
    paused_count: Annotated[int, Field(alias="pausedCount")]
    blocked_count: Annotated[int, Field(alias="blockedCount")]
    message: str

    model_config = ConfigDict(populate_by_name=True)


class CommentAutomationRiskReport(BaseModel):
    platform: str = ""
    account_id: Annotated[str | None, Field(alias="accountId")] = None
    status: str = Field(min_length=1, max_length=60)
    reason: str = Field(default="", max_length=500)
    step: str = Field(default="", max_length=80)
    url: str = ""
    raw_payload: Annotated[dict[str, Any] | None, Field(alias="rawPayload")] = None

    model_config = ConfigDict(populate_by_name=True)


class CommentAutomationRiskResult(BaseModel):
    source_id: Annotated[str, Field(alias="sourceId")]
    account_id: Annotated[str | None, Field(alias="accountId")]
    paused: bool
    source_status: Annotated[str, Field(alias="sourceStatus")]
    account_status: Annotated[str | None, Field(alias="accountStatus")]
    risk_status: Annotated[str | None, Field(alias="riskStatus")]
    message: str

    model_config = ConfigDict(populate_by_name=True)


class CommentConvertRequest(BaseModel):
    comment_ids: Annotated[list[str], Field(alias="commentIds", min_length=1)]
    city: str = "待识别"
    category: str = "待识别"
    status: str = "待私信"

    model_config = ConfigDict(populate_by_name=True)


class CommentConvertResult(BaseModel):
    converted: int
    skipped: int
    lead_ids: Annotated[list[str], Field(alias="leadIds")]
    message: str

    model_config = ConfigDict(populate_by_name=True)


class CommentInterceptOverview(BaseModel):
    sources: int
    comments: int
    high_intent_comments: Annotated[int, Field(alias="highIntentComments")]
    converted_leads: Annotated[int, Field(alias="convertedLeads")]

    model_config = ConfigDict(populate_by_name=True)
