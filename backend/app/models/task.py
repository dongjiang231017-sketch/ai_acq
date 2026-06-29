from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return self.name


class CallRecord(Base):
    __tablename__ = "call_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    task_id: Mapped[str] = mapped_column(String(32), ForeignKey("outreach_tasks.id"), index=True)
    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("merchant_leads.id"), index=True)
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
