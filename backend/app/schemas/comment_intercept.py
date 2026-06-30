from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field


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
