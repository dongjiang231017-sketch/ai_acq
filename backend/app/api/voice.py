from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
    VoiceSampleRead,
    SystemVoiceRead,
    VoiceTrainingJobCreate,
    VoiceTrainingJobRead,
    VoiceUsageRecordRead,
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
        risk_note="未授权前不可训练、不可被任务选择。",
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
            .where(_clone_profile_filter())
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
    }


@router.get("/system-voices", response_model=list[SystemVoiceRead])
def list_system_voices() -> list[dict[str, str | bool]]:
    return SYSTEM_VOICES


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
    if profile.authorization_status == "授权通过" and profile.status not in {"训练中", "可用"}:
        profile.status = "可训练"
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
            .where(_clone_profile_filter())
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
        raise HTTPException(status_code=400, detail="请先上传至少 1 条可用录音样本，再创建克隆训练")
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
        status="排队中",
        progress=0,
        engine=payload.engine,
        sample_minutes=sample_minutes,
        message=payload.message or "克隆训练任务已创建；真实克隆服务接入前保留人工复核安全门。",
        started_at=None,
        finished_at=None,
    )
    db.add(job)
    db.flush()
    db.add(
        VoiceCloneRecord(
            profile_id=profile.id,
            training_job_id=job.id,
            cloned_voice_name=profile.name,
            engine=job.engine,
            status=job.status,
            sample_count=usable_samples,
            sample_minutes=job.sample_minutes,
            result=job.message,
        )
    )
    profile.status = "训练中"
    profile.sample_count = usable_samples
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
            .where(_clone_profile_filter())
            .order_by(VoiceCloneRecord.created_at.desc())
        ).all()
    )


@router.get("/usage-records", response_model=list[VoiceUsageRecordRead])
def list_voice_usage_records(db: Session = Depends(get_db)) -> list[VoiceUsageRecord]:
    _seed_voice_assets(db)
    return list(db.scalars(select(VoiceUsageRecord).order_by(VoiceUsageRecord.created_at.desc())).all())
