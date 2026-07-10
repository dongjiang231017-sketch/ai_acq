from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel as BaseModel


TaskChannel = Literal["collector", "call", "dm"]


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    channel: TaskChannel
    target_count: Annotated[int, Field(ge=0, alias="targetCount")] = 0
    concurrency: Annotated[int, Field(ge=1, le=50)] = 1
    script_id: Annotated[str | None, Field(alias="scriptId")] = None
    scheduled_at: Annotated[datetime | None, Field(alias="scheduledAt")] = None


class TaskRead(BaseModel):
    id: str
    name: str
    channel: TaskChannel
    status: str
    target_count: Annotated[int, Field(alias="targetCount")]
    completed_count: Annotated[int, Field(alias="completedCount")]
    connected_count: Annotated[int, Field(alias="connectedCount")]
    intent_count: Annotated[int, Field(alias="intentCount")]
    failed_count: Annotated[int, Field(alias="failedCount")]
    concurrency: int
    script_id: Annotated[str | None, Field(alias="scriptId")]
    dm_account_id: Annotated[str | None, Field(alias="dmAccountId")]
    dm_template_id: Annotated[str | None, Field(alias="dmTemplateId")]
    scheduled_at: Annotated[datetime | None, Field(alias="scheduledAt")]
    started_at: Annotated[datetime | None, Field(alias="startedAt")]
    finished_at: Annotated[datetime | None, Field(alias="finishedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OutboundTaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    lead_ids: Annotated[list[str], Field(alias="leadIds", min_length=1)]
    concurrency: Annotated[int, Field(ge=1, le=50)] = 5
    script_id: Annotated[str | None, Field(alias="scriptId")] = None
    scheduled_at: Annotated[datetime | None, Field(alias="scheduledAt")] = None


class CallScriptEntry(BaseModel):
    number: str = Field(pattern=r"^\d{2}$")
    category: str = Field(min_length=1, max_length=40)
    customer_trigger: Annotated[str, Field(alias="customerTrigger")] = ""
    content: str = Field(min_length=1)
    execution_tip: Annotated[str, Field(alias="executionTip")] = ""
    audio_file: Annotated[str, Field(alias="audioFile", min_length=1)]

    model_config = ConfigDict(populate_by_name=True)


class CallScriptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    opening: str = Field(min_length=1)
    qualification: str = Field(min_length=1)
    objection: str = Field(min_length=1)
    closing: str = Field(min_length=1)
    entries: list[CallScriptEntry] = Field(default_factory=list)
    audio_mapping: Annotated[dict[str, str], Field(alias="audioMapping")] = Field(default_factory=dict)
    is_active: Annotated[bool, Field(alias="isActive")] = True


class CallScriptUpdate(CallScriptCreate):
    pass


class CallScriptRead(CallScriptCreate):
    id: str
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CallRecordRead(BaseModel):
    id: str
    # 2026-07-09：单号试拨的通话没有任务/线索上下文，模型已改可空，schema 必须同步，
    # 否则含 None 的记录会让 /outbound/records 列表 500（本次复查抓到的真 bug）
    task_id: Annotated[str | None, Field(alias="taskId")] = None
    lead_id: Annotated[str | None, Field(alias="leadId")] = None
    merchant_name: Annotated[str, Field(alias="merchantName")]
    phone: str | None
    ai_seat: Annotated[str, Field(alias="aiSeat")]
    duration_seconds: Annotated[int, Field(alias="durationSeconds")]
    intent_level: Annotated[str, Field(alias="intentLevel")]
    current_node: Annotated[str, Field(alias="currentNode")]
    outcome: str
    transcript: str
    gateway_call_id: Annotated[str | None, Field(alias="gatewayCallId")]
    gateway_status: Annotated[str, Field(alias="gatewayStatus")]
    raw_payload: Annotated[str | None, Field(alias="rawPayload")]
    need_handoff: Annotated[bool, Field(alias="needHandoff")]
    recall_at: Annotated[datetime | None, Field(alias="recallAt")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RecallRuleRead(BaseModel):
    id: str
    name: str
    no_answer_interval_minutes: Annotated[int, Field(alias="noAnswerIntervalMinutes")]
    busy_interval_minutes: Annotated[int, Field(alias="busyIntervalMinutes")]
    max_attempts: Annotated[int, Field(alias="maxAttempts")]
    quiet_start: Annotated[str, Field(alias="quietStart")]
    quiet_end: Annotated[str, Field(alias="quietEnd")]
    enabled: bool

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RecallRuleUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    no_answer_interval_minutes: Annotated[int, Field(ge=1, le=10080, alias="noAnswerIntervalMinutes")]
    busy_interval_minutes: Annotated[int, Field(ge=1, le=10080, alias="busyIntervalMinutes")]
    max_attempts: Annotated[int, Field(ge=1, le=20, alias="maxAttempts")]
    quiet_start: Annotated[str, Field(alias="quietStart")]
    quiet_end: Annotated[str, Field(alias="quietEnd")]
    enabled: bool


class OutboundOverview(BaseModel):
    ai_seats: Annotated[int, Field(alias="aiSeats")]
    active_calls: Annotated[int, Field(alias="activeCalls")]
    needs_handoff: Annotated[int, Field(alias="needsHandoff")]
    silent_alerts: Annotated[int, Field(alias="silentAlerts")]
    today_calls: Annotated[int, Field(alias="todayCalls")]
    connected_rate: Annotated[int, Field(alias="connectedRate")]
    intent_count: Annotated[int, Field(alias="intentCount")]


class VoiceGatewayProfileRead(BaseModel):
    key: str
    label: str
    vendor: str
    model: str
    category: str
    transport: str
    host: str
    sip_port: Annotated[int, Field(alias="sipPort")]
    trunk_name: Annotated[str, Field(alias="trunkName")]
    max_channels: Annotated[int, Field(alias="maxChannels")]
    line_type: Annotated[str, Field(alias="lineType")]
    admin_url: Annotated[str, Field(alias="adminUrl")]
    discovery_mode: Annotated[str, Field(alias="discoveryMode")]
    tested: bool
    capabilities: list[str]
    notes: list[str]


class TelephonyConfigRead(BaseModel):
    gateway_mode: Annotated[str, Field(alias="gatewayMode")]
    asterisk_deployment_mode: Annotated[str, Field(alias="asteriskDeploymentMode")]
    voice_gateway_profile: Annotated[VoiceGatewayProfileRead, Field(alias="voiceGatewayProfile")]
    queue_enabled: Annotated[bool, Field(alias="queueEnabled")]
    queue_name: Annotated[str, Field(alias="queueName")]
    redis_url_configured: Annotated[bool, Field(alias="redisUrlConfigured")]
    asterisk_host: Annotated[str, Field(alias="asteriskHost")]
    asterisk_ami_port: Annotated[int, Field(alias="asteriskAmiPort")]
    asterisk_username_configured: Annotated[bool, Field(alias="asteriskUsernameConfigured")]
    asterisk_trunk_name: Annotated[str, Field(alias="asteriskTrunkName")]
    asterisk_max_channels: Annotated[int, Field(alias="asteriskMaxChannels")]
    asterisk_live_call_enabled: Annotated[bool, Field(alias="asteriskLiveCallEnabled")]
    asterisk_bulk_call_enabled: Annotated[bool, Field(alias="asteriskBulkCallEnabled")]


class TelephonyHealthRead(BaseModel):
    checked_at: Annotated[datetime, Field(alias="checkedAt")]
    gateway_mode: Annotated[str, Field(alias="gatewayMode")]
    asterisk_deployment_mode: Annotated[str, Field(alias="asteriskDeploymentMode")]
    voice_gateway_profile: Annotated[VoiceGatewayProfileRead, Field(alias="voiceGatewayProfile")]
    configured: bool
    live_call_enabled: Annotated[bool, Field(alias="liveCallEnabled")]
    bulk_call_enabled: Annotated[bool, Field(alias="bulkCallEnabled")]
    ami_reachable: Annotated[bool, Field(alias="amiReachable")]
    authenticated: bool
    ping_ok: Annotated[bool, Field(alias="pingOk")]
    trunk_configured: Annotated[bool, Field(alias="trunkConfigured")]
    trunk_reachable: Annotated[bool | None, Field(alias="trunkReachable")]
    trunk_status: Annotated[str, Field(alias="trunkStatus")]
    max_channels: Annotated[int, Field(alias="maxChannels")]
    ready_for_test_call: Annotated[bool, Field(alias="readyForTestCall")]
    errors: list[str]


class TelephonyPreflightStepRead(BaseModel):
    key: str
    label: str
    status: str
    detail: str
    action: str


class TelephonyPreflightRead(BaseModel):
    checked_at: Annotated[datetime, Field(alias="checkedAt")]
    voice_gateway_profile: Annotated[VoiceGatewayProfileRead, Field(alias="voiceGatewayProfile")]
    ready_for_device_test: Annotated[bool, Field(alias="readyForDeviceTest")]
    ready_for_single_number_test: Annotated[bool, Field(alias="readyForSingleNumberTest")]
    ready_for_bulk_tasks: Annotated[bool, Field(alias="readyForBulkTasks")]
    next_step: Annotated[str, Field(alias="nextStep")]
    health: TelephonyHealthRead
    steps: list[TelephonyPreflightStepRead]


class TelephonyTestCallCreate(BaseModel):
    phone: Annotated[str, Field(min_length=3, max_length=40)]
    caller_id: Annotated[str | None, Field(alias="callerId")] = None
    merchant_name: Annotated[str | None, Field(alias="merchantName", max_length=120)] = None
    conversation_route: Annotated[str | None, Field(alias="conversationRoute", pattern="^(pipeline|omni|livekit)$")] = None

    model_config = ConfigDict(populate_by_name=True)


class TelephonyCellularDiagnosticRead(BaseModel):
    status: str
    stage: str
    title: str
    summary: str
    detail: str
    action_items: Annotated[list[str], Field(alias="actionItems")]
    technical_detail: Annotated[str, Field(alias="technicalDetail")] = ""
    can_retry: Annotated[bool, Field(alias="canRetry")]
    customer_action_required: Annotated[bool, Field(alias="customerActionRequired")]


class TelephonyRecoveryCommandRead(BaseModel):
    command: str
    ok: bool
    message: str = ""
    output: str = ""


class TelephonyLineRecoveryRead(BaseModel):
    checked_at: Annotated[datetime, Field(alias="checkedAt")]
    status: str
    summary: str
    commands: list[TelephonyRecoveryCommandRead]
    health: TelephonyHealthRead
    next_step: Annotated[str, Field(alias="nextStep")]


class TelephonyTestCallRead(BaseModel):
    accepted: bool
    action_id: Annotated[str, Field(alias="actionId")]
    channel: str
    requested_route: Annotated[str, Field(alias="requestedRoute")]
    actual_bridge_route: Annotated[str, Field(alias="actualBridgeRoute")]
    effective_route: Annotated[str, Field(alias="effectiveRoute")] = ""
    route_fallback_reason: Annotated[str, Field(alias="routeFallbackReason")] = ""
    route_matched: Annotated[bool, Field(alias="routeMatched")]
    gateway_status: Annotated[str, Field(alias="gatewayStatus")]
    message: str
    raw_payload: Annotated[str, Field(alias="rawPayload")]
    verification_stage: Annotated[str, Field(alias="verificationStage")]
    cellular_confirmed: Annotated[bool, Field(alias="cellularConfirmed")]
    media_loop_confirmed: Annotated[bool, Field(alias="mediaLoopConfirmed")]
    human_speech_confirmed: Annotated[bool, Field(alias="humanSpeechConfirmed")] = False
    ai_speech_confirmed: Annotated[bool, Field(alias="aiSpeechConfirmed")] = False
    call_screening_detected: Annotated[bool, Field(alias="callScreeningDetected")] = False
    bridge_error: Annotated[str, Field(alias="bridgeError")] = ""
    conversation_confirmed: Annotated[bool, Field(alias="conversationConfirmed")] = False
    acceptance_ready: Annotated[bool, Field(alias="acceptanceReady")]
    acceptance_note: Annotated[str, Field(alias="acceptanceNote")]
    cellular_diagnostic: Annotated[TelephonyCellularDiagnosticRead, Field(alias="cellularDiagnostic")]
    auto_recovery: Annotated[TelephonyLineRecoveryRead | None, Field(alias="autoRecovery")] = None


class RealtimePipelineStepRead(BaseModel):
    key: str
    label: str
    status: str
    provider: str
    latency_ms: Annotated[int, Field(alias="latencyMs")]
    detail: str


class RealtimeRouteOptionRead(BaseModel):
    key: str
    label: str
    mode: str
    summary: str
    estimated_latency_ms: Annotated[int, Field(alias="estimatedLatencyMs")]
    estimated_ai_cost_per_minute: Annotated[float, Field(alias="estimatedAiCostPerMinute")]
    ready_for_asterisk_media: Annotated[bool, Field(alias="readyForAsteriskMedia")]
    is_active: Annotated[bool, Field(alias="isActive")]


class RealtimeRouteBenchmarkRead(BaseModel):
    key: str
    label: str
    status: str
    quality_score: Annotated[int, Field(alias="qualityScore")]
    readiness_score: Annotated[int, Field(alias="readinessScore")]
    estimated_latency_ms: Annotated[int, Field(alias="estimatedLatencyMs")]
    estimated_ai_cost_per_minute: Annotated[float, Field(alias="estimatedAiCostPerMinute")]
    cost_rank: Annotated[int, Field(alias="costRank")]
    risk_level: Annotated[str, Field(alias="riskLevel")]
    strengths: list[str]
    risks: list[str]
    next_action: Annotated[str, Field(alias="nextAction")]


class RealtimeRouteBenchmarkReportRead(BaseModel):
    recommended_route: Annotated[str, Field(alias="recommendedRoute")]
    status: str
    summary: str
    low_cost_first: Annotated[bool, Field(alias="lowCostFirst")]
    latest_score: Annotated[int | None, Field(alias="latestScore")] = None
    latest_turn_response_ms: Annotated[int | None, Field(alias="latestTurnResponseMs")] = None
    benchmarks: list[RealtimeRouteBenchmarkRead]


class RealtimeLearningSummaryRead(BaseModel):
    recent_lesson_count: Annotated[int, Field(alias="recentLessonCount")]
    active_guidance_count: Annotated[int, Field(alias="activeGuidanceCount")]
    avoid_phrase_count: Annotated[int, Field(alias="avoidPhraseCount")]
    quality_tags: Annotated[list[str], Field(alias="qualityTags")]
    latest_guidance: Annotated[list[str], Field(alias="latestGuidance")]
    avoid_phrases: Annotated[list[str], Field(alias="avoidPhrases")]
    summary: str


class RealtimePipelineRead(BaseModel):
    mode: str
    bridge_mode: Annotated[str, Field(alias="bridgeMode")]
    target_latency_ms: Annotated[int, Field(alias="targetLatencyMs")]
    estimated_latency_ms: Annotated[int, Field(alias="estimatedLatencyMs")]
    estimated_ai_cost_per_minute: Annotated[float, Field(alias="estimatedAiCostPerMinute")]
    ready_for_mock_call: Annotated[bool, Field(alias="readyForMockCall")]
    ready_for_asterisk_media: Annotated[bool, Field(alias="readyForAsteriskMedia")]
    configured_route: Annotated[str, Field(alias="configuredRoute")] = "pipeline"
    actual_bridge_route: Annotated[str, Field(alias="actualBridgeRoute")] = "pipeline"
    route_matched: Annotated[bool, Field(alias="routeMatched")] = True
    next_step: Annotated[str, Field(alias="nextStep")]
    route_options: Annotated[list[RealtimeRouteOptionRead], Field(alias="routeOptions")] = []
    route_benchmark: Annotated[RealtimeRouteBenchmarkReportRead | None, Field(alias="routeBenchmark")] = None
    learning: RealtimeLearningSummaryRead | None = None
    steps: list[RealtimePipelineStepRead]


class RealtimeVoiceSelection(BaseModel):
    voice_id: Annotated[str, Field(alias="voiceId")]
    voice_name: Annotated[str, Field(alias="voiceName")]
    voice_type: Annotated[str, Field(alias="voiceType")] = "system"
    provider: str = "Qwen-TTS"
    external_voice_id: Annotated[str | None, Field(alias="externalVoiceId")] = None

    model_config = ConfigDict(populate_by_name=True)


class RealtimeSessionCreate(BaseModel):
    merchant_name: Annotated[str, Field(alias="merchantName", min_length=1, max_length=120)] = "模拟商家"
    phone: Annotated[str | None, Field(max_length=40)] = None
    voice: RealtimeVoiceSelection
    conversation_route: Annotated[str, Field(alias="conversationRoute", pattern="^(pipeline|omni|livekit)$")] = "pipeline"

    model_config = ConfigDict(populate_by_name=True)


class RealtimeUtteranceCreate(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=500)]
    barge_in: Annotated[bool, Field(alias="bargeIn")] = True

    model_config = ConfigDict(populate_by_name=True)


class RealtimeEventRead(BaseModel):
    id: str
    at: datetime
    type: str
    actor: str
    status: str
    text: str
    detail: str
    latency_ms: Annotated[int, Field(alias="latencyMs")]


class RealtimeTtsChunkRead(BaseModel):
    index: int
    text: str
    duration_ms: Annotated[int, Field(alias="durationMs")]
    provider: str


class RealtimeSessionRead(BaseModel):
    id: str
    status: str
    mode: str
    bridge_mode: Annotated[str, Field(alias="bridgeMode")]
    merchant_name: Annotated[str, Field(alias="merchantName")]
    phone: str | None
    voice: RealtimeVoiceSelection
    current_intent: Annotated[str, Field(alias="currentIntent")]
    current_node: Annotated[str, Field(alias="currentNode")]
    interruptions: int
    cost_estimate_per_minute: Annotated[float, Field(alias="costEstimatePerMinute")]
    latency_estimate_ms: Annotated[int, Field(alias="latencyEstimateMs")]
    started_at: Annotated[datetime, Field(alias="startedAt")]
    updated_at: Annotated[datetime, Field(alias="updatedAt")]
    events: list[RealtimeEventRead]


class RealtimeTurnRead(BaseModel):
    session: RealtimeSessionRead
    asr_text: Annotated[str, Field(alias="asrText")]
    intent: str
    reply: str
    interrupted: bool
    tts_chunks: Annotated[list[RealtimeTtsChunkRead], Field(alias="ttsChunks")]


class RealtimeLiveEventRead(BaseModel):
    id: str
    at: str
    type: str
    call_id: Annotated[str | None, Field(alias="callId")] = None
    text: str | None = None
    reply: str | None = None
    strategy: str | None = None
    latency_ms: Annotated[int, Field(alias="latencyMs")] = 0
    detail: str | None = None
    raw: dict[str, object]


class RealtimeLiveScoreMetricRead(BaseModel):
    name: str
    score: int
    status: str
    weight: float
    detail: str


class RealtimeLiveScoreRead(BaseModel):
    call_id: Annotated[str | None, Field(alias="callId")] = None
    score: int
    status: str
    summary: str
    metrics: list[RealtimeLiveScoreMetricRead]


class RealtimeLiveStateRead(BaseModel):
    call_id: Annotated[str | None, Field(alias="callId")] = None
    state: str
    label: str
    status: str
    close_reason: Annotated[str | None, Field(alias="closeReason")] = None
    can_auto_close: Annotated[bool, Field(alias="canAutoClose")]
    auto_close_scheduled: Annotated[bool, Field(alias="autoCloseScheduled")]
    human_speech_confirmed: Annotated[bool, Field(alias="humanSpeechConfirmed")]
    call_screening_detected: Annotated[bool, Field(alias="callScreeningDetected")]
    voicemail_detected: Annotated[bool, Field(alias="voicemailDetected")]
    silence_detected: Annotated[bool, Field(alias="silenceDetected")]
    no_response_detected: Annotated[bool, Field(alias="noResponseDetected")]
    hangup_detected: Annotated[bool, Field(alias="hangupDetected")]
    ai_speech_confirmed: Annotated[bool, Field(alias="aiSpeechConfirmed")]
    customer_speech_confirmed: Annotated[bool, Field(alias="customerSpeechConfirmed")]
    interruption_detected: Annotated[bool, Field(alias="interruptionDetected")]
    turn_taking_status: Annotated[str, Field(alias="turnTakingStatus")]
    latest_turn_response_ms: Annotated[int | None, Field(alias="latestTurnResponseMs")] = None
    current_phase: Annotated[str, Field(alias="currentPhase")] = "unknown"
    phase_label: Annotated[str, Field(alias="phaseLabel")] = "状态未知"
    turn_action: Annotated[str, Field(alias="turnAction")] = ""
    latency_breakdown: Annotated[dict[str, int | None], Field(default_factory=dict, alias="latencyBreakdown")]
    last_customer_text: Annotated[str | None, Field(alias="lastCustomerText")] = None
    last_ai_reply: Annotated[str | None, Field(alias="lastAiReply")] = None
    last_event_at: Annotated[str | None, Field(alias="lastEventAt")] = None
    issues: list[str]


class RealtimeLiveEventsRead(BaseModel):
    log_path: Annotated[str, Field(alias="logPath")]
    has_events: Annotated[bool, Field(alias="hasEvents")]
    latest_at: Annotated[str | None, Field(alias="latestAt")]
    score: RealtimeLiveScoreRead | None = None
    state: RealtimeLiveStateRead | None = None
    events: list[RealtimeLiveEventRead]
