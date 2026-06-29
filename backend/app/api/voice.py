from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.growth import VoiceProfile, VoiceTrainingJob, VoiceUsageRecord
from app.schemas.voice import (
    VoiceOverview,
    VoiceProfileCreate,
    VoiceProfileRead,
    VoiceProfileUpdate,
    VoiceTrainingJobCreate,
    VoiceTrainingJobRead,
    VoiceUsageRecordRead,
)

router = APIRouter()


def _seed_voice_assets(db: Session) -> None:
    profiles = db.scalar(select(func.count()).select_from(VoiceProfile)) or 0
    if profiles:
        return

    standard = VoiceProfile(
        name="标准AI音色",
        owner_name="系统",
        scenario="外呼",
        status="可用",
        authorization_status="系统内置",
        sample_count=0,
        fallback_voice="标准AI音色",
        consent_material="系统内置安全音色，无真人克隆样本。",
        risk_note="可作为所有未授权音色的回退。",
    )
    pending = VoiceProfile(
        name="招商顾问授权音色",
        owner_name="待授权顾问",
        scenario="外呼",
        status="待授权",
        authorization_status="待提交",
        sample_count=0,
        fallback_voice="标准AI音色",
        consent_material="等待上传授权材料和样本元数据。",
        risk_note="未授权前不可训练、不可被任务选择。",
    )
    db.add_all([standard, pending])
    db.flush()
    db.add(
        VoiceUsageRecord(
            profile_id=standard.id,
            merchant_name="模拟商家",
            scenario="外呼",
            result="默认安全音色模拟使用",
            fallback_used=False,
        )
    )
    db.commit()


@router.get("/overview", response_model=VoiceOverview)
def voice_overview(db: Session = Depends(get_db)) -> dict[str, int]:
    _seed_voice_assets(db)
    profiles = db.scalar(select(func.count()).select_from(VoiceProfile)) or 0
    usable = db.scalar(select(func.count()).select_from(VoiceProfile).where(VoiceProfile.status == "可用")) or 0
    pending = db.scalar(select(func.count()).select_from(VoiceProfile).where(VoiceProfile.authorization_status.in_(["待提交", "待审核"]))) or 0
    jobs = db.scalar(select(func.count()).select_from(VoiceTrainingJob)) or 0
    usage = db.scalar(select(func.count()).select_from(VoiceUsageRecord)) or 0
    fallback = db.scalar(select(func.count()).select_from(VoiceUsageRecord).where(VoiceUsageRecord.fallback_used.is_(True))) or 0
    return {
        "profiles": int(profiles),
        "usableProfiles": int(usable),
        "pendingAuthorization": int(pending),
        "trainingJobs": int(jobs),
        "usageRecords": int(usage),
        "fallbackUsage": int(fallback),
    }


@router.get("/profiles", response_model=list[VoiceProfileRead])
def list_voice_profiles(db: Session = Depends(get_db)) -> list[VoiceProfile]:
    _seed_voice_assets(db)
    return list(db.scalars(select(VoiceProfile).order_by(VoiceProfile.created_at.desc())).all())


@router.post("/profiles", response_model=VoiceProfileRead)
def create_voice_profile(payload: VoiceProfileCreate, db: Session = Depends(get_db)) -> VoiceProfile:
    profile = VoiceProfile(**payload.model_dump(by_alias=False))
    if profile.authorization_status not in {"授权通过", "系统内置"}:
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
    return list(db.scalars(select(VoiceTrainingJob).order_by(VoiceTrainingJob.created_at.desc())).all())


@router.post("/profiles/{profile_id}/training-jobs", response_model=VoiceTrainingJobRead)
def create_training_job(profile_id: str, payload: VoiceTrainingJobCreate, db: Session = Depends(get_db)) -> VoiceTrainingJob:
    profile = db.get(VoiceProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="声音档案不存在")
    if profile.authorization_status not in {"授权通过", "系统内置"}:
        raise HTTPException(status_code=400, detail="声音档案未授权，不能进入训练")
    job = VoiceTrainingJob(
        profile_id=profile.id,
        status="训练完成" if profile.authorization_status == "系统内置" else "排队中",
        progress=100 if profile.authorization_status == "系统内置" else 0,
        engine=payload.engine,
        sample_minutes=payload.sample_minutes,
        message=payload.message or "训练任务已创建；真实克隆服务仍需单独接入安全门。",
        started_at=datetime.utcnow() if profile.authorization_status == "系统内置" else None,
        finished_at=datetime.utcnow() if profile.authorization_status == "系统内置" else None,
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
