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
