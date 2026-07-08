from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.operations import SystemAuditLog, SystemSetting
from app.schemas.system_settings import (
    SettingsOverview,
    SystemAuditLogRead,
    SystemSettingRead,
    SystemSettingUpdate,
)

router = APIRouter()

GROUP_LABELS = {
    "telephony": "电话线路",
    "dm": "平台账号",
    "model": "模型API",
    "permissions": "权限角色",
    "compliance": "合规审计",
}

CLIENT_GROUP_LABELS = {
    "telephony": "电话线路",
    "dm": "平台账号",
    "compliance": "合规保护",
}

CLIENT_VISIBLE_ITEMS = {
    ("telephony", "asterisk_deployment_mode"),
    ("telephony", "gateway_mode"),
    ("telephony", "queue_enabled"),
    ("telephony", "trunk_name"),
    ("dm", "gateway_mode"),
    ("dm", "live_send_enabled"),
    ("dm", "queue_enabled"),
    ("compliance", "dnc_enabled"),
    ("compliance", "refusal_stop_enabled"),
}


def _bool_value(value: bool) -> str:
    return "true" if value else "false"


def _status_for_setting_value(group_key: str, item_key: str, value: str) -> str:
    if group_key == "model":
        if item_key.endswith("_api_key"):
            return "已配置" if value.strip() else "待配置"
        if item_key.endswith("_enabled") or item_key.endswith("_first_sentence"):
            return "已启用" if value == "true" else "未启用"
        return "已配置" if value.strip() else "待配置"
    if item_key == "asterisk_deployment_mode":
        return "云端托管" if value == "server" else "本机内置"
    if item_key == "gateway_mode":
        return "模拟模式" if value == "simulator" else "已启用"
    if item_key in {"queue_enabled", "dnc_enabled", "refusal_stop_enabled"}:
        return "已启用" if value == "true" else "未启用"
    if item_key == "live_send_enabled":
        return "已启用" if value == "true" else "受控"
    if item_key == "trunk_name":
        return "已配置" if value.strip() else "待配置"
    return "已启用" if value else "待配置"


def _default_settings() -> list[dict[str, object]]:
    return [
        {
            "group_key": "telephony",
            "item_key": "asterisk_deployment_mode",
            "label": "Asterisk 部署位置",
            "value": settings.asterisk_deployment_mode,
            "value_type": "select:server,client",
            "status": "云端托管" if settings.asterisk_deployment_mode == "server" else "本机内置",
            "description": "交付默认使用服务器 Asterisk；客户端内置 Asterisk 仅作为本地备选方案。",
        },
        {
            "group_key": "telephony",
            "item_key": "gateway_mode",
            "label": "电话网关模式",
            "value": settings.telephony_gateway_mode,
            "value_type": "select:simulator,asterisk",
            "status": "模拟模式" if settings.telephony_gateway_mode == "simulator" else "已启用",
            "description": "控制外呼任务使用模拟网关还是真实 Asterisk/线路网关。",
        },
        {
            "group_key": "telephony",
            "item_key": "queue_enabled",
            "label": "外呼队列",
            "value": _bool_value(settings.outbound_queue_enabled),
            "value_type": "boolean",
            "status": "已启用" if settings.outbound_queue_enabled else "未启用",
            "description": "启用后外呼任务会进入 Redis 队列，由 worker 消费。",
        },
        {
            "group_key": "telephony",
            "item_key": "trunk_name",
            "label": "线路中继名称",
            "value": settings.asterisk_trunk_name,
            "value_type": "text",
            "status": "已配置" if settings.asterisk_trunk_name else "待配置",
            "description": "真实外呼接入时使用的 Asterisk trunk 别名。",
        },
        {
            "group_key": "dm",
            "item_key": "gateway_mode",
            "label": "私信发送模式",
            "value": settings.dm_gateway_mode,
            "value_type": "select:simulator,browser",
            "status": "模拟模式" if settings.dm_gateway_mode == "simulator" else "已启用",
            "description": "控制平台私信使用模拟器还是浏览器自动化适配器。",
        },
        {
            "group_key": "dm",
            "item_key": "live_send_enabled",
            "label": "真实发送开关",
            "value": _bool_value(settings.dm_browser_live_send_enabled),
            "value_type": "boolean",
            "status": "受控" if not settings.dm_browser_live_send_enabled else "已启用",
            "description": "真实发送属于高风险动作，默认关闭，仅在人工确认后开启。",
        },
        {
            "group_key": "dm",
            "item_key": "queue_enabled",
            "label": "私信任务队列",
            "value": _bool_value(settings.dm_queue_enabled),
            "value_type": "boolean",
            "status": "已启用" if settings.dm_queue_enabled else "未启用",
            "description": "启用后私信任务会进入 Redis 队列，便于限速和隔离执行。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_api_key",
            "label": "DashScope API Key",
            "value": settings.dashscope_api_key,
            "value_type": "text",
            "status": "已配置" if settings.dashscope_api_key else "待配置",
            "description": "阿里百炼 DashScope Key，用于 Qwen Omni、Paraformer、Qwen-TTS 和 CosyVoice。",
            "sensitive": True,
        },
        {
            "group_key": "model",
            "item_key": "dashscope_workspace",
            "label": "DashScope Workspace",
            "value": settings.dashscope_workspace,
            "value_type": "text",
            "status": "已配置" if settings.dashscope_workspace else "可选",
            "description": "DashScope workspace，可为空；有独立 workspace 时填写。",
        },
        {
            "group_key": "model",
            "item_key": "deepseek_api_key",
            "label": "DeepSeek API Key",
            "value": settings.deepseek_api_key,
            "value_type": "text",
            "status": "已配置" if settings.deepseek_api_key else "待配置",
            "description": "DeepSeek Key，用于低成本分段 Pipeline 的复杂问题短回复。",
            "sensitive": True,
        },
        {
            "group_key": "model",
            "item_key": "deepseek_base_url",
            "label": "DeepSeek Base URL",
            "value": settings.deepseek_base_url,
            "value_type": "text",
            "status": "已配置" if settings.deepseek_base_url else "待配置",
            "description": "DeepSeek 兼容 Chat Completions 接口地址。",
        },
        {
            "group_key": "model",
            "item_key": "deepseek_chat_model",
            "label": "DeepSeek 对话模型",
            "value": settings.deepseek_chat_model,
            "value_type": "select:deepseek-v4-flash,deepseek-chat,deepseek-reasoner",
            "status": "已配置" if settings.deepseek_chat_model else "待配置",
            "description": "低成本分段 Pipeline 使用的 LLM 模型。",
        },
        {
            "group_key": "model",
            "item_key": "deepseek_timeout_seconds",
            "label": "DeepSeek 超时秒数",
            "value": str(settings.deepseek_timeout_seconds),
            "value_type": "text",
            "status": "已配置",
            "description": "电话实时链路等待 DeepSeek 的最长秒数，建议 1.0-1.5。",
        },
        {
            "group_key": "model",
            "item_key": "deepseek_max_tokens",
            "label": "DeepSeek 最大输出 Token",
            "value": str(settings.deepseek_max_tokens),
            "value_type": "number",
            "status": "已配置",
            "description": "电话回复必须短，建议 60-120。",
        },
        {
            "group_key": "model",
            "item_key": "deepseek_stream_first_sentence",
            "label": "DeepSeek 首句流式返回",
            "value": _bool_value(settings.deepseek_stream_first_sentence),
            "value_type": "boolean",
            "status": "已启用" if settings.deepseek_stream_first_sentence else "未启用",
            "description": "开启后拿到可说首句就返回，降低电话停顿。",
        },
        {
            "group_key": "model",
            "item_key": "realtime_conversation_mode",
            "label": "实时通话路线",
            "value": settings.realtime_conversation_mode,
            "value_type": "select:livekit,pipeline,omni",
            "status": "已配置",
            "description": "livekit 为正式外呼 Agent 路线；pipeline/omni 保留为 AudioSocket 备用路线。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_omni_realtime_model",
            "label": "Qwen Omni 实时模型",
            "value": settings.dashscope_omni_realtime_model,
            "value_type": "select:qwen3.5-omni-flash-realtime-2026-03-15,qwen-omni-turbo-realtime,qwen3.5-omni-plus-realtime",
            "status": "已配置",
            "description": "Omni 线路使用的端到端实时语音模型。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_omni_realtime_url",
            "label": "Qwen Omni WebSocket URL",
            "value": settings.dashscope_omni_realtime_url,
            "value_type": "text",
            "status": "已配置" if settings.dashscope_omni_realtime_url else "待配置",
            "description": "DashScope Omni Realtime WebSocket 地址。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_omni_realtime_voice",
            "label": "Qwen Omni 系统音色",
            "value": settings.dashscope_omni_realtime_voice,
            "value_type": "text",
            "status": "已配置" if settings.dashscope_omni_realtime_voice else "待配置",
            "description": "Omni 线路默认系统音色。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_omni_input_transcription_model",
            "label": "Omni 输入转写模型",
            "value": settings.dashscope_omni_input_transcription_model,
            "value_type": "select:qwen3-asr-flash-realtime,paraformer-realtime-8k-v2",
            "status": "已配置",
            "description": "Omni 会话内用于输入音频转写的模型。",
        },
        {
            "group_key": "model",
            "item_key": "realtime_asr_model",
            "label": "Pipeline ASR 模型",
            "value": settings.realtime_asr_model,
            "value_type": "select:paraformer-realtime-8k-v2,paraformer-realtime-v2,qwen3-asr-flash-realtime",
            "status": "已配置",
            "description": "低成本分段 Pipeline 的实时语音识别模型。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_realtime_tts_model",
            "label": "实时系统音色 TTS 模型",
            "value": settings.dashscope_realtime_tts_model,
            "value_type": "select:qwen3-tts-flash-realtime,qwen-tts-realtime",
            "status": "已配置",
            "description": "Pipeline 系统音色使用的流式 TTS 模型。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_realtime_tts_voice",
            "label": "实时系统音色",
            "value": settings.dashscope_realtime_tts_voice,
            "value_type": "text",
            "status": "已配置" if settings.dashscope_realtime_tts_voice else "待配置",
            "description": "Pipeline 系统音色 voice 参数。",
        },
        {
            "group_key": "model",
            "item_key": "realtime_tts_voice_id",
            "label": "默认外呼 voice_id",
            "value": settings.realtime_tts_voice_id,
            "value_type": "text",
            "status": "已配置" if settings.realtime_tts_voice_id else "待配置",
            "description": "声音档案选择的默认外呼音色 ID；系统音色填 voice 参数，复刻音色填复刻 voice_id。",
        },
        {
            "group_key": "model",
            "item_key": "realtime_tts_voice_name",
            "label": "默认外呼音色名称",
            "value": settings.realtime_tts_voice_name,
            "value_type": "text",
            "status": "已配置" if settings.realtime_tts_voice_name else "待配置",
            "description": "声音档案选择的默认外呼音色展示名称。",
        },
        {
            "group_key": "model",
            "item_key": "realtime_tts_voice_type",
            "label": "默认外呼音色类型",
            "value": settings.realtime_tts_voice_type,
            "value_type": "select:system,clone",
            "status": "已配置" if settings.realtime_tts_voice_type else "待配置",
            "description": "system 为系统音色，clone 为复刻音色。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_tts_model",
            "label": "复刻音色 TTS 模型",
            "value": settings.dashscope_tts_model,
            "value_type": "select:cosyvoice-v2,cosyvoice-v1",
            "status": "已配置",
            "description": "已授权复刻音色播放使用的 TTS 模型。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_voice_clone_model",
            "label": "声音复刻模型",
            "value": settings.dashscope_voice_clone_model,
            "value_type": "select:cosyvoice-v2,cosyvoice-v1",
            "status": "已配置",
            "description": "声音档案授权样本创建复刻音色时使用的模型。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_system_tts_model",
            "label": "试听系统音色模型",
            "value": settings.dashscope_system_tts_model,
            "value_type": "select:qwen3-tts-flash,qwen-tts",
            "status": "已配置",
            "description": "声音档案系统音色试听使用的模型。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_system_tts_language_type",
            "label": "TTS 语言类型",
            "value": settings.dashscope_system_tts_language_type,
            "value_type": "select:Chinese,English",
            "status": "已配置",
            "description": "Qwen-TTS 系统音色语言参数。",
        },
        {
            "group_key": "model",
            "item_key": "realtime_llm_timeout_seconds",
            "label": "实时 LLM 电话预算秒数",
            "value": str(settings.realtime_llm_timeout_seconds),
            "value_type": "text",
            "status": "已配置",
            "description": "Pipeline 内 LLM 首句预算；超过会使用本地语义策略兜底。",
        },
        {
            "group_key": "model",
            "item_key": "realtime_reply_max_chars",
            "label": "实时回复最长字数",
            "value": str(settings.realtime_reply_max_chars),
            "value_type": "number",
            "status": "已配置",
            "description": "电话场景每句尽量短，防止像录播。",
        },
        {
            "group_key": "model",
            "item_key": "realtime_voice_cache_enabled",
            "label": "外呼音色缓存",
            "value": _bool_value(settings.realtime_voice_cache_enabled),
            "value_type": "boolean",
            "status": "已启用" if settings.realtime_voice_cache_enabled else "未启用",
            "description": "开启后高频问题优先播放预生成真人音色缓存，未命中再回退到实时 TTS 或 Omni。",
        },
        {
            "group_key": "model",
            "item_key": "realtime_voice_cache_dir",
            "label": "外呼音色缓存目录",
            "value": settings.realtime_voice_cache_dir,
            "value_type": "text",
            "status": "已配置" if settings.realtime_voice_cache_dir else "待配置",
            "description": "本机语音缓存包目录，需包含 manifests/natural_v2_manifest_ascii.csv 和 audio_pcm16_8k。",
        },
        {
            "group_key": "model",
            "item_key": "realtime_voice_cache_min_confidence",
            "label": "音色缓存命中阈值",
            "value": str(settings.realtime_voice_cache_min_confidence),
            "value_type": "text",
            "status": "已配置",
            "description": "意图匹配置信度阈值，建议 0.85-0.95。过低容易误播，过高会更多回退实时模型。",
        },
        {
            "group_key": "model",
            "item_key": "voice_clone_provider",
            "label": "声音复刻服务商",
            "value": settings.voice_clone_provider,
            "value_type": "select:dashscope",
            "status": "已配置",
            "description": "当前内置 DashScope/CosyVoice。",
        },
        {
            "group_key": "model",
            "item_key": "voice_clone_training_enabled",
            "label": "启用真实声音复刻",
            "value": _bool_value(settings.voice_clone_training_enabled),
            "value_type": "boolean",
            "status": "已启用" if settings.voice_clone_training_enabled else "未启用",
            "description": "只有接通真实复刻服务后才开启，避免把 mock 训练交付给客户。",
        },
        {
            "group_key": "model",
            "item_key": "voice_clone_engine_name",
            "label": "声音复刻引擎名称",
            "value": settings.voice_clone_engine_name,
            "value_type": "text",
            "status": "已配置" if settings.voice_clone_engine_name else "待配置",
            "description": "显示给运营后台的声音复刻引擎名称。",
        },
        {
            "group_key": "model",
            "item_key": "voice_sample_public_base_url",
            "label": "声音样本公网地址",
            "value": settings.voice_sample_public_base_url,
            "value_type": "text",
            "status": "已配置" if settings.voice_sample_public_base_url else "待配置",
            "description": "DashScope 创建音色需要公网可访问的样本 URL。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_voice_prefix",
            "label": "声音复刻前缀",
            "value": settings.dashscope_voice_prefix,
            "value_type": "text",
            "status": "已配置" if settings.dashscope_voice_prefix else "待配置",
            "description": "DashScope 创建 voice_id 时使用的前缀。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_voice_language_hints",
            "label": "声音样本语言提示",
            "value": settings.dashscope_voice_language_hints,
            "value_type": "text",
            "status": "已配置" if settings.dashscope_voice_language_hints else "待配置",
            "description": "声音复刻样本语言提示，多个值用英文逗号分隔。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_preview_text",
            "label": "复刻试听文本",
            "value": settings.dashscope_preview_text,
            "value_type": "text",
            "status": "已配置" if settings.dashscope_preview_text else "待配置",
            "description": "生成复刻音色试听时使用的文本。",
        },
        {
            "group_key": "model",
            "item_key": "dashscope_system_tts_preview_text",
            "label": "系统音色试听文本",
            "value": settings.dashscope_system_tts_preview_text,
            "value_type": "text",
            "status": "已配置" if settings.dashscope_system_tts_preview_text else "待配置",
            "description": "系统音色试听时使用的文本。",
        },
        {
            "group_key": "permissions",
            "item_key": "default_roles",
            "label": "默认角色",
            "value": "admin,operator,sales",
            "value_type": "text",
            "status": "已启用",
            "description": "管理后台和客户端的一期角色集合。",
        },
        {
            "group_key": "permissions",
            "item_key": "default_owner",
            "label": "默认跟进负责人",
            "value": "待分配",
            "value_type": "text",
            "status": "已启用",
            "description": "新意向客户或工单未分配时的默认负责人。",
        },
        {
            "group_key": "compliance",
            "item_key": "dnc_enabled",
            "label": "勿扰保护",
            "value": "true",
            "value_type": "boolean",
            "status": "已启用",
            "description": "客户拒绝触达或进入勿扰名单后阻断后续任务。",
        },
        {
            "group_key": "compliance",
            "item_key": "refusal_stop_enabled",
            "label": "拒绝即停",
            "value": "true",
            "value_type": "boolean",
            "status": "已启用",
            "description": "外呼或私信明确拒绝后停止自动追触。",
        },
        {
            "group_key": "compliance",
            "item_key": "audit_retention_days",
            "label": "审计保留天数",
            "value": "180",
            "value_type": "number",
            "status": "已启用",
            "description": "配置变更、导出和高风险动作的审计记录保留周期。",
        },
    ]


def _is_valid_setting_value(value: str, value_type: str) -> bool:
    if value_type == "boolean":
        return value in {"true", "false"}
    if value_type == "number":
        return value.isdigit()
    if value_type.startswith("select:"):
        return value in set(value_type.replace("select:", "").split(","))
    return True


def _seed_settings(db: Session) -> None:
    changed = False
    for item in _default_settings():
        exists = db.scalar(
            select(SystemSetting).where(SystemSetting.group_key == item["group_key"], SystemSetting.item_key == item["item_key"])
        )
        if exists:
            for field in ("label", "value_type", "description", "sensitive"):
                next_value = item.get(field)
                if next_value is not None and getattr(exists, field) != next_value:
                    setattr(exists, field, next_value)
                    changed = True
            if not _is_valid_setting_value(exists.value, str(item["value_type"])):
                exists.value = str(item["value"])
                exists.status = str(item["status"])
                changed = True
            if _is_client_visible(exists) or exists.group_key == "model":
                next_status = _status_for_setting_value(exists.group_key, exists.item_key, exists.value)
                if exists.status != next_status:
                    exists.status = next_status
                    changed = True
            continue
        db.add(SystemSetting(**item))
        changed = True
    if changed:
        db.flush()
        db.add(
            SystemAuditLog(
                actor="系统",
                action="seed",
                target_type="system_settings",
                summary="初始化系统设置默认项",
                after_value="default settings",
            )
        )
        db.commit()


def _is_enabled(setting: SystemSetting) -> bool:
    return setting.status in {"已启用", "已配置", "受控", "模拟模式"}


def _is_client_visible(setting: SystemSetting) -> bool:
    return (setting.group_key, setting.item_key) in CLIENT_VISIBLE_ITEMS


@router.get("/overview", response_model=SettingsOverview)
def settings_overview(db: Session = Depends(get_db)) -> dict[str, object]:
    _seed_settings(db)
    all_items = list(db.scalars(select(SystemSetting)).all())
    items = [item for item in all_items if _is_client_visible(item)]
    groups = []
    for group_key, label in CLIENT_GROUP_LABELS.items():
        group_items = [item for item in items if item.group_key == group_key]
        groups.append(
            {
                "group_key": group_key,
                "label": label,
                "total": len(group_items),
                "enabled": sum(1 for item in group_items if _is_enabled(item)),
                "warning": sum(1 for item in group_items if not _is_enabled(item)),
            }
        )
    audits = db.scalar(select(func.count()).select_from(SystemAuditLog)) or 0
    return {
        "total_settings": len(items),
        "enabled_settings": sum(1 for item in items if _is_enabled(item)),
        "warning_settings": sum(1 for item in items if not _is_enabled(item)),
        "sensitive_settings": sum(1 for item in items if item.sensitive),
        "audit_logs": int(audits),
        "groups": groups,
    }


@router.get("/items", response_model=list[SystemSettingRead])
def list_system_settings(db: Session = Depends(get_db)) -> list[SystemSetting]:
    _seed_settings(db)
    items = list(db.scalars(select(SystemSetting).order_by(SystemSetting.group_key, SystemSetting.item_key)).all())
    return [item for item in items if _is_client_visible(item)]


@router.patch("/items/{setting_id}", response_model=SystemSettingRead)
def update_system_setting(setting_id: str, payload: SystemSettingUpdate, db: Session = Depends(get_db)) -> SystemSetting:
    _seed_settings(db)
    setting = db.get(SystemSetting, setting_id)
    if not setting:
        raise HTTPException(status_code=404, detail="系统设置不存在")
    if not _is_client_visible(setting):
        raise HTTPException(status_code=404, detail="系统设置不存在")
    before = "[masked]" if setting.sensitive else setting.value
    values = payload.model_dump(exclude={"actor"}, exclude_unset=True)
    for field, value in values.items():
        if value is not None:
            setattr(setting, field, value)
    if "value" in values and "status" not in values:
        setting.status = _status_for_setting_value(setting.group_key, setting.item_key, setting.value)
    setting.updated_by = payload.actor
    setting.updated_at = datetime.utcnow()
    after = "[masked]" if setting.sensitive else setting.value
    db.add(
        SystemAuditLog(
            actor=payload.actor,
            action="update",
            target_type="system_setting",
            target_id=setting.id,
            summary=f"更新配置：{setting.label}",
            before_value=before,
            after_value=after,
        )
    )
    db.commit()
    db.refresh(setting)
    return setting


@router.get("/audit-logs", response_model=list[SystemAuditLogRead])
def list_system_audit_logs(db: Session = Depends(get_db)) -> list[SystemAuditLog]:
    _seed_settings(db)
    return list(db.scalars(select(SystemAuditLog).order_by(SystemAuditLog.created_at.desc()).limit(80)).all())
