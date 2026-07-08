from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel as BaseModel


class VoiceOverview(BaseModel):
    profiles: int
    usable_profiles: Annotated[int, Field(alias="usableProfiles")]
    pending_authorization: Annotated[int, Field(alias="pendingAuthorization")]
    training_jobs: Annotated[int, Field(alias="trainingJobs")]
    usage_records: Annotated[int, Field(alias="usageRecords")]
    fallback_usage: Annotated[int, Field(alias="fallbackUsage")]
    system_voices: Annotated[int, Field(alias="systemVoices")] = 0
    default_voice: Annotated[str, Field(alias="defaultVoice")] = "晨煦（Ethan）"
    clone_training_enabled: Annotated[bool, Field(alias="cloneTrainingEnabled")] = False
    clone_engine_name: Annotated[str, Field(alias="cloneEngineName")] = ""
    clone_engine_status: Annotated[str, Field(alias="cloneEngineStatus")] = "未接入"
    clone_engine_message: Annotated[str, Field(alias="cloneEngineMessage")] = "真实声音克隆服务未接入"

    model_config = ConfigDict(populate_by_name=True)


class SystemVoiceRead(BaseModel):
    id: str
    name: str
    provider: str
    voice_param: Annotated[str, Field(alias="voiceParam")]
    gender: str
    style: str
    scenario: str
    status: str
    is_default: Annotated[bool, Field(alias="isDefault")]
    sample_text: Annotated[str, Field(alias="sampleText")]

    model_config = ConfigDict(populate_by_name=True)


class SystemVoicePreviewRead(BaseModel):
    voice_id: Annotated[str, Field(alias="voiceId")]
    voice_param: Annotated[str, Field(alias="voiceParam")]
    audio_url: Annotated[str, Field(alias="audioUrl")]
    preview_text: Annotated[str, Field(alias="previewText")]
    message: str

    model_config = ConfigDict(populate_by_name=True)


class VoiceDefaultSelection(BaseModel):
    voice_id: Annotated[str, Field(alias="voiceId")]
    voice_name: Annotated[str, Field(alias="voiceName")]
    voice_type: Annotated[str, Field(alias="voiceType")] = "system"
    provider: str = "Qwen-TTS"
    voice_param: Annotated[str | None, Field(alias="voiceParam")] = None
    external_voice_id: Annotated[str | None, Field(alias="externalVoiceId")] = None

    model_config = ConfigDict(populate_by_name=True)


class VoiceDefaultSelectionRead(VoiceDefaultSelection):
    message: str
    effective_without_restart: Annotated[bool, Field(alias="effectiveWithoutRestart")] = True

    model_config = ConfigDict(populate_by_name=True)


class VoiceCacheStatusRead(BaseModel):
    enabled: bool
    root: str
    profile: str
    display_name: Annotated[str, Field(alias="displayName")]
    asset_version: Annotated[str, Field(alias="assetVersion")]
    manifest_loaded: Annotated[bool, Field(alias="manifestLoaded")]
    item_count: Annotated[int, Field(alias="itemCount")]
    intent_count: Annotated[int, Field(alias="intentCount")]
    min_confidence: Annotated[float, Field(alias="minConfidence")]

    model_config = ConfigDict(populate_by_name=True)


class VoiceCachePreferenceUpdate(BaseModel):
    enabled: bool

    model_config = ConfigDict(populate_by_name=True)


class VoiceCacheItemRead(BaseModel):
    seq: str
    scene_id: Annotated[str, Field(alias="sceneId")]
    scene_title: Annotated[str, Field(alias="sceneTitle")]
    section: str
    customer_trigger: Annotated[str, Field(alias="customerTrigger")]
    human_text: Annotated[str, Field(alias="humanText")]
    audio_format: Annotated[str, Field(alias="audioFormat")]
    audio_url: Annotated[str, Field(alias="audioUrl")]

    model_config = ConfigDict(populate_by_name=True)


class VoiceCacheIntentRead(BaseModel):
    intent_id: Annotated[str, Field(alias="intentId")]
    priority: str
    seq_candidates: Annotated[list[str], Field(alias="seqCandidates")]
    scene_title: Annotated[str, Field(alias="sceneTitle")]
    trigger_examples: Annotated[list[str], Field(alias="triggerExamples")]
    recommended_action: Annotated[str, Field(alias="recommendedAction")]

    model_config = ConfigDict(populate_by_name=True)


class VoiceCacheLibraryRead(VoiceCacheStatusRead):
    items: list[VoiceCacheItemRead]
    intents: list[VoiceCacheIntentRead]

    model_config = ConfigDict(populate_by_name=True)


class VoiceProviderStatusRead(BaseModel):
    provider: str
    configured: bool
    ready: bool
    status: str
    message: str
    engine_name: Annotated[str, Field(alias="engineName")]
    clone_model: Annotated[str, Field(alias="cloneModel")]
    tts_model: Annotated[str, Field(alias="ttsModel")]
    sample_public_base_url_configured: Annotated[bool, Field(alias="samplePublicBaseUrlConfigured")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class VoiceProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner_name: Annotated[str, Field(alias="ownerName")] = "待授权人"
    scenario: str = "外呼"
    status: str = "待授权"
    authorization_status: Annotated[str, Field(alias="authorizationStatus")] = "待提交"
    sample_count: Annotated[int, Field(alias="sampleCount", ge=0)] = 0
    fallback_voice: Annotated[str, Field(alias="fallbackVoice")] = "晨煦（Ethan）"
    consent_material: Annotated[str, Field(alias="consentMaterial")] = ""
    risk_note: Annotated[str, Field(alias="riskNote")] = ""

    model_config = ConfigDict(populate_by_name=True)


class VoiceProfileUpdate(BaseModel):
    status: str | None = None
    authorization_status: Annotated[str | None, Field(alias="authorizationStatus")] = None
    sample_count: Annotated[int | None, Field(alias="sampleCount", ge=0)] = None
    fallback_voice: Annotated[str | None, Field(alias="fallbackVoice")] = None
    consent_material: Annotated[str | None, Field(alias="consentMaterial")] = None
    risk_note: Annotated[str | None, Field(alias="riskNote")] = None

    model_config = ConfigDict(populate_by_name=True)


class VoiceProfileRead(VoiceProfileCreate):
    id: str
    created_at: Annotated[datetime, Field(alias="createdAt")]
    updated_at: Annotated[datetime, Field(alias="updatedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class VoiceTrainingJobCreate(BaseModel):
    engine: str = "真实声音克隆服务"
    sample_minutes: Annotated[int, Field(alias="sampleMinutes", ge=0)] = 0
    message: str = ""

    model_config = ConfigDict(populate_by_name=True)


class VoiceTrainingJobRead(VoiceTrainingJobCreate):
    id: str
    profile_id: Annotated[str, Field(alias="profileId")]
    status: str
    progress: int
    created_at: Annotated[datetime, Field(alias="createdAt")]
    started_at: Annotated[datetime | None, Field(alias="startedAt")]
    finished_at: Annotated[datetime | None, Field(alias="finishedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class VoiceSampleRead(BaseModel):
    id: str
    profile_id: Annotated[str, Field(alias="profileId")]
    file_name: Annotated[str, Field(alias="fileName")]
    content_type: Annotated[str, Field(alias="contentType")]
    size_bytes: Annotated[int, Field(alias="sizeBytes")]
    duration_seconds: Annotated[int, Field(alias="durationSeconds")]
    quality_status: Annotated[str, Field(alias="qualityStatus")]
    transcript: str
    uploaded_by: Annotated[str, Field(alias="uploadedBy")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class VoiceCloneRecordRead(BaseModel):
    id: str
    profile_id: Annotated[str, Field(alias="profileId")]
    training_job_id: Annotated[str | None, Field(alias="trainingJobId")]
    cloned_voice_name: Annotated[str, Field(alias="clonedVoiceName")]
    engine: str
    external_voice_id: Annotated[str, Field(alias="externalVoiceId")] = ""
    preview_audio_url: Annotated[str, Field(alias="previewAudioUrl")] = ""
    status: str
    sample_count: Annotated[int, Field(alias="sampleCount")]
    sample_minutes: Annotated[int, Field(alias="sampleMinutes")]
    result: str
    created_at: Annotated[datetime, Field(alias="createdAt")]
    completed_at: Annotated[datetime | None, Field(alias="completedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class VoiceUsageRecordRead(BaseModel):
    id: str
    profile_id: Annotated[str | None, Field(alias="profileId")]
    task_id: Annotated[str | None, Field(alias="taskId")]
    merchant_name: Annotated[str, Field(alias="merchantName")]
    scenario: str
    result: str
    fallback_used: Annotated[bool, Field(alias="fallbackUsed")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
