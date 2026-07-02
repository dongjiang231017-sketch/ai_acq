from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class LeadProviderConfig(Base):
    __tablename__ = "lead_provider_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    provider: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secret_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qps_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return self.name


class LeadCollectionTask(Base):
    __tablename__ = "lead_collection_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(120), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="amap", index=True)
    cities: Mapped[list[str]] = mapped_column(JSON, default=list)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_per_keyword: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[str] = mapped_column(String(40), default="待采集", index=True)
    last_run_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    runs = relationship("LeadCollectionRun", back_populates="task", cascade="all, delete-orphan")
    raw_records = relationship("RawLeadRecord", back_populates="task", cascade="all, delete-orphan")
    owner_user = relationship("User", foreign_keys=[owner_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self) -> str:
        return self.name


class LeadCollectionRun(Base):
    __tablename__ = "lead_collection_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    task_id: Mapped[str] = mapped_column(ForeignKey("lead_collection_tasks.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="amap", index=True)
    status: Mapped[str] = mapped_column(String(40), default="运行中", index=True)
    requested_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    task = relationship("LeadCollectionTask", back_populates="runs")
    raw_records = relationship("RawLeadRecord", back_populates="run", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"{self.provider} {self.status}"


class RawLeadRecord(Base):
    __tablename__ = "raw_lead_records"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "provider", "source_poi_id", name="uq_raw_lead_records_owner_provider_poi"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    task_id: Mapped[str] = mapped_column(ForeignKey("lead_collection_tasks.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("lead_collection_runs.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("merchant_leads.id", ondelete="SET NULL"), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    source_poi_id: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    city: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    longitude: Mapped[str | None] = mapped_column(String(40), nullable=True)
    latitude: Mapped[str | None] = mapped_column(String(40), nullable=True)
    import_status: Mapped[str] = mapped_column(String(40), default="已入库", index=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    task = relationship("LeadCollectionTask", back_populates="raw_records")
    run = relationship("LeadCollectionRun", back_populates="raw_records")
    lead = relationship("MerchantLead")
    owner_user = relationship("User")

    def __repr__(self) -> str:
        return self.name


class PlatformBrowserSession(Base):
    __tablename__ = "platform_browser_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    provider: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    login_url: Mapped[str] = mapped_column(String(500))
    home_url: Mapped[str] = mapped_column(String(500))
    profile_dir: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="未初始化", index=True)
    login_process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_login_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return self.name
