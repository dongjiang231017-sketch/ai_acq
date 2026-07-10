from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class OutreachTask(Base):
    __tablename__ = "outreach_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(160), index=True)
    channel: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="待启动")
    target_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    connected_count: Mapped[int] = mapped_column(Integer, default=0)
    intent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    concurrency: Mapped[int] = mapped_column(Integer, default=1)
    script_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dm_account_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dm_template_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_lead_ids: Mapped[str] = mapped_column(Text, default="")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return self.name


class CallScript(Base):
    __tablename__ = "call_scripts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(120), index=True)
    opening: Mapped[str] = mapped_column(Text)
    qualification: Mapped[str] = mapped_column(Text)
    objection: Mapped[str] = mapped_column(Text)
    closing: Mapped[str] = mapped_column(Text)
    entries: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    audio_mapping: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return self.name


class CallRecord(Base):
    __tablename__ = "call_records"
    __table_args__ = (
        Index(
            "uq_call_records_gateway_call_id",
            "gateway_call_id",
            unique=True,
            postgresql_where=text("gateway_call_id IS NOT NULL"),
            sqlite_where=text("gateway_call_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    task_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("outreach_tasks.id"), nullable=True, index=True)
    lead_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("merchant_leads.id"), nullable=True, index=True)
    merchant_name: Mapped[str] = mapped_column(String(120), index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_seat: Mapped[str] = mapped_column(String(40), default="AI-01")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    intent_level: Mapped[str] = mapped_column(String(20), default="C", index=True)
    current_node: Mapped[str] = mapped_column(String(80), default="开场白")
    outcome: Mapped[str] = mapped_column(String(40), default="未接通", index=True)
    transcript: Mapped[str] = mapped_column(Text, default="")
    gateway_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gateway_status: Mapped[str] = mapped_column(String(40), default="completed", index=True)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    need_handoff: Mapped[bool] = mapped_column(Boolean, default=False)
    recall_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"{self.merchant_name} {self.outcome}"


class RecallRule(Base):
    __tablename__ = "recall_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(120), index=True)
    no_answer_interval_minutes: Mapped[int] = mapped_column(Integer, default=240)
    busy_interval_minutes: Mapped[int] = mapped_column(Integer, default=120)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    quiet_start: Mapped[str] = mapped_column(String(8), default="21:00")
    quiet_end: Mapped[str] = mapped_column(String(8), default="09:00")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return self.name


class DirectMessageAccount(Base):
    __tablename__ = "dm_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    account_name: Mapped[str] = mapped_column(String(120), index=True)
    login_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="待登录", index=True)
    browser_profile_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    browser_profile_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_status: Mapped[str | None] = mapped_column(String(40), default="未登录", nullable=True, index=True)
    risk_status: Mapped[str | None] = mapped_column(String(40), default="正常", nullable=True, index=True)
    daily_limit: Mapped[int] = mapped_column(Integer, default=200)
    sent_today: Mapped[int] = mapped_column(Integer, default=0)
    min_send_interval_seconds: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"{self.platform} {self.account_name}"


class DirectMessagePlatformConfig(Base):
    __tablename__ = "dm_platform_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    home_url: Mapped[str] = mapped_column(String(240), default="")
    inbox_url: Mapped[str] = mapped_column(String(240), default="")
    merchant_search_url: Mapped[str] = mapped_column(String(240), default="")
    login_check_selector: Mapped[str] = mapped_column(String(240), default="")
    risk_check_selector: Mapped[str] = mapped_column(String(240), default="")
    merchant_link_selector: Mapped[str] = mapped_column(String(240), default="")
    message_button_selector: Mapped[str] = mapped_column(String(240), default="")
    input_selector: Mapped[str] = mapped_column(String(240), default="")
    send_button_selector: Mapped[str] = mapped_column(String(240), default="")
    sent_success_selector: Mapped[str] = mapped_column(String(240), default="")
    unread_selector: Mapped[str] = mapped_column(String(240), default="")
    conversation_item_selector: Mapped[str] = mapped_column(String(240), default="")
    conversation_title_selector: Mapped[str] = mapped_column(String(240), default="")
    message_text_selector: Mapped[str] = mapped_column(String(240), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return self.platform


class DirectMessageTemplate(Base):
    __tablename__ = "dm_templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(120), index=True)
    platform: Mapped[str] = mapped_column(String(40), default="通用", index=True)
    content: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return self.name


class DirectMessageConversation(Base):
    __tablename__ = "dm_conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    task_id: Mapped[str] = mapped_column(String(32), ForeignKey("outreach_tasks.id"), index=True)
    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("merchant_leads.id"), index=True)
    account_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("dm_accounts.id"), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    merchant_name: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), default="已发送", index=True)
    intent_level: Mapped[str] = mapped_column(String(20), default="C", index=True)
    last_message: Mapped[str] = mapped_column(Text, default="")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    need_handoff: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"{self.platform} {self.merchant_name}"


class DirectMessage(Base):
    __tablename__ = "dm_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    conversation_id: Mapped[str] = mapped_column(String(32), ForeignKey("dm_conversations.id"), index=True)
    direction: Mapped[str] = mapped_column(String(20), index=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="sent", index=True)
    external_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"{self.direction} {self.status}"


class CommentInterceptSource(Base):
    __tablename__ = "comment_intercept_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="视频链接", index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    keyword: Mapped[str] = mapped_column(String(160), default="")
    video_url: Mapped[str] = mapped_column(Text, default="")
    video_title: Mapped[str] = mapped_column(String(240), default="")
    owner_account_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("dm_accounts.id"), nullable=True, index=True)
    sync_status: Mapped[str] = mapped_column(String(40), default="待同步", index=True)
    sync_frequency_minutes: Mapped[int] = mapped_column(Integer, default=120)
    keyword_rules: Mapped[str] = mapped_column(Text, default="合作,价格,报名,入驻,求资料,想了解,加我")
    auto_reply_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    human_confirm_required: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"{self.platform} {self.name}"


class SocialComment(Base):
    __tablename__ = "social_comments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    source_id: Mapped[str] = mapped_column(String(32), ForeignKey("comment_intercept_sources.id"), index=True)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    external_comment_id: Mapped[str] = mapped_column(String(120), index=True)
    video_url: Mapped[str] = mapped_column(Text, default="")
    author_name: Mapped[str] = mapped_column(String(120), index=True)
    author_profile_url: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(40), default="待识别", index=True)
    category: Mapped[str] = mapped_column(String(80), default="待识别", index=True)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    intent_score: Mapped[int] = mapped_column(Integer, default=60, index=True)
    intent_level: Mapped[str] = mapped_column(String(20), default="C", index=True)
    status: Mapped[str] = mapped_column(String(40), default="待转线索", index=True)
    risk_status: Mapped[str] = mapped_column(String(40), default="正常", index=True)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    commented_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"{self.author_name}: {self.content[:20]}"


class CommentLeadConversion(Base):
    __tablename__ = "comment_lead_conversions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    comment_id: Mapped[str] = mapped_column(String(32), ForeignKey("social_comments.id"), index=True)
    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("merchant_leads.id"), index=True)
    action: Mapped[str] = mapped_column(String(40), default="转线索", index=True)
    status: Mapped[str] = mapped_column(String(40), default="已完成", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"{self.action} {self.status}"
