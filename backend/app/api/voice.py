from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.growth import VoiceCloneRecord, VoiceProfile, VoiceSample, VoiceTrainingJob, VoiceUsageRecord
from app.schemas.voice import (
    VoiceCloneRecordRead,
    VoiceOverview,
    VoiceProfileCreate,
    VoiceProfileRead,
    VoiceProfileUpdate,
    VoiceProviderStatusRead,
    VoiceSampleRead,
    SystemVoiceRead,
    VoiceTrainingJobCreate,
    VoiceTrainingJobRead,
    VoiceUsageRecordRead,
)
from app.services.dashscope_voice import (
    VoiceProviderError,
    create_dashscope_voice_clone,
    dashscope_provider_status,
)

router = APIRouter()

SYSTEM_VOICES = [
    {
        "id": "system_standard_warm",
        "name": "标准AI音色",
        "provider": "模型内置TTS",
        "gender": "通用",
        "style": "稳重清晰",
        "scenario": "默认外呼",
        "status": "可用",
        "isDefault": True,
        "sampleText": "您好，我是本地生活服务顾问，想和您确认一下是否方便了解视频号团购获客。",
    },
    {
        "id": "system_female_service",
        "name": "温和女声",
        "provider": "模型内置TTS",
        "gender": "女声",
        "style": "亲和客服",
        "scenario": "首次触达、回访",
        "status": "可用",
        "isDefault": False,
        "sampleText": "您好，看到您店铺适合做本地生活曝光，我先简单介绍一下合作方式。",
    },
    {
        "id": "system_male_business",
        "name": "商务男声",
        "provider": "模型内置TTS",
        "gender": "男声",
        "style": "商务简洁",
        "scenario": "方案说明、资料跟进",
        "status": "可用",
        "isDefault": False,
        "sampleText": "我们可以先从基础方案试跑，再根据实际咨询量决定是否加大投放。",
    },
]

DEFAULT_SYSTEM_VOICE = next(voice for voice in SYSTEM_VOICES if voice["isDefault"])
ALLOWED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".webm"}
MOCK_VOICE_ENGINE = "mock-voice-engine"
DEFAULT_REAL_CLONE_ENGINE = "真实声音克隆服务"


def _is_system_profile(profile: VoiceProfile) -> bool:
    return profile.authorization_status == "系统内置" or profile.owner_name == "系统"


def _clone_profile_filter():
    return and_(VoiceProfile.authorization_status != "系统内置", VoiceProfile.owner_name != "系统")


def _voice_sample_root() -> Path:
    root = Path(settings.voice_sample_storage_root).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_audio_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_AUDIO_SUFFIXES:
        raise HTTPException(status_code=400, detail="请上传 wav、mp3、m4a、aac、ogg、flac 或 webm 录音文件")
    return f"{uuid4().hex}{suffix}"


def _ensure_clone_profile(db: Session, profile_id: str) -> VoiceProfile:
    profile = db.get(VoiceProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="声音档案不存在")
    if _is_system_profile(profile):
        raise HTTPException(status_code=400, detail="系统内置音色不通过声音档案维护")
    return profile


def _usable_sample_count(db: Session, profile_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(VoiceSample)
            .where(VoiceSample.profile_id == profile_id, VoiceSample.quality_status == "可用")
        )
        or 0
    )


def _voice_clone_engine_name() -> str:
    return settings.voice_clone_engine_name.strip() or DEFAULT_REAL_CLONE_ENGINE


def _voice_clone_training_ready() -> bool:
    return dashscope_provider_status(probe=False).ready


def _voice_clone_status() -> dict[str, str | bool]:
    provider_status = dashscope_provider_status(probe=False)
    if provider_status.ready:
        return {
            "cloneTrainingEnabled": True,
            "cloneEngineName": provider_status.engine_name,
            "cloneEngineStatus": provider_status.status,
            "cloneEngineMessage": provider_status.message,
        }
    return {
        "cloneTrainingEnabled": False,
        "cloneEngineName": provider_status.engine_name,
        "cloneEngineStatus": provider_status.status,
        "cloneEngineMessage": provider_status.message,
    }


def _latest_usable_sample(db: Session, profile_id: str) -> VoiceSample | None:
    return db.scalar(
        select(VoiceSample)
        .where(VoiceSample.profile_id == profile_id, VoiceSample.quality_status == "可用")
        .order_by(VoiceSample.created_at.desc())
    )


def _seed_voice_assets(db: Session) -> None:
    clone_profiles = db.scalar(select(func.count()).select_from(VoiceProfile).where(_clone_profile_filter())) or 0
    if clone_profiles:
        return

    pending = VoiceProfile(
        name="招商顾问克隆音色",
        owner_name="待授权顾问",
        scenario="外呼",
        status="待授权",
        authorization_status="待提交",
        sample_count=0,
        fallback_voice=DEFAULT_SYSTEM_VOICE["name"],
        consent_material="等待上传授权材料和声音样本元数据。",
        risk_note="未授权前不可复刻、不可被任务选择。",
    )
    db.add(pending)
    db.flush()
    db.add(
        VoiceUsageRecord(
            profile_id=None,
            merchant_name="模拟商家",
            scenario="外呼",
            result=f"使用系统内置音色：{DEFAULT_SYSTEM_VOICE['name']}",
            fallback_used=False,
        )
    )
    db.commit()


@router.get("/overview", response_model=VoiceOverview)
def voice_overview(db: Session = Depends(get_db)) -> dict[str, int]:
    _seed_voice_assets(db)
    profiles = db.scalar(select(func.count()).select_from(VoiceProfile).where(_clone_profile_filter())) or 0
    usable = (
        db.scalar(select(func.count()).select_from(VoiceProfile).where(_clone_profile_filter(), VoiceProfile.status == "可用"))
        or 0
    )
    pending = (
        db.scalar(
            select(func.count())
            .select_from(VoiceProfile)
            .where(_clone_profile_filter(), VoiceProfile.authorization_status.in_(["待提交", "待审核"]))
        )
        or 0
    )
    jobs = (
        db.scalar(
            select(func.count())
            .select_from(VoiceCloneRecord)
            .join(VoiceProfile, VoiceCloneRecord.profile_id == VoiceProfile.id)
            .where(_clone_profile_filter(), VoiceCloneRecord.engine != MOCK_VOICE_ENGINE)
        )
        or 0
    )
    usage = db.scalar(select(func.count()).select_from(VoiceUsageRecord)) or 0
    fallback = db.scalar(select(func.count()).select_from(VoiceUsageRecord).where(VoiceUsageRecord.fallback_used.is_(True))) or 0
    return {
        "profiles": int(profiles),
        "usableProfiles": int(usable),
        "pendingAuthorization": int(pending),
        "trainingJobs": int(jobs),
        "usageRecords": int(usage),
        "fallbackUsage": int(fallback),
        "systemVoices": len(SYSTEM_VOICES),
        "defaultVoice": DEFAULT_SYSTEM_VOICE["name"],
        **_voice_clone_status(),
    }


@router.get("/system-voices", response_model=list[SystemVoiceRead])
def list_system_voices() -> list[dict[str, str | bool]]:
    return SYSTEM_VOICES


@router.get("/provider/status", response_model=VoiceProviderStatusRead)
def voice_provider_status(probe: bool = Query(False)) -> object:
    return dashscope_provider_status(probe=probe)


@router.get("/profiles", response_model=list[VoiceProfileRead])
def list_voice_profiles(db: Session = Depends(get_db)) -> list[VoiceProfile]:
    _seed_voice_assets(db)
    return list(db.scalars(select(VoiceProfile).where(_clone_profile_filter()).order_by(VoiceProfile.created_at.desc())).all())


@router.post("/profiles", response_model=VoiceProfileRead)
def create_voice_profile(payload: VoiceProfileCreate, db: Session = Depends(get_db)) -> VoiceProfile:
    profile = VoiceProfile(**payload.model_dump(by_alias=False))
    if profile.authorization_status == "系统内置":
        raise HTTPException(status_code=400, detail="系统内置音色不通过声音档案创建")
    if profile.authorization_status != "授权通过":
        profile.status = "待授权"
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.patch("/profiles/{profile_id}", response_model=VoiceProfileRead)
def update_voice_profile(profile_id: str, payload: VoiceProfileUpdate, db: Session = Depends(get_db)) -> VoiceProfile:
    profile = _ensure_clone_profile(db, profile_id)
    for field, value in payload.model_dump(exclude_unset=True, by_alias=False).items():
        setattr(profile, field, value)
    if profile.authorization_status in {"授权撤回", "已拒绝"}:
        profile.status = "已停用"
    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/samples", response_model=list[VoiceSampleRead])
def list_voice_samples(db: Session = Depends(get_db)) -> list[VoiceSample]:
    _seed_voice_assets(db)
    return list(
        db.scalars(
            select(VoiceSample)
            .join(VoiceProfile, VoiceSample.profile_id == VoiceProfile.id)
            .where(_clone_profile_filter())
            .order_by(VoiceSample.created_at.desc())
        ).all()
    )


@router.get("/profiles/{profile_id}/samples", response_model=list[VoiceSampleRead])
def list_profile_voice_samples(profile_id: str, db: Session = Depends(get_db)) -> list[VoiceSample]:
    _ensure_clone_profile(db, profile_id)
    return list(
        db.scalars(select(VoiceSample).where(VoiceSample.profile_id == profile_id).order_by(VoiceSample.created_at.desc())).all()
    )


@router.get("/samples/{sample_id}/file")
def read_voice_sample_file(sample_id: str, db: Session = Depends(get_db)) -> FileResponse:
    sample = db.get(VoiceSample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="录音样本不存在")
    _ensure_clone_profile(db, sample.profile_id)
    path = Path(sample.storage_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="录音文件不存在")
    return FileResponse(path, media_type=sample.content_type or "audio/*", filename=sample.file_name)


@router.post("/profiles/{profile_id}/samples", response_model=VoiceSampleRead)
def upload_voice_sample(
    profile_id: str,
    file: UploadFile = File(...),
    uploaded_by: str = Form("客户"),
    duration_seconds: int = Form(0),
    transcript: str = Form(""),
    db: Session = Depends(get_db),
) -> VoiceSample:
    profile = _ensure_clone_profile(db, profile_id)
    safe_filename = _safe_audio_filename(file.filename or "voice-sample.wav")
    profile_dir = _voice_sample_root() / profile.id
    profile_dir.mkdir(parents=True, exist_ok=True)
    target = profile_dir / safe_filename

    size = 0
    with target.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            output.write(chunk)

    if size <= 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="录音文件为空，请重新上传")

    quality_status = "可用" if (file.content_type or "").startswith("audio/") else "待复核"
    sample = VoiceSample(
        profile_id=profile.id,
        file_name=file.filename or safe_filename,
        content_type=file.content_type or "audio/*",
        storage_path=str(target),
        size_bytes=size,
        duration_seconds=max(duration_seconds, 0),
        quality_status=quality_status,
        transcript=transcript,
        uploaded_by=uploaded_by or profile.owner_name or "客户",
    )
    db.add(sample)
    db.flush()

    profile.sample_count = _usable_sample_count(db, profile.id)
    if profile.authorization_status == "授权通过" and profile.status not in {"复刻中", "可用"}:
        profile.status = "可复刻"
    elif profile.authorization_status != "授权通过":
        profile.status = "待授权"
    profile.consent_material = profile.consent_material or "已上传授权录音样本，等待补充授权说明。"
    profile.risk_note = f"已上传 {profile.sample_count} 条可用录音样本；训练前仍需授权通过。"
    profile.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(sample)
    return sample


@router.get("/training-jobs", response_model=list[VoiceTrainingJobRead])
def list_training_jobs(db: Session = Depends(get_db)) -> list[VoiceTrainingJob]:
    _seed_voice_assets(db)
    return list(
        db.scalars(
            select(VoiceTrainingJob)
            .join(VoiceProfile, VoiceTrainingJob.profile_id == VoiceProfile.id)
            .join(VoiceCloneRecord, VoiceCloneRecord.training_job_id == VoiceTrainingJob.id)
            .where(_clone_profile_filter(), VoiceTrainingJob.engine != MOCK_VOICE_ENGINE)
            .order_by(VoiceTrainingJob.created_at.desc())
        ).all()
    )


@router.post("/profiles/{profile_id}/training-jobs", response_model=VoiceTrainingJobRead)
def create_training_job(profile_id: str, payload: VoiceTrainingJobCreate, db: Session = Depends(get_db)) -> VoiceTrainingJob:
    profile = _ensure_clone_profile(db, profile_id)
    if profile.authorization_status != "授权通过":
        raise HTTPException(status_code=400, detail="声音档案未授权，不能进入训练")
    usable_samples = _usable_sample_count(db, profile.id)
    if usable_samples <= 0:
        raise HTTPException(status_code=400, detail="请先上传至少 1 条可用录音样本，再生成复刻音色")
    if not _voice_clone_training_ready():
        raise HTTPException(status_code=400, detail="真实声音克隆服务未接入，不能生成复刻音色。请先配置 DashScope/CosyVoice 后再提交。")
    sample = _latest_usable_sample(db, profile.id)
    if not sample:
        raise HTTPException(status_code=400, detail="请先上传至少 1 条可用录音样本，再创建复刻音色")
    sample_seconds = (
        db.scalar(
            select(func.coalesce(func.sum(VoiceSample.duration_seconds), 0)).where(
                VoiceSample.profile_id == profile.id, VoiceSample.quality_status == "可用"
            )
        )
        or 0
    )
    sample_minutes = max(payload.sample_minutes, max(1, int(sample_seconds // 60) if sample_seconds else usable_samples))
    job = VoiceTrainingJob(
        profile_id=profile.id,
        status="生成中",
        progress=10,
        engine=_voice_clone_engine_name(),
        sample_minutes=sample_minutes,
        message=payload.message or "正在提交 DashScope/CosyVoice 生成复刻音色。",
        started_at=datetime.utcnow(),
        finished_at=None,
    )
    db.add(job)
    db.flush()
    clone_record = VoiceCloneRecord(
        profile_id=profile.id,
        training_job_id=job.id,
        cloned_voice_name=profile.name,
        engine=job.engine,
        status=job.status,
        sample_count=usable_samples,
        sample_minutes=job.sample_minutes,
        result=job.message,
    )
    db.add(clone_record)
    db.flush()
    profile.status = "复刻中"
    profile.sample_count = usable_samples
    profile.updated_at = datetime.utcnow()

    try:
        clone_result = create_dashscope_voice_clone(profile, sample, clone_record.id)
    except VoiceProviderError as exc:
        job.status = "失败"
        job.progress = 100
        job.message = str(exc)
        job.finished_at = datetime.utcnow()
        clone_record.status = "失败"
        clone_record.result = str(exc)
        clone_record.completed_at = datetime.utcnow()
        profile.status = "复刻失败"
        profile.risk_note = str(exc)
        profile.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    job.status = "已完成"
    job.progress = 100
    job.message = clone_result.message
    job.finished_at = datetime.utcnow()
    clone_record.status = "可用"
    clone_record.external_voice_id = clone_result.external_voice_id
    clone_record.preview_audio_path = clone_result.preview_audio_path
    clone_record.result = clone_result.message
    clone_record.completed_at = datetime.utcnow()
    profile.status = "可用"
    profile.risk_note = f"DashScope/CosyVoice 音色已生成，可用于试听和后续外呼音频合成。voice_id={clone_result.external_voice_id}"
    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job


@router.get("/clone-records", response_model=list[VoiceCloneRecordRead])
def list_voice_clone_records(db: Session = Depends(get_db)) -> list[VoiceCloneRecord]:
    _seed_voice_assets(db)
    return list(
        db.scalars(
            select(VoiceCloneRecord)
            .join(VoiceProfile, VoiceCloneRecord.profile_id == VoiceProfile.id)
            .where(_clone_profile_filter(), VoiceCloneRecord.engine != MOCK_VOICE_ENGINE)
            .order_by(VoiceCloneRecord.created_at.desc())
        ).all()
    )


@router.get("/clone-records/{record_id}/preview")
def read_voice_clone_preview(record_id: str, db: Session = Depends(get_db)) -> FileResponse:
    record = db.get(VoiceCloneRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="克隆记录不存在")
    _ensure_clone_profile(db, record.profile_id)
    if not record.preview_audio_path:
        raise HTTPException(status_code=404, detail="暂无试听音频")
    path = Path(record.preview_audio_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="试听音频文件不存在")
    return FileResponse(path, media_type="audio/wav", filename=f"{record.cloned_voice_name}.wav")


@router.get("/usage-records", response_model=list[VoiceUsageRecordRead])
def list_voice_usage_records(db: Session = Depends(get_db)) -> list[VoiceUsageRecord]:
    _seed_voice_assets(db)
    return list(db.scalars(select(VoiceUsageRecord).order_by(VoiceUsageRecord.created_at.desc())).all())
