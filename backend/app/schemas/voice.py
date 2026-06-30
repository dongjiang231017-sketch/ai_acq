from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class VoiceOverview(BaseModel):
    profiles: int
    usable_profiles: Annotated[int, Field(alias="usableProfiles")]
    pending_authorization: Annotated[int, Field(alias="pendingAuthorization")]
    training_jobs: Annotated[int, Field(alias="trainingJobs")]
    usage_records: Annotated[int, Field(alias="usageRecords")]
    fallback_usage: Annotated[int, Field(alias="fallbackUsage")]
    system_voices: Annotated[int, Field(alias="systemVoices")] = 0
    default_voice: Annotated[str, Field(alias="defaultVoice")] = "标准AI音色"
    clone_training_enabled: Annotated[bool, Field(alias="cloneTrainingEnabled")] = False
    clone_engine_name: Annotated[str, Field(alias="cloneEngineName")] = ""
    clone_engine_status: Annotated[str, Field(alias="cloneEngineStatus")] = "未接入"
    clone_engine_message: Annotated[str, Field(alias="cloneEngineMessage")] = "真实声音克隆服务未接入"

    model_config = ConfigDict(populate_by_name=True)


class SystemVoiceRead(BaseModel):
    id: str
    name: str
    provider: str
    gender: str
    style: str
    scenario: str
    status: str
    is_default: Annotated[bool, Field(alias="isDefault")]
    sample_text: Annotated[str, Field(alias="sampleText")]

    model_config = ConfigDict(populate_by_name=True)


class VoiceProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner_name: Annotated[str, Field(alias="ownerName")] = "待授权人"
    scenario: str = "外呼"
    status: str = "待授权"
    authorization_status: Annotated[str, Field(alias="authorizationStatus")] = "待提交"
    sample_count: Annotated[int, Field(alias="sampleCount", ge=0)] = 0
    fallback_voice: Annotated[str, Field(alias="fallbackVoice")] = "标准AI音色"
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
