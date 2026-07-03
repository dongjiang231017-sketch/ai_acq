from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel as BaseModel


GatewayTransport = Literal["UDP", "TCP", "TLS"]


class VoiceGatewayConfigField(BaseModel):
    label: str
    value: str
    target: str
    note: str = ""


class VoiceGatewayDeliveryStep(BaseModel):
    key: str
    label: str
    detail: str
    expected_result: Annotated[str, Field(alias="expectedResult")]


class VoiceGatewayConfigCard(BaseModel):
    line_id: Annotated[str, Field(alias="lineId")]
    customer_name: Annotated[str, Field(alias="customerName")]
    line_name: Annotated[str, Field(alias="lineName")]
    gateway_profile_key: Annotated[str, Field(alias="gatewayProfileKey")]
    gateway_label: Annotated[str, Field(alias="gatewayLabel")]
    sip_server: Annotated[str, Field(alias="sipServer")]
    sip_port: Annotated[int, Field(alias="sipPort")]
    sip_transport: Annotated[str, Field(alias="sipTransport")]
    sip_username: Annotated[str, Field(alias="sipUsername")]
    sip_auth_username: Annotated[str, Field(alias="sipAuthUsername")]
    sip_password_secret_alias: Annotated[str, Field(alias="sipPasswordSecretAlias")]
    sip_password_display: Annotated[str, Field(alias="sipPasswordDisplay")] = "********"
    trunk_name: Annotated[str, Field(alias="trunkName")]
    channel_count: Annotated[int, Field(alias="channelCount")]
    codec_primary: Annotated[str, Field(alias="codecPrimary")]
    codec_secondary: Annotated[str, Field(alias="codecSecondary")]
    dtmf_mode: Annotated[str, Field(alias="dtmfMode")]
    rtp_port_range: Annotated[str, Field(alias="rtpPortRange")]
    route_direction: Annotated[str, Field(alias="routeDirection")]
    field_mapping: Annotated[list[VoiceGatewayConfigField], Field(alias="fieldMapping")]
    delivery_steps: Annotated[list[VoiceGatewayDeliveryStep], Field(alias="deliverySteps")]


class VoiceGatewayLineCreate(BaseModel):
    line_name: Annotated[str, Field(alias="lineName", min_length=1, max_length=120)] = "默认语音线路"
    owner_user_id: Annotated[str | None, Field(alias="ownerUserId")] = None
    customer_name: Annotated[str | None, Field(alias="customerName", max_length=160)] = None
    gateway_profile_key: Annotated[str, Field(alias="gatewayProfileKey", max_length=80)] = "dinstar_8t_server"
    gateway_label: Annotated[str | None, Field(alias="gatewayLabel", max_length=160)] = None
    gateway_vendor: Annotated[str | None, Field(alias="gatewayVendor", max_length=120)] = None
    gateway_model: Annotated[str | None, Field(alias="gatewayModel", max_length=120)] = None
    gateway_category: Annotated[str | None, Field(alias="gatewayCategory", max_length=80)] = None
    sip_server_host: Annotated[str, Field(alias="sipServerHost", min_length=1, max_length=120)] = "101.132.63.159"
    sip_server_port: Annotated[int, Field(alias="sipServerPort", ge=1, le=65535)] = 5060
    sip_transport: Annotated[GatewayTransport, Field(alias="sipTransport")] = "UDP"
    channel_count: Annotated[int, Field(alias="channelCount", ge=1, le=256)] = 1
    device_admin_url: Annotated[str | None, Field(alias="deviceAdminUrl", max_length=240)] = None
    device_serial: Annotated[str | None, Field(alias="deviceSerial", max_length=120)] = None
    device_mac: Annotated[str | None, Field(alias="deviceMac", max_length=80)] = None
    network_note: Annotated[str | None, Field(alias="networkNote")] = None
    notes: str | None = None


class VoiceGatewayLineUpdate(BaseModel):
    line_name: Annotated[str | None, Field(alias="lineName", min_length=1, max_length=120)] = None
    customer_name: Annotated[str | None, Field(alias="customerName", max_length=160)] = None
    gateway_label: Annotated[str | None, Field(alias="gatewayLabel", max_length=160)] = None
    gateway_vendor: Annotated[str | None, Field(alias="gatewayVendor", max_length=120)] = None
    gateway_model: Annotated[str | None, Field(alias="gatewayModel", max_length=120)] = None
    gateway_category: Annotated[str | None, Field(alias="gatewayCategory", max_length=80)] = None
    sip_server_host: Annotated[str | None, Field(alias="sipServerHost", min_length=1, max_length=120)] = None
    sip_server_port: Annotated[int | None, Field(alias="sipServerPort", ge=1, le=65535)] = None
    sip_transport: Annotated[GatewayTransport | None, Field(alias="sipTransport")] = None
    channel_count: Annotated[int | None, Field(alias="channelCount", ge=1, le=256)] = None
    device_admin_url: Annotated[str | None, Field(alias="deviceAdminUrl", max_length=240)] = None
    device_serial: Annotated[str | None, Field(alias="deviceSerial", max_length=120)] = None
    device_mac: Annotated[str | None, Field(alias="deviceMac", max_length=80)] = None
    network_note: Annotated[str | None, Field(alias="networkNote")] = None
    notes: str | None = None


class VoiceGatewayLineRead(BaseModel):
    id: str
    owner_user_id: Annotated[str, Field(alias="ownerUserId")]
    created_by_user_id: Annotated[str | None, Field(alias="createdByUserId")]
    line_name: Annotated[str, Field(alias="lineName")]
    customer_name: Annotated[str, Field(alias="customerName")]
    status: str
    gateway_profile_key: Annotated[str, Field(alias="gatewayProfileKey")]
    gateway_label: Annotated[str, Field(alias="gatewayLabel")]
    gateway_vendor: Annotated[str, Field(alias="gatewayVendor")]
    gateway_model: Annotated[str, Field(alias="gatewayModel")]
    gateway_category: Annotated[str, Field(alias="gatewayCategory")]
    deployment_mode: Annotated[str, Field(alias="deploymentMode")]
    sip_server_host: Annotated[str, Field(alias="sipServerHost")]
    sip_server_port: Annotated[int, Field(alias="sipServerPort")]
    sip_transport: Annotated[str, Field(alias="sipTransport")]
    sip_username: Annotated[str, Field(alias="sipUsername")]
    sip_auth_username: Annotated[str, Field(alias="sipAuthUsername")]
    sip_password_secret_alias: Annotated[str, Field(alias="sipPasswordSecretAlias")]
    sip_password_display: Annotated[str, Field(alias="sipPasswordDisplay")] = "********"
    trunk_name: Annotated[str, Field(alias="trunkName")]
    channel_count: Annotated[int, Field(alias="channelCount")]
    codec_primary: Annotated[str, Field(alias="codecPrimary")]
    codec_secondary: Annotated[str, Field(alias="codecSecondary")]
    dtmf_mode: Annotated[str, Field(alias="dtmfMode")]
    rtp_port_range: Annotated[str, Field(alias="rtpPortRange")]
    route_direction: Annotated[str, Field(alias="routeDirection")]
    device_admin_url: Annotated[str, Field(alias="deviceAdminUrl")]
    device_serial: Annotated[str, Field(alias="deviceSerial")]
    device_mac: Annotated[str, Field(alias="deviceMac")]
    network_note: Annotated[str, Field(alias="networkNote")]
    registration_status: Annotated[str, Field(alias="registrationStatus")]
    route_status: Annotated[str, Field(alias="routeStatus")]
    sim_status: Annotated[str, Field(alias="simStatus")]
    rtp_status: Annotated[str, Field(alias="rtpStatus")]
    acceptance_status: Annotated[str, Field(alias="acceptanceStatus")]
    last_registered_at: Annotated[datetime | None, Field(alias="lastRegisteredAt")]
    last_preflight_at: Annotated[datetime | None, Field(alias="lastPreflightAt")]
    notes: str
    config_card: Annotated[VoiceGatewayConfigCard, Field(alias="configCard")]
    created_at: Annotated[datetime, Field(alias="createdAt")]
    updated_at: Annotated[datetime, Field(alias="updatedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class VoiceGatewayLineCreated(VoiceGatewayLineRead):
    sip_password_one_time: Annotated[str, Field(alias="sipPasswordOneTime")]
    one_time_warning: Annotated[str, Field(alias="oneTimeWarning")]


class VoiceGatewayCredentialRotation(BaseModel):
    line: VoiceGatewayLineRead
    sip_password_one_time: Annotated[str, Field(alias="sipPasswordOneTime")]
    one_time_warning: Annotated[str, Field(alias="oneTimeWarning")]


class VoiceGatewayLineEventCreate(BaseModel):
    event_type: Annotated[
        str,
        Field(alias="eventType", pattern="^(sip_registration|gateway_route|sim_voice|rtp_media|single_call|asr_tts|live_monitor|note)$"),
    ]
    status: Annotated[str, Field(min_length=1, max_length=40)]
    summary: Annotated[str, Field(max_length=240)] = ""
    detail: str = ""
    evidence_json: Annotated[str, Field(alias="evidenceJson")] = ""


class VoiceGatewayLineEventRead(BaseModel):
    id: str
    line_id: Annotated[str, Field(alias="lineId")]
    owner_user_id: Annotated[str, Field(alias="ownerUserId")]
    actor_user_id: Annotated[str | None, Field(alias="actorUserId")]
    event_type: Annotated[str, Field(alias="eventType")]
    status: str
    summary: str
    detail: str
    evidence_json: Annotated[str, Field(alias="evidenceJson")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
