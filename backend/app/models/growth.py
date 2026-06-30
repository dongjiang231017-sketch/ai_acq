from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class IntentCustomer(Base):
    __tablename__ = "intent_customers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    lead_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("merchant_leads.id"), nullable=True, index=True)
    merchant_name: Mapped[str] = mapped_column(String(120), index=True)
    platform: Mapped[str] = mapped_column(String(40), default="未知", index=True)
    city: Mapped[str] = mapped_column(String(40), default="", index=True)
    category: Mapped[str] = mapped_column(String(80), default="", index=True)
    contact_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    intent_level: Mapped[str] = mapped_column(String(20), default="C", index=True)
    intent_score: Mapped[int] = mapped_column(Integer, default=60)
    source_channels: Mapped[str] = mapped_column(String(120), default="线索")
    latest_signal: Mapped[str] = mapped_column(Text, default="")
    evidence_summary: Mapped[str] = mapped_column(Text, default="")
    owner_name: Mapped[str] = mapped_column(String(80), default="待分配", index=True)
    follow_status: Mapped[str] = mapped_column(String(40), default="待分配", index=True)
    next_follow_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    need_handoff: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    dnc_status: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return self.merchant_name


class IntentEvent(Base):
    __tablename__ = "intent_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    customer_id: Mapped[str] = mapped_column(String(32), ForeignKey("intent_customers.id"), index=True)
    lead_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("merchant_leads.id"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    source_record_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    intent_level: Mapped[str] = mapped_column(String(20), default="C", index=True)
    summary: Mapped[str] = mapped_column(String(240), default="")
    evidence_text: Mapped[str] = mapped_column(Text, default="")
    need_handoff: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"{self.channel} {self.intent_level}"


class FollowUpWorkOrder(Base):
    __tablename__ = "follow_up_work_orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    customer_id: Mapped[str] = mapped_column(String(32), ForeignKey("intent_customers.id"), index=True)
    title: Mapped[str] = mapped_column(String(160), index=True)
    owner_name: Mapped[str] = mapped_column(String(80), default="待分配", index=True)
    status: Mapped[str] = mapped_column(String(40), default="待分配", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="P1", index=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_note: Mapped[str] = mapped_column(Text, default="")
    closed_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return self.title


class LearningSuggestion(Base):
    __tablename__ = "learning_suggestions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    source_type: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    source_record_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    target_type: Mapped[str] = mapped_column(String(60), default="外呼话术", index=True)
    title: Mapped[str] = mapped_column(String(160), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    proposed_content: Mapped[str] = mapped_column(Text, default="")
    evidence_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="待审核", index=True)
    reviewer: Mapped[str | None] = mapped_column(String(80), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact_score: Mapped[int] = mapped_column(Integer, default=60)
    rollback_point: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return self.title


class KnowledgeBaseItem(Base):
    __tablename__ = "knowledge_base_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    title: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(80), default="产品资料", index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="草稿", index=True)
    version: Mapped[str] = mapped_column(String(40), default="v1")
    source_suggestion_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("learning_suggestions.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return self.title


class LearningExperiment(Base):
    __tablename__ = "learning_experiments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(160), index=True)
    target_type: Mapped[str] = mapped_column(String(60), default="外呼话术", index=True)
    status: Mapped[str] = mapped_column(String(40), default="计划中", index=True)
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    variant: Mapped[str] = mapped_column(Text, default="")
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    success_metric: Mapped[str] = mapped_column(String(120), default="意向率提升")
    result_summary: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return self.name


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(120), index=True)
    owner_name: Mapped[str] = mapped_column(String(80), default="系统", index=True)
    scenario: Mapped[str] = mapped_column(String(80), default="外呼", index=True)
    status: Mapped[str] = mapped_column(String(40), default="待授权", index=True)
    authorization_status: Mapped[str] = mapped_column(String(40), default="待提交", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    fallback_voice: Mapped[str] = mapped_column(String(120), default="标准AI音色")
    consent_material: Mapped[str] = mapped_column(Text, default="")
    risk_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return self.name


class VoiceTrainingJob(Base):
    __tablename__ = "voice_training_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    profile_id: Mapped[str] = mapped_column(String(32), ForeignKey("voice_profiles.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="排队中", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    engine: Mapped[str] = mapped_column(String(80), default="真实声音克隆服务")
    sample_minutes: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"{self.profile_id} {self.status}"


class VoiceSample(Base):
    __tablename__ = "voice_samples"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    profile_id: Mapped[str] = mapped_column(String(32), ForeignKey("voice_profiles.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(240))
    content_type: Mapped[str] = mapped_column(String(120), default="audio/wav")
    storage_path: Mapped[str] = mapped_column(Text, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    quality_status: Mapped[str] = mapped_column(String(40), default="可用", index=True)
    transcript: Mapped[str] = mapped_column(Text, default="")
    uploaded_by: Mapped[str] = mapped_column(String(80), default="客户")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return self.file_name


class VoiceCloneRecord(Base):
    __tablename__ = "voice_clone_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    profile_id: Mapped[str] = mapped_column(String(32), ForeignKey("voice_profiles.id"), index=True)
    training_job_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("voice_training_jobs.id"), nullable=True, index=True)
    cloned_voice_name: Mapped[str] = mapped_column(String(120), default="")
    engine: Mapped[str] = mapped_column(String(80), default="真实声音克隆服务")
    status: Mapped[str] = mapped_column(String(40), default="排队中", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    sample_minutes: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"{self.cloned_voice_name} {self.status}"


class VoiceUsageRecord(Base):
    __tablename__ = "voice_usage_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    profile_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("voice_profiles.id"), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("outreach_tasks.id"), nullable=True, index=True)
    merchant_name: Mapped[str] = mapped_column(String(120), default="")
    scenario: Mapped[str] = mapped_column(String(80), default="外呼", index=True)
    result: Mapped[str] = mapped_column(String(80), default="模拟使用", index=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return self.result
