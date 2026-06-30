from datetime import datetime
from pathlib import Path
import re
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
    SystemVoicePreviewRead,
    VoiceTrainingJobCreate,
    VoiceTrainingJobRead,
    VoiceUsageRecordRead,
)
from app.services.dashscope_voice import (
    VoiceProviderError,
    create_dashscope_voice_clone,
    dashscope_provider_status,
    synthesize_qwen_system_voice_preview,
)

router = APIRouter()

QWEN_TTS_PRESET_VOICES = [
    ("Cherry", "芊悦", "阳光积极、亲切自然小姐姐（女性）", "女声", "自然对话", "客服外呼"),
    ("Serena", "苏瑶", "温柔小姐姐（女性）", "女声", "自然对话", "客服外呼"),
    ("Ethan", "晨煦", "标准普通话，带部分北方口音。阳光、温暖、活力、朝气（男性）", "男声", "标准普通话", "默认外呼"),
    ("Chelsie", "千雪", "二次元虚拟女友（女性）", "女声", "自然对话", "客服外呼"),
    ("Momo", "茉兔", "撒娇搞怪，逗你开心（女性）", "女声", "轻松亲和", "轻松互动"),
    ("Vivian", "十三", "拽拽的、可爱的小暴躁（女性）", "女声", "轻松亲和", "轻松互动"),
    ("Moon", "月白", "率性帅气的月白（男性）", "男声", "自然对话", "客服外呼"),
    ("Maia", "四月", "知性与温柔的碰撞（女性）", "女声", "自然对话", "客服外呼"),
    ("Kai", "凯", "耳朵的一场 SPA（男性）", "男声", "自然对话", "客服外呼"),
    ("Nofish", "不吃鱼", "不会翘舌音的设计师（男性）", "男声", "自然对话", "客服外呼"),
    ("Bella", "萌宝", "喝酒不打醉拳的小萝莉（女性）", "女声", "轻松亲和", "轻松互动"),
    ("Jennifer", "詹妮弗", "品牌级、电影质感般美语女声（女性）", "女声", "多语种", "多语种触达"),
    ("Ryan", "甜茶", "节奏拉满，戏感炸裂，真实与张力共舞（男性）", "男声", "自然对话", "客服外呼"),
    ("Katerina", "卡捷琳娜", "御姐音色，韵律回味十足（女性）", "女声", "多语种", "多语种触达"),
    ("Aiden", "艾登", "精通厨艺的美语大男孩（男性）", "男声", "多语种", "多语种触达"),
    ("Eldric Sage", "沧明子", "沉稳睿智的老者，沧桑如松却心明如镜（男性）", "男声", "沉稳叙事", "方案说明"),
    ("Mia", "乖小妹", "温顺如春水，乖巧如初雪（女性）", "女声", "自然对话", "客服外呼"),
    ("Mochi", "沙小弥", "聪明伶俐的小大人，童真未泯却早慧如禅（男性）", "男声", "轻松亲和", "轻松互动"),
    ("Bellona", "燕铮莺", "声音洪亮，吐字清晰，人物鲜活，听得人热血沸腾；金戈铁马入梦来，字正腔圆间尽显千面人声的江湖（女性）", "女声", "自然对话", "客服外呼"),
    ("Vincent", "田叔", "一口独特的沙哑烟嗓，一开口便道尽了千军万马与江湖豪情（男性）", "男声", "自然对话", "客服外呼"),
    ("Bunny", "萌小姬", "“萌属性”爆棚的小萝莉（女性）", "女声", "轻松亲和", "轻松互动"),
    ("Neil", "阿闻", "平直的基线语调，字正腔圆的咬字发音，这就是最专业的新闻主持人（男性）", "男声", "专业播报", "新闻播报"),
    ("Elias", "墨讲师", "既保持学科严谨性，又通过叙事技巧将复杂知识转化为可消化的认知模块（女性）", "女声", "知识讲解", "内容讲解"),
    ("Arthur", "徐大爷", "被岁月和旱烟浸泡过的质朴嗓音，不疾不徐地摇开了满村的奇闻异事（男性）", "男声", "自然对话", "客服外呼"),
    ("Nini", "邻家妹妹", "糯米糍一样又软又黏的嗓音，那一声声拉长了的“哥哥”，甜得能把人的骨头都叫酥了（女性）", "女声", "自然对话", "客服外呼"),
    ("Seren", "小婉", "温和舒缓的声线，助你更快地进入睡眠，晚安，好梦（女性）", "女声", "自然对话", "客服外呼"),
    ("Pip", "顽屁小孩", "调皮捣蛋却充满童真的他来了，这是你记忆中的小新吗（男性）", "男声", "自然对话", "客服外呼"),
    ("Stella", "少女阿月", "平时是甜到发腻的迷糊少女音，但在喊出“代表月亮消灭你”时，瞬间充满不容置疑的爱与正义（女性）", "女声", "自然对话", "客服外呼"),
    ("Bodega", "博德加", "热情的西班牙大叔（男性）", "男声", "多语种", "多语种触达"),
    ("Sonrisa", "索尼莎", "热情开朗的拉美大姐（女性）", "女声", "多语种", "多语种触达"),
    ("Alek", "阿列克", "一开口，是战斗民族的冷，也是毛呢大衣下的暖（男性）", "男声", "多语种", "多语种触达"),
    ("Dolce", "多尔切", "慵懒的意大利大叔（男性）", "男声", "多语种", "多语种触达"),
    ("Sohee", "素熙", "温柔开朗，情绪丰富的韩国欧尼（女性）", "女声", "多语种", "多语种触达"),
    ("Ono Anna", "小野杏", "鬼灵精怪的青梅竹马（女性）", "女声", "多语种", "多语种触达"),
    ("Lenn", "莱恩", "理性是底色，叛逆藏在细节里——穿西装也听后朋克的德国青年（男性）", "男声", "多语种", "多语种触达"),
    ("Emilien", "埃米尔安", "浪漫的法国大哥哥（男性）", "男声", "多语种", "多语种触达"),
    ("Andre", "安德雷", "声音磁性，自然舒服、沉稳男生（男性）", "男声", "沉稳叙事", "方案说明"),
    ("Radio Gol", "拉迪奥·戈尔", "足球诗人 Rádio Gol！今天我要用名字为你们解说足球（男性）", "男声", "多语种", "多语种触达"),
    ("Jada", "上海-阿珍", "风风火火的沪上阿姐（女性）", "女声", "地方方言", "本地触达"),
    ("Dylan", "北京-晓东", "北京胡同里长大的少年（男性）", "男声", "地方方言", "本地触达"),
    ("Li", "南京-老李", "耐心的瑜伽老师（男性）", "男声", "地方方言", "本地触达"),
    ("Marcus", "陕西-秦川", "面宽话短，心实声沉——老陕的味道（男性）", "男声", "地方方言", "本地触达"),
    ("Roy", "闽南-阿杰", "诙谐直爽、市井活泼的台湾哥仔形象（男性）", "男声", "地方方言", "本地触达"),
    ("Peter", "天津-李彼得", "天津相声，专业捧哏（男性）", "男声", "地方方言", "本地触达"),
    ("Sunny", "四川-晴儿", "甜到你心里的川妹子（女性）", "女声", "地方方言", "本地触达"),
    ("Eric", "四川-程川", "一个跳脱市井的四川成都男子（男性）", "男声", "地方方言", "本地触达"),
    ("Rocky", "粤语-阿强", "幽默风趣的阿强，在线陪聊（男性）", "男声", "地方方言", "本地触达"),
    ("Kiki", "粤语-阿清", "甜美的港妹闺蜜（女性）", "女声", "地方方言", "本地触达"),
]


def _qwen_voice_id(voice_param: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", voice_param.lower()).strip("_")
    return f"qwen_tts_{normalized}"


def _build_system_voice(
    voice_param: str,
    name: str,
    description: str,
    gender: str,
    style: str,
    scenario: str,
) -> dict[str, str | bool]:
    return {
        "id": _qwen_voice_id(voice_param),
        "name": f"{name}（{voice_param}）",
        "provider": "Qwen-TTS",
        "voiceParam": voice_param,
        "gender": gender,
        "style": style,
        "scenario": scenario,
        "status": "可用",
        "isDefault": voice_param == "Ethan",
        "sampleText": description,
    }


SYSTEM_VOICES = [_build_system_voice(*voice) for voice in QWEN_TTS_PRESET_VOICES]

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


@router.post("/system-voices/{voice_id}/preview", response_model=SystemVoicePreviewRead)
def preview_system_voice(voice_id: str) -> dict[str, str]:
    voice = next((item for item in SYSTEM_VOICES if item["id"] == voice_id), None)
    if not voice:
        raise HTTPException(status_code=404, detail="系统音色不存在")

    preview_text = settings.dashscope_system_tts_preview_text.strip() or str(voice["sampleText"])
    try:
        result = synthesize_qwen_system_voice_preview(str(voice["voiceParam"]), preview_text)
    except VoiceProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "voiceId": str(voice["id"]),
        "voiceParam": str(voice["voiceParam"]),
        "audioUrl": result.audio_url,
        "previewText": preview_text,
        "message": result.message,
    }


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
    provider_status = dashscope_provider_status(probe=False)
    if not provider_status.ready:
        missing_public_url = "" if provider_status.sample_public_base_url_configured else " 还需要配置可公网访问的 VOICE_SAMPLE_PUBLIC_BASE_URL。"
        raise HTTPException(
            status_code=400,
            detail=f"{provider_status.message}{missing_public_url}",
        )
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
