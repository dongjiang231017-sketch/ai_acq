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


def _bool_value(value: bool) -> str:
    return "true" if value else "false"


def _default_settings() -> list[dict[str, object]]:
    return [
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
            "item_key": "realtime_api_alias",
            "label": "实时语音模型",
            "value": "secret:openai_realtime_api",
            "value_type": "text",
            "status": "待配置",
            "description": "仅保存密钥别名，不在系统设置中保存原始 API Key。",
            "sensitive": True,
        },
        {
            "group_key": "model",
            "item_key": "asr_model",
            "label": "语音识别模型",
            "value": "whisper-1",
            "value_type": "select:whisper-1,gpt-4o-mini-transcribe,realtime",
            "status": "待接入",
            "description": "外呼通话转写和质检使用的 ASR 模型别名。",
        },
        {
            "group_key": "model",
            "item_key": "poi_api_alias",
            "label": "商源检索 API",
            "value": "secret:poi_provider_api",
            "value_type": "text",
            "status": "待配置",
            "description": "地图、平台或商源检索服务的密钥别名。",
            "sensitive": True,
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


def _seed_settings(db: Session) -> None:
    created = False
    for item in _default_settings():
        exists = db.scalar(
            select(SystemSetting).where(SystemSetting.group_key == item["group_key"], SystemSetting.item_key == item["item_key"])
        )
        if exists:
            continue
        db.add(SystemSetting(**item))
        created = True
    if created:
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


@router.get("/overview", response_model=SettingsOverview)
def settings_overview(db: Session = Depends(get_db)) -> dict[str, object]:
    _seed_settings(db)
    items = list(db.scalars(select(SystemSetting)).all())
    groups = []
    for group_key, label in GROUP_LABELS.items():
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
    return list(db.scalars(select(SystemSetting).order_by(SystemSetting.group_key, SystemSetting.item_key)).all())


@router.patch("/items/{setting_id}", response_model=SystemSettingRead)
def update_system_setting(setting_id: str, payload: SystemSettingUpdate, db: Session = Depends(get_db)) -> SystemSetting:
    _seed_settings(db)
    setting = db.get(SystemSetting, setting_id)
    if not setting:
        raise HTTPException(status_code=404, detail="系统设置不存在")
    before = "[masked]" if setting.sensitive else setting.value
    values = payload.model_dump(exclude={"actor"}, exclude_unset=True)
    for field, value in values.items():
        if value is not None:
            setattr(setting, field, value)
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
