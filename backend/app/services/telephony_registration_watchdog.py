"""电话注册看门狗（【审计B1】掉注册无监控无自愈）。

本架构是语音网关（如鼎信 8T）主动注册进服务器 Asterisk，服务器端无法替网关重新注册。
因此自愈策略是：常驻 asyncio 任务每 30 秒通过现有 AMI 封装查询 pjsip contacts，
contact 消失/恢复时写日志事件（telephony_registration_lost / telephony_registration_recovered），
连续 3 次丢失时落一条待办事件文件，提示运维在网关侧重新发起 SIP 注册。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.services.asterisk_ami import AsteriskAmiClient, AsteriskAmiError, _trunk_status_from_output
from app.services.voice_gateway_profiles import current_voice_gateway_profile

logger = logging.getLogger(__name__)

# 【审计B1】待办事件文件：连续丢失注册时写入，供运维/前端拾取
TELEPHONY_ALERT_PATH = Path("/tmp/ai_acq_telephony_alert.json")
WATCHDOG_INTERVAL_SECONDS = 30.0
ALERT_AFTER_CONSECUTIVE_LOSSES = 3


def check_registration_contact() -> tuple[bool | None, str]:
    """查询 pjsip contacts，判断网关 trunk 的 contact 是否存在且可达。

    返回 (True=存在且可达, False=消失或不可达, None=AMI 不可用/无法判断)。
    复用 asterisk_ami.AsteriskAmiClient 与 _trunk_status_from_output（含审计B4修正）。
    """
    trunk_name = (current_voice_gateway_profile().trunk_name or "").strip()
    try:
        with AsteriskAmiClient() as client:
            response = client.command("pjsip show contacts")
            output = response.field_text("Output") or response.message
    except AsteriskAmiError as exc:
        return None, str(exc)
    if trunk_name:
        # 只看属于本 trunk 的 contact 行，避免其他 endpoint 干扰判断
        related = "\n".join(
            line for line in output.splitlines() if trunk_name.lower() in line.lower()
        )
        if not related.strip():
            return False, f"pjsip contacts 中未找到 {trunk_name} 的 contact（网关未注册进来）"
        return _trunk_status_from_output(related)
    return _trunk_status_from_output(output)


async def run_registration_watchdog(interval_seconds: float = WATCHDOG_INTERVAL_SECONDS) -> None:
    """【审计B1】常驻看门狗循环：每 interval_seconds 检查一次注册 contact。"""
    logger.info("telephony_registration_watchdog_started interval=%.0fs", interval_seconds)
    last_present: bool | None = None
    consecutive_losses = 0
    while True:
        try:
            present, detail = await asyncio.to_thread(check_registration_contact)
        except asyncio.CancelledError:
            logger.info("telephony_registration_watchdog_cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 看门狗永不因单次检查异常退出
            present, detail = None, str(exc)
        if present is False:
            consecutive_losses += 1
            if last_present is not False:
                # 【审计B1】contact 消失事件
                logger.warning("telephony_registration_lost detail=%s", detail)
            if consecutive_losses == ALERT_AFTER_CONSECUTIVE_LOSSES:
                _write_alert_file(detail, consecutive_losses)
            last_present = False
        elif present is True:
            if last_present is False:
                # 【审计B1】contact 恢复事件
                logger.warning("telephony_registration_recovered detail=%s", detail)
                _clear_alert_file()
            consecutive_losses = 0
            last_present = True
        else:
            # AMI 不可用或输出无法判断：不计入丢失次数，只提示
            logger.warning("telephony_registration_watchdog_check_skipped detail=%s", detail)
        await asyncio.sleep(max(5.0, interval_seconds))


def _write_alert_file(detail: str, consecutive_losses: int) -> None:
    payload = {
        "event": "telephony_registration_lost",
        "trunk": current_voice_gateway_profile().trunk_name,
        "consecutiveLosses": consecutive_losses,
        "detail": detail[:500],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        # 本架构是网关注册进服务器 Asterisk，服务器端无法替网关重注册
        "action": "请在语音网关侧检查电源/网络/SIP账号并重新发起 SIP 注册",
    }
    try:
        TELEPHONY_ALERT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.warning("telephony_registration_alert_written path=%s", TELEPHONY_ALERT_PATH)
    except OSError:
        logger.exception("telephony_registration_alert_write_failed path=%s", TELEPHONY_ALERT_PATH)


def _clear_alert_file() -> None:
    try:
        TELEPHONY_ALERT_PATH.unlink()
    except FileNotFoundError:
        return
    except OSError:
        logger.exception("telephony_registration_alert_clear_failed path=%s", TELEPHONY_ALERT_PATH)
