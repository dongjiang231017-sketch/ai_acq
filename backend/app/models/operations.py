from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ReportExport(Base):
    __tablename__ = "report_exports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    report_type: Mapped[str] = mapped_column(String(80), default="经营总览", index=True)
    date_range: Mapped[str] = mapped_column(String(80), default="近30天")
    file_format: Mapped[str] = mapped_column(String(20), default="xlsx")
    requester: Mapped[str] = mapped_column(String(80), default="运营管理员", index=True)
    status: Mapped[str] = mapped_column(String(40), default="已生成", index=True)
    download_url: Mapped[str] = mapped_column(String(240), default="")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    sensitive_fields_included: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"{self.report_type} {self.status}"


class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = (UniqueConstraint("group_key", "item_key", name="uq_system_settings_group_item"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    group_key: Mapped[str] = mapped_column(String(40), index=True)
    item_key: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    value_type: Mapped[str] = mapped_column(String(240), default="text")
    status: Mapped[str] = mapped_column(String(40), default="已启用", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    updated_by: Mapped[str] = mapped_column(String(80), default="系统")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return self.label


class SystemAuditLog(Base):
    __tablename__ = "system_audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    actor: Mapped[str] = mapped_column(String(80), default="系统", index=True)
    action: Mapped[str] = mapped_column(String(80), default="update", index=True)
    target_type: Mapped[str] = mapped_column(String(80), default="system_setting", index=True)
    target_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(String(240), default="")
    before_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return self.summary
