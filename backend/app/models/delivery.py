from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class VoiceGatewayLine(Base):
    __tablename__ = "voice_gateway_lines"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "line_name", name="uq_voice_gateway_lines_owner_name"),
        UniqueConstraint("sip_username", name="uq_voice_gateway_lines_sip_username"),
        UniqueConstraint("trunk_name", name="uq_voice_gateway_lines_trunk_name"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    line_name: Mapped[str] = mapped_column(String(120), index=True)
    customer_name: Mapped[str] = mapped_column(String(160), default="", index=True)
    status: Mapped[str] = mapped_column(String(40), default="待配置", index=True)

    gateway_profile_key: Mapped[str] = mapped_column(String(80), default="dinstar_8t_server", index=True)
    gateway_label: Mapped[str] = mapped_column(String(160), default="")
    gateway_vendor: Mapped[str] = mapped_column(String(120), default="")
    gateway_model: Mapped[str] = mapped_column(String(120), default="")
    gateway_category: Mapped[str] = mapped_column(String(80), default="")
    deployment_mode: Mapped[str] = mapped_column(String(40), default="server", index=True)

    sip_server_host: Mapped[str] = mapped_column(String(120), default="")
    sip_server_port: Mapped[int] = mapped_column(Integer, default=5060)
    sip_transport: Mapped[str] = mapped_column(String(20), default="UDP")
    sip_username: Mapped[str] = mapped_column(String(120), index=True)
    sip_auth_username: Mapped[str] = mapped_column(String(120), index=True)
    sip_password_hash: Mapped[str] = mapped_column(String(255), default="")
    sip_password_secret_alias: Mapped[str] = mapped_column(String(180), default="")
    trunk_name: Mapped[str] = mapped_column(String(120), index=True)

    channel_count: Mapped[int] = mapped_column(Integer, default=1)
    codec_primary: Mapped[str] = mapped_column(String(40), default="PCMA/alaw")
    codec_secondary: Mapped[str] = mapped_column(String(40), default="PCMU/ulaw")
    dtmf_mode: Mapped[str] = mapped_column(String(40), default="RFC2833/RFC4733")
    rtp_port_range: Mapped[str] = mapped_column(String(40), default="10000-20000/UDP")
    route_direction: Mapped[str] = mapped_column(String(120), default="SIP中继/SIP -> VoLTE/GSM/SIM")

    device_admin_url: Mapped[str] = mapped_column(String(240), default="")
    device_serial: Mapped[str] = mapped_column(String(120), default="")
    device_mac: Mapped[str] = mapped_column(String(80), default="")
    network_note: Mapped[str] = mapped_column(Text, default="")

    registration_status: Mapped[str] = mapped_column(String(40), default="待注册", index=True)
    route_status: Mapped[str] = mapped_column(String(40), default="待检查", index=True)
    sim_status: Mapped[str] = mapped_column(String(40), default="待检查", index=True)
    rtp_status: Mapped[str] = mapped_column(String(40), default="待检查", index=True)
    acceptance_status: Mapped[str] = mapped_column(String(40), default="待单号验收", index=True)
    last_registered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_preflight_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner_user = relationship("User", foreign_keys=[owner_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    events = relationship("VoiceGatewayLineEvent", back_populates="line", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"{self.customer_name or self.owner_user_id} {self.line_name}"


class VoiceGatewayLineEvent(Base):
    __tablename__ = "voice_gateway_line_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    line_id: Mapped[str] = mapped_column(ForeignKey("voice_gateway_lines.id", ondelete="CASCADE"), index=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    summary: Mapped[str] = mapped_column(String(240), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    line = relationship("VoiceGatewayLine", back_populates="events")
    owner_user = relationship("User", foreign_keys=[owner_user_id])
    actor_user = relationship("User", foreign_keys=[actor_user_id])

    def __repr__(self) -> str:
        return f"{self.event_type} {self.status}"
