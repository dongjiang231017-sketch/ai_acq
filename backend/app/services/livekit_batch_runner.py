"""LiveKit 批量外呼编排（2026-07-09，需求 7.7.4/7.7.5）。

此前 TELEPHONY_GATEWAY_MODE=livekit 时批量任务会 fallback 到 SimulatorGateway，
点"启动任务"只生成假通话记录。本模块实现真实批量外呼：

- 逐个 dispatch LiveKit 呼叫（带 taskId/leadId 元数据），通话由 agent worker 处理；
- 并发槽位控制（默认取任务 concurrency，上限=网关通道数）；
- 完成检测：worker 挂断落库 CallRecord（gateway_call_id=action_id）即视为该通结束；
- 跳过黑名单/勿扰/已明确拒绝的线索（需求 7.7.5.5）；
- 单通超时 6 分钟、整任务兜底超时后按已完成数收尾，任务计数由 worker 落库时累加。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.lead import MerchantLead
from app.models.task import CallRecord, OutreachTask
from app.services.livekit_outbound import LiveKitOutboundError, dispatch_livekit_outbound_call
from app.services.outbound_runner import get_task_leads

logger = logging.getLogger(__name__)

# 拨打中：防任务重启后重拨进行中的号码；有意向：已确认意向的交给销售跟进，不再机拨
_SKIP_STATUS_MARKERS = ("勿扰", "黑名单", "拒绝", "已成交", "拨打中", "有意向")
_PER_CALL_TIMEOUT_SECONDS = 360
_DIAL_GAP_SECONDS = 2.0
_RUNNING_TASKS: set[str] = set()
_RUNNING_LOCK = threading.Lock()


def start_livekit_outbound_task(task_id: str) -> None:
    """后台线程启动批量外呼；重复启动同一任务直接忽略。

    check-then-add 用锁包成原子，防止并发/双击两次进入把同一名单每个号码拨两遍
    （子代理审计的竞态）。注：这是进程内守卫，多 worker 进程仍需 DB 层幂等兜底。
    """
    with _RUNNING_LOCK:
        if task_id in _RUNNING_TASKS:
            return
        _RUNNING_TASKS.add(task_id)
    thread = threading.Thread(target=_run_task, args=(task_id,), daemon=True, name=f"lk-batch-{task_id[:8]}")
    thread.start()


def _completed_count(db, action_ids: list[str]) -> int:
    if not action_ids:
        return 0
    return int(
        db.scalar(
            select(func.count()).select_from(CallRecord).where(
                CallRecord.gateway_call_id.in_(action_ids),
                CallRecord.gateway_status.in_(["completed", "no_answer", "failed"]),
            )
        )
        or 0
    )


def _skippable(lead: MerchantLead) -> bool:
    status_text = " ".join(str(v or "") for v in (lead.status, lead.follow_up_status, lead.remark))
    return any(marker in status_text for marker in _SKIP_STATUS_MARKERS)


def _run_task(task_id: str) -> None:
    try:
        with SessionLocal() as db:
            task = db.get(OutreachTask, task_id)
            if task is None or task.channel != "call":
                return
            leads = [lead for lead in get_task_leads(db, task) if lead.phone and not _skippable(lead)]
            concurrency = max(1, min(int(task.concurrency or 1), 8))
            task.status = "运行中"
            task.started_at = datetime.utcnow()
            task.finished_at = None
            task.completed_count = 0
            task.connected_count = 0
            task.intent_count = 0
            task.failed_count = 0
            db.commit()
            lead_specs = [(lead.id, lead.phone, lead.name) for lead in leads]

        if not lead_specs:
            with SessionLocal() as db:
                task = db.get(OutreachTask, task_id)
                if task is not None:
                    task.status = "已完成"
                    task.finished_at = datetime.utcnow()
                    db.commit()
            return

        dispatched: list[tuple[str, float]] = []  # (action_id, dispatched_at)
        dispatch_failed = 0

        for lead_id, phone, name in lead_specs:
            # 槽位等待：进行中呼叫数 = 已派发 - 已落库 - 已超时
            while True:
                with SessionLocal() as db:
                    done = _completed_count(db, [a for a, _ in dispatched])
                now = time.monotonic()
                timed_out = sum(1 for _, t0 in dispatched if now - t0 > _PER_CALL_TIMEOUT_SECONDS)
                active = len(dispatched) - done - timed_out
                if active < concurrency:
                    break
                time.sleep(3)

            try:
                result = dispatch_livekit_outbound_call(phone, merchant_name=name, task_id=task_id, lead_id=lead_id)
                dispatched.append((result.action_id, time.monotonic()))
                with SessionLocal() as db:
                    lead = db.get(MerchantLead, lead_id)
                    if lead is not None:
                        lead.status = "拨打中"
                        db.commit()
            except Exception as exc:  # noqa: BLE001
                # 单通失败隔离：一次瞬时网络/DB 抖动只跳过这一个号码继续下一个，
                # 不能让整批 367 个号码因一次可恢复错误全部放弃（子代理审计 bug C，
                # 原来只捕 LiveKitOutboundError，其它异常穿透到外层→整批判"异常"）。
                dispatch_failed += 1
                logger.warning("批量外呼 dispatch 失败 lead=%s: %s", lead_id, exc)
                try:
                    with SessionLocal() as db:
                        task = db.get(OutreachTask, task_id)
                        if task is not None:
                            task.failed_count = (task.failed_count or 0) + 1
                            db.commit()
                except Exception:  # noqa: BLE001
                    logger.exception("dispatch 失败计数写库也失败 lead=%s", lead_id)
            time.sleep(_DIAL_GAP_SECONDS)

        # 收尾：等余下呼叫落库或超时
        deadline = time.monotonic() + _PER_CALL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with SessionLocal() as db:
                done = _completed_count(db, [a for a, _ in dispatched])
            if done >= len(dispatched):
                break
            time.sleep(5)

        with SessionLocal() as db:
            task = db.get(OutreachTask, task_id)
            if task is not None:
                # 从 CallRecord 聚合权威计数覆盖（不依赖 persist 的增量计数器——
                # 多进程并发落库的 Python 层 +1 会丢更新，子代理审计 bug A）。
                action_ids = [a for a, _ in dispatched]
                done = _completed_count(db, action_ids)
                if action_ids:
                    connected = int(
                        db.scalar(
                            select(func.count()).select_from(CallRecord).where(
                                CallRecord.gateway_call_id.in_(action_ids),
                                CallRecord.outcome.in_(["有意向", "已接通", "稍后联系"]),
                            )
                        ) or 0
                    )
                    intent = int(
                        db.scalar(
                            select(func.count()).select_from(CallRecord).where(
                                CallRecord.gateway_call_id.in_(action_ids),
                                CallRecord.intent_level.in_(["A", "B"]),
                            )
                        ) or 0
                    )
                else:
                    connected = intent = 0
                missing = len(dispatched) - done
                task.completed_count = max(task.completed_count or 0, done)
                task.connected_count = connected
                task.intent_count = intent
                task.failed_count = dispatch_failed + missing
                task.status = "已完成" if missing == 0 and dispatch_failed == 0 else "部分完成"
                task.finished_at = datetime.utcnow()
                db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("批量外呼任务 %s 异常", task_id)
        try:
            with SessionLocal() as db:
                task = db.get(OutreachTask, task_id)
                if task is not None:
                    task.status = "异常"
                    task.finished_at = datetime.utcnow()
                    db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("批量外呼任务 %s 状态回写失败", task_id)
    finally:
        _RUNNING_TASKS.discard(task_id)
