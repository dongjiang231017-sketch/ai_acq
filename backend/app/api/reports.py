from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.intent import _sync_intent_customers
from app.db.session import get_db
from app.models.growth import FollowUpWorkOrder, IntentCustomer
from app.models.lead import MerchantLead
from app.models.operations import ReportExport
from app.models.task import CallRecord, DirectMessageConversation, OutreachTask
from app.schemas.reports import (
    ChannelReport,
    ReportExportCreate,
    ReportExportRead,
    ReportOverview,
    SalesPerformanceReport,
)

router = APIRouter()


def _rate(part: int, total: int) -> int:
    return round((part / total) * 100) if total else 0


def _seed_export(db: Session) -> None:
    exports = db.scalar(select(func.count()).select_from(ReportExport)) or 0
    if exports:
        return
    export = ReportExport(
        report_type="经营总览",
        date_range="近30天",
        file_format="xlsx",
        requester="系统",
        status="已生成",
        row_count=0,
        download_url="/api/reports/exports/sample/download",
        finished_at=datetime.utcnow(),
    )
    db.add(export)
    db.commit()


def _report_counts(db: Session) -> dict[str, int]:
    _sync_intent_customers(db)
    total_leads = db.scalar(select(func.count()).select_from(MerchantLead)) or 0
    total_calls = db.scalar(select(func.count()).select_from(CallRecord)) or 0
    total_dm = db.scalar(select(func.count()).select_from(DirectMessageConversation)) or 0
    connected_calls = (
        db.scalar(select(func.count()).select_from(CallRecord).where(CallRecord.outcome.in_(["有意向", "已接通", "稍后联系"]))) or 0
    )
    connected_dm = (
        db.scalar(select(func.count()).select_from(DirectMessageConversation).where(DirectMessageConversation.status.in_(["已回复", "需人工"])))
        or 0
    )
    high_intent = db.scalar(select(func.count()).select_from(IntentCustomer).where(IntentCustomer.intent_level.in_(["A", "B"]))) or 0
    pending = (
        db.scalar(select(func.count()).select_from(FollowUpWorkOrder).where(FollowUpWorkOrder.status.in_(["待分配", "跟进中", "待确认"])))
        or 0
    )
    exports = db.scalar(select(func.count()).select_from(ReportExport)) or 0
    return {
        "total_leads": int(total_leads),
        "total_touches": int(total_calls) + int(total_dm),
        "connected": int(connected_calls) + int(connected_dm),
        "high_intent": int(high_intent),
        "pending_work_orders": int(pending),
        "export_jobs": int(exports),
    }


@router.get("/overview", response_model=ReportOverview)
def reports_overview(db: Session = Depends(get_db)) -> dict[str, object]:
    _seed_export(db)
    counts = _report_counts(db)
    funnel = [
        {"key": "leads", "label": "商家线索", "value": counts["total_leads"], "rate": 100 if counts["total_leads"] else 0},
        {
            "key": "touches",
            "label": "电话/私信触达",
            "value": counts["total_touches"],
            "rate": _rate(counts["total_touches"], counts["total_leads"]),
        },
        {
            "key": "connected",
            "label": "有效接通/回复",
            "value": counts["connected"],
            "rate": _rate(counts["connected"], counts["total_touches"]),
        },
        {
            "key": "intent",
            "label": "A/B 意向",
            "value": counts["high_intent"],
            "rate": _rate(counts["high_intent"], counts["connected"]),
        },
    ]
    return {
        **counts,
        "conversion_rate": _rate(counts["high_intent"], counts["total_leads"]),
        "funnel": funnel,
        "updated_at": datetime.utcnow(),
    }


@router.get("/channels", response_model=list[ChannelReport])
def channel_reports(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    _sync_intent_customers(db)
    channels: dict[str, dict[str, int | str]] = {
        "collector": {"id": "collector", "channel": "线索采集", "leads": 0, "touches": 0, "connected": 0, "intent": 0, "handoff": 0},
        "call": {"id": "call", "channel": "AI外呼", "leads": 0, "touches": 0, "connected": 0, "intent": 0, "handoff": 0},
        "dm": {"id": "dm", "channel": "平台私信", "leads": 0, "touches": 0, "connected": 0, "intent": 0, "handoff": 0},
    }

    for lead in db.scalars(select(MerchantLead)).all():
        channels["collector"]["leads"] = int(channels["collector"]["leads"]) + 1
        if lead.intent_score >= 70:
            channels["collector"]["intent"] = int(channels["collector"]["intent"]) + 1

    for task in db.scalars(select(OutreachTask)).all():
        channel_key = "dm" if task.channel == "dm" else "call" if task.channel == "call" else "collector"
        channels[channel_key]["leads"] = max(int(channels[channel_key]["leads"]), task.target_count)

    for record in db.scalars(select(CallRecord)).all():
        channels["call"]["touches"] = int(channels["call"]["touches"]) + 1
        if record.outcome in {"有意向", "已接通", "稍后联系"}:
            channels["call"]["connected"] = int(channels["call"]["connected"]) + 1
        if record.intent_level in {"A", "B"}:
            channels["call"]["intent"] = int(channels["call"]["intent"]) + 1
        if record.need_handoff:
            channels["call"]["handoff"] = int(channels["call"]["handoff"]) + 1

    for conversation in db.scalars(select(DirectMessageConversation)).all():
        channels["dm"]["touches"] = int(channels["dm"]["touches"]) + 1
        if conversation.status in {"已回复", "需人工"}:
            channels["dm"]["connected"] = int(channels["dm"]["connected"]) + 1
        if conversation.intent_level in {"A", "B"}:
            channels["dm"]["intent"] = int(channels["dm"]["intent"]) + 1
        if conversation.need_handoff:
            channels["dm"]["handoff"] = int(channels["dm"]["handoff"]) + 1

    reports: list[dict[str, object]] = []
    for item in channels.values():
        conversion_rate = _rate(int(item["intent"]), max(int(item["touches"]), int(item["leads"])))
        reports.append(
            {
                **item,
                "conversion_rate": conversion_rate,
                "status": "重点跟进" if int(item["handoff"]) > 0 else "稳定",
                "insight": "人工接管较多，建议销售优先处理。"
                if int(item["handoff"]) > 0
                else "当前通道运行平稳，可继续观察转化。",
            }
        )
    return reports


@router.get("/sales", response_model=list[SalesPerformanceReport])
def sales_performance_reports(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    _sync_intent_customers(db)
    owners: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "assigned_customers": 0,
            "pending_work_orders": 0,
            "closed_work_orders": 0,
            "high_intent": 0,
            "handoff": 0,
            "last_activity_at": None,
        }
    )
    for customer in db.scalars(select(IntentCustomer)).all():
        owner = customer.owner_name or "待分配"
        owners[owner]["assigned_customers"] = int(owners[owner]["assigned_customers"]) + 1
        if customer.intent_level in {"A", "B"}:
            owners[owner]["high_intent"] = int(owners[owner]["high_intent"]) + 1
        if customer.need_handoff:
            owners[owner]["handoff"] = int(owners[owner]["handoff"]) + 1
        current = owners[owner]["last_activity_at"]
        owners[owner]["last_activity_at"] = max(current, customer.updated_at) if isinstance(current, datetime) else customer.updated_at

    for order in db.scalars(select(FollowUpWorkOrder)).all():
        owner = order.owner_name or "待分配"
        if order.status in {"已完成", "已关闭"}:
            owners[owner]["closed_work_orders"] = int(owners[owner]["closed_work_orders"]) + 1
        else:
            owners[owner]["pending_work_orders"] = int(owners[owner]["pending_work_orders"]) + 1
        current = owners[owner]["last_activity_at"]
        owners[owner]["last_activity_at"] = max(current, order.updated_at) if isinstance(current, datetime) else order.updated_at

    if not owners:
        owners["待分配"]

    return [
        {
            "id": owner,
            "owner_name": owner,
            **values,
            "conversion_rate": _rate(int(values["high_intent"]), int(values["assigned_customers"])),
        }
        for owner, values in sorted(owners.items(), key=lambda item: int(item[1]["high_intent"]), reverse=True)
    ]


@router.get("/exports", response_model=list[ReportExportRead])
def list_report_exports(db: Session = Depends(get_db)) -> list[ReportExport]:
    _seed_export(db)
    return list(db.scalars(select(ReportExport).order_by(ReportExport.created_at.desc())).all())


@router.post("/exports", response_model=ReportExportRead)
def create_report_export(payload: ReportExportCreate, db: Session = Depends(get_db)) -> ReportExport:
    if payload.report_type == "渠道分析":
        row_count = len(channel_reports(db))
    elif payload.report_type == "销售绩效":
        row_count = len(sales_performance_reports(db))
    else:
        counts = _report_counts(db)
        row_count = sum(counts.values())
    export = ReportExport(
        report_type=payload.report_type,
        date_range=payload.date_range,
        file_format=payload.file_format,
        requester=payload.requester,
        status="已生成",
        row_count=int(row_count),
        sensitive_fields_included=payload.include_sensitive_fields,
        finished_at=datetime.utcnow(),
    )
    db.add(export)
    db.flush()
    export.download_url = f"/api/reports/exports/{export.id}/download"
    db.commit()
    db.refresh(export)
    return export


@router.get("/exports/{export_id}/download")
def download_report_export(export_id: str, db: Session = Depends(get_db)):
    """真实生成 xlsx 并下载（2026-07-09：此前 download_url 是死链，需求 7.11.3.2）。"""
    from io import BytesIO

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook

    export = db.get(ReportExport, export_id)
    report_type = export.report_type if export else "线索明细"

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = report_type[:28] or "报表"

    if report_type == "渠道分析":
        rows = channel_reports(db)
        headers = ["渠道", "线索数", "触达数", "接通/回复", "意向数", "转人工"]
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get("channel"), row.get("leads"), row.get("touches"), row.get("connected"), row.get("intent"), row.get("handoff")])
    elif report_type == "销售绩效":
        rows = sales_performance_reports(db)
        headers = ["销售", "跟进客户数", "待办工单", "完成工单", "成交数"]
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get("owner"), row.get("customers"), row.get("pendingOrders"), row.get("closedOrders"), row.get("deals")])
    elif report_type == "通话记录":
        sheet.append(["商家", "电话", "接听结果", "意向等级", "时长(秒)", "呼叫时间", "转写摘要"])
        for record in db.scalars(select(CallRecord).order_by(CallRecord.created_at.desc()).limit(5000)):
            sheet.append([
                record.merchant_name,
                record.phone or "",
                record.outcome,
                record.intent_level,
                record.duration_seconds,
                record.created_at.isoformat(sep=" ", timespec="seconds") if record.created_at else "",
                (record.transcript or "")[:500],
            ])
    elif report_type == "意向客户":
        sheet.append(["商家", "城市", "类目", "电话", "意向等级", "来源渠道", "最新信号", "跟进状态", "跟进人"])
        for customer in db.scalars(select(IntentCustomer).order_by(IntentCustomer.updated_at.desc()).limit(5000)):
            sheet.append([
                customer.merchant_name,
                customer.city,
                customer.category,
                customer.phone or "",
                customer.intent_level,
                customer.source_channels,
                (customer.latest_signal or "")[:200],
                customer.follow_status,
                customer.owner_name,
            ])
    else:  # 线索明细（默认）
        sheet.append(["商家名称", "城市", "区县", "类目", "电话", "地址", "来源", "评分", "电话状态", "跟进状态", "创建时间"])
        for lead in db.scalars(select(MerchantLead).order_by(MerchantLead.created_at.desc()).limit(10000)):
            sheet.append([
                lead.name,
                lead.city,
                lead.district or "",
                lead.category,
                lead.phone or "",
                lead.address or "",
                lead.source,
                lead.intent_score,
                lead.status,
                lead.follow_up_status,
                lead.created_at.isoformat(sep=" ", timespec="seconds") if lead.created_at else "",
            ])

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    from urllib.parse import quote

    # HTTP 头必须 latin-1：中文文件名需 RFC 5987 百分号编码，否则 starlette 编码报 500
    filename = quote(f"{report_type}-{datetime.utcnow().strftime('%Y%m%d%H%M')}.xlsx")
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
