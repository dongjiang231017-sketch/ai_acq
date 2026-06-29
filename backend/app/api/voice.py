from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.growth import VoiceProfile, VoiceTrainingJob, VoiceUsageRecord
from app.schemas.voice import (
    VoiceOverview,
    VoiceProfileCreate,
    VoiceProfileRead,
    VoiceProfileUpdate,
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


def _is_system_profile(profile: VoiceProfile) -> bool:
    return profile.authorization_status == "系统内置" or profile.owner_name == "系统"


def _clone_profile_filter():
    return and_(VoiceProfile.authorization_status != "系统内置", VoiceProfile.owner_name != "系统")


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
            .select_from(VoiceTrainingJob)
            .join(VoiceProfile, VoiceTrainingJob.profile_id == VoiceProfile.id)
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
    profile = db.get(VoiceProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="声音档案不存在")
    if _is_system_profile(profile):
        raise HTTPException(status_code=400, detail="系统内置音色不通过声音档案维护")
    for field, value in payload.model_dump(exclude_unset=True, by_alias=False).items():
        setattr(profile, field, value)
    if profile.authorization_status in {"授权撤回", "已拒绝"}:
        profile.status = "已停用"
    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/training-jobs", response_model=list[VoiceTrainingJobRead])
def list_training_jobs(db: Session = Depends(get_db)) -> list[VoiceTrainingJob]:
    _seed_voice_assets(db)
    return list(
        db.scalars(
            select(VoiceTrainingJob)
            .join(VoiceProfile, VoiceTrainingJob.profile_id == VoiceProfile.id)
            .where(_clone_profile_filter())
            .order_by(VoiceTrainingJob.created_at.desc())
        ).all()
    )


@router.post("/profiles/{profile_id}/training-jobs", response_model=VoiceTrainingJobRead)
def create_training_job(profile_id: str, payload: VoiceTrainingJobCreate, db: Session = Depends(get_db)) -> VoiceTrainingJob:
    profile = db.get(VoiceProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="声音档案不存在")
    if _is_system_profile(profile):
        raise HTTPException(status_code=400, detail="系统内置音色无需克隆训练")
    if profile.authorization_status != "授权通过":
        raise HTTPException(status_code=400, detail="声音档案未授权，不能进入训练")
    job = VoiceTrainingJob(
        profile_id=profile.id,
        status="排队中",
        progress=0,
        engine=payload.engine,
        sample_minutes=payload.sample_minutes,
        message=payload.message or "训练任务已创建；真实克隆服务仍需单独接入安全门。",
        started_at=None,
        finished_at=None,
    )
    db.add(job)
    if profile.authorization_status == "授权通过":
        profile.status = "训练中"
    db.commit()
    db.refresh(job)
    return job


@router.get("/usage-records", response_model=list[VoiceUsageRecordRead])
def list_voice_usage_records(db: Session = Depends(get_db)) -> list[VoiceUsageRecord]:
    _seed_voice_assets(db)
    return list(db.scalars(select(VoiceUsageRecord).order_by(VoiceUsageRecord.created_at.desc())).all())
