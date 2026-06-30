import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.lead import MerchantLead
from app.models.task import CommentInterceptSource, CommentLeadConversion, SocialComment
from app.schemas.comment_intercept import (
    BrowserCommentCaptureRequest,
    CommentConvertRequest,
    CommentConvertResult,
    CommentInterceptOverview,
    CommentInterceptSourceCreate,
    CommentInterceptSourceRead,
    CommentSyncResult,
    SocialCommentRead,
)
from app.services.comment_intercept_adapter import CommentInterceptAdapterUnavailable, PlatformComment, sync_platform_comments

router = APIRouter()

INTENT_WORDS = ("合作", "价格", "报名", "入驻", "求资料", "想了解", "怎么做", "加我", "联系", "开通")
RISK_WORDS = ("兼职", "刷单", "贷款", "博彩", "色情")


def _intent_score(content: str, like_count: int, keyword_rules: str) -> tuple[int, str]:
    rules = [word.strip() for word in keyword_rules.replace("，", ",").split(",") if word.strip()]
    keyword_pool = tuple(dict.fromkeys([*INTENT_WORDS, *rules]))
    hits = sum(1 for word in keyword_pool if word and word in content)
    score = min(98, 46 + hits * 13 + min(like_count, 20))
    if score >= 85:
        return score, "A"
    if score >= 70:
        return score, "B"
    if score >= 55:
        return score, "C"
    return score, "D"


def _risk_status(content: str) -> str:
    return "需人工复核" if any(word in content for word in RISK_WORDS) else "正常"


def _safe_external_comment_id(value: str | None, seed: str) -> str:
    trimmed = (value or "").strip()
    if trimmed and len(trimmed) <= 120:
        return trimmed
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return f"browser-{digest}"[:120]


def _raw_payload_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)[:5000]


def _platform_comment_from_browser_capture(
    source: CommentInterceptSource,
    captured: object,
    page_url: str,
    page_title: str,
) -> PlatformComment | None:
    content = str(getattr(captured, "content", "") or "").strip()
    if not content:
        return None

    author_name = str(getattr(captured, "author_name", "") or "").strip() or "平台评论用户"
    video_url = str(getattr(captured, "video_url", "") or "").strip() or page_url or source.video_url
    raw_payload = {
        "captureMode": "desktop-webview-dom",
        "pageUrl": page_url,
        "pageTitle": page_title,
        "captured": getattr(captured, "raw_payload", None) or {},
    }
    seed = f"{source.id}|{video_url}|{author_name}|{content}"
    return PlatformComment(
        external_comment_id=_safe_external_comment_id(getattr(captured, "external_comment_id", None), seed),
        author_name=author_name[:120],
        author_profile_url=str(getattr(captured, "author_profile_url", "") or "").strip(),
        content=content,
        video_url=video_url,
        city=str(getattr(captured, "city", "") or "").strip() or "待识别",
        category=str(getattr(captured, "category", "") or "").strip() or "待识别",
        like_count=int(getattr(captured, "like_count", 0) or 0),
        reply_count=int(getattr(captured, "reply_count", 0) or 0),
        commented_at=getattr(captured, "commented_at", None),
        raw_payload=_raw_payload_json(raw_payload),
    )


def _import_platform_comments(
    source: CommentInterceptSource,
    platform_comments: list[PlatformComment],
    db: Session,
) -> tuple[int, int]:
    imported = 0
    skipped = 0
    for platform_comment in platform_comments:
        existing = db.scalar(
            select(SocialComment).where(
                SocialComment.source_id == source.id,
                SocialComment.external_comment_id == platform_comment.external_comment_id,
            )
        )
        if existing:
            skipped += 1
            continue
        score, level = _intent_score(platform_comment.content, platform_comment.like_count, source.keyword_rules)
        comment = SocialComment(
            source_id=source.id,
            platform=source.platform,
            external_comment_id=platform_comment.external_comment_id,
            video_url=platform_comment.video_url,
            author_name=platform_comment.author_name,
            author_profile_url=platform_comment.author_profile_url,
            content=platform_comment.content,
            city=platform_comment.city,
            category=platform_comment.category,
            like_count=platform_comment.like_count,
            reply_count=platform_comment.reply_count,
            intent_score=score,
            intent_level=level,
            status="待转线索",
            risk_status=_risk_status(platform_comment.content),
            raw_payload=platform_comment.raw_payload,
            commented_at=platform_comment.commented_at,
        )
        db.add(comment)
        imported += 1
    return imported, skipped


def _source_comment_count(source_id: str, db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(SocialComment).where(SocialComment.source_id == source_id)) or 0)


@router.get("/overview", response_model=CommentInterceptOverview)
def comment_intercept_overview(db: Session = Depends(get_db)) -> dict[str, int]:
    sources = db.scalar(select(func.count()).select_from(CommentInterceptSource)) or 0
    comments = db.scalar(select(func.count()).select_from(SocialComment)) or 0
    high_intent = (
        db.scalar(select(func.count()).select_from(SocialComment).where(SocialComment.intent_level.in_(["A", "B"]))) or 0
    )
    converted = db.scalar(select(func.count()).select_from(CommentLeadConversion)) or 0
    return {
        "sources": int(sources),
        "comments": int(comments),
        "highIntentComments": int(high_intent),
        "convertedLeads": int(converted),
    }


@router.get("/sources", response_model=list[CommentInterceptSourceRead])
def list_comment_sources(db: Session = Depends(get_db)) -> list[CommentInterceptSource]:
    return list(db.scalars(select(CommentInterceptSource).order_by(CommentInterceptSource.created_at.desc())).all())


@router.post("/sources", response_model=CommentInterceptSourceRead)
def create_comment_source(payload: CommentInterceptSourceCreate, db: Session = Depends(get_db)) -> CommentInterceptSource:
    if payload.platform not in {"抖音", "视频号"}:
        raise HTTPException(status_code=400, detail="评论截流第一版只支持抖音和视频号来源")
    source = CommentInterceptSource(
        platform=payload.platform,
        source_type=payload.source_type,
        name=payload.name,
        keyword=payload.keyword,
        video_url=payload.video_url,
        video_title=payload.video_title,
        owner_account_id=payload.owner_account_id,
        sync_frequency_minutes=payload.sync_frequency_minutes,
        keyword_rules=payload.keyword_rules,
        auto_reply_enabled=payload.auto_reply_enabled,
        human_confirm_required=payload.human_confirm_required,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.post("/sources/{source_id}/sync", response_model=CommentSyncResult)
def sync_comment_source(source_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    source = db.get(CommentInterceptSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="评论截流来源不存在")

    try:
        platform_comments = sync_platform_comments(source)
    except CommentInterceptAdapterUnavailable as exc:
        source.sync_status = "未接通"
        source.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except RuntimeError as exc:
        source.sync_status = "同步失败"
        source.last_error = f"评论同步失败：{exc}"
        db.commit()
        raise HTTPException(status_code=502, detail=source.last_error) from exc

    imported, skipped = _import_platform_comments(source, platform_comments, db)
    now = datetime.utcnow()
    source.sync_status = "已同步"
    source.last_sync_at = now
    source.last_error = None
    db.commit()
    total_comments = _source_comment_count(source.id, db)
    return {
        "sourceId": source.id,
        "imported": imported,
        "skipped": skipped,
        "totalComments": total_comments,
        "message": f"真实平台同步完成：新增 {imported} 条评论，跳过 {skipped} 条重复评论。",
    }


@router.post("/sources/{source_id}/browser-capture", response_model=CommentSyncResult)
def import_browser_captured_comments(
    source_id: str,
    payload: BrowserCommentCaptureRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    source = db.get(CommentInterceptSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="评论截流来源不存在")
    if payload.platform != source.platform:
        raise HTTPException(status_code=400, detail=f"当前来源是{source.platform}，不能导入{payload.platform}页面评论")

    page_url = payload.page_url.strip() or source.video_url
    page_title = payload.page_title.strip()
    platform_comments = [
        platform_comment
        for platform_comment in (
            _platform_comment_from_browser_capture(source, captured, page_url, page_title)
            for captured in payload.comments
        )
        if platform_comment is not None
    ]
    imported, skipped = _import_platform_comments(source, platform_comments, db)
    now = datetime.utcnow()
    if page_url and not source.video_url:
        source.video_url = page_url
    if page_title and not source.video_title:
        source.video_title = page_title[:240]
    source.sync_status = "已同步" if platform_comments else "采集为空"
    source.last_sync_at = now
    source.last_error = None
    db.commit()
    total_comments = _source_comment_count(source.id, db)
    detected = len(platform_comments)
    return {
        "sourceId": source.id,
        "imported": imported,
        "skipped": skipped,
        "totalComments": total_comments,
        "message": (
            f"浏览器登录采集完成：当前内置页识别 {detected} 条评论，"
            f"新增 {imported} 条，跳过 {skipped} 条重复评论。"
        ),
    }


@router.get("/comments", response_model=list[SocialCommentRead])
def list_social_comments(
    source_id: str | None = Query(default=None, alias="sourceId"),
    platform: str | None = None,
    status: str | None = None,
    intent_level: str | None = Query(default=None, alias="intentLevel"),
    db: Session = Depends(get_db),
) -> list[SocialComment]:
    stmt = select(SocialComment).order_by(SocialComment.intent_score.desc(), SocialComment.created_at.desc())
    if source_id:
        stmt = stmt.where(SocialComment.source_id == source_id)
    if platform:
        stmt = stmt.where(SocialComment.platform == platform)
    if status:
        stmt = stmt.where(SocialComment.status == status)
    if intent_level:
        stmt = stmt.where(SocialComment.intent_level == intent_level)
    return list(db.scalars(stmt).all())


@router.post("/comments/convert", response_model=CommentConvertResult)
def convert_comments_to_leads(payload: CommentConvertRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    unique_comment_ids = list(dict.fromkeys(payload.comment_ids))
    comments = list(db.scalars(select(SocialComment).where(SocialComment.id.in_(unique_comment_ids))).all())
    if len(comments) != len(unique_comment_ids):
        raise HTTPException(status_code=400, detail="包含不存在的评论")

    converted = 0
    skipped = 0
    lead_ids: list[str] = []
    for comment in comments:
        existing_conversion = db.scalar(select(CommentLeadConversion).where(CommentLeadConversion.comment_id == comment.id))
        if existing_conversion:
            skipped += 1
            if existing_conversion.lead_id not in lead_ids:
                lead_ids.append(existing_conversion.lead_id)
            continue

        lead = db.scalar(
            select(MerchantLead).where(
                MerchantLead.platform == comment.platform,
                MerchantLead.platform_url == comment.author_profile_url,
                MerchantLead.source == "评论截流",
            )
        )
        if not lead:
            lead = MerchantLead(
                name=comment.author_name,
                platform=comment.platform,
                city=comment.city if comment.city != "待识别" else payload.city,
                category=comment.category if comment.category != "待识别" else payload.category,
                phone=None,
                contact_name=comment.author_name,
                platform_url=comment.author_profile_url,
                source="评论截流",
                intent_score=comment.intent_score,
                status=payload.status,
            )
            db.add(lead)
            db.flush()
            converted += 1
        else:
            skipped += 1

        conversion = CommentLeadConversion(
            comment_id=comment.id,
            lead_id=lead.id,
            action="转线索",
            status="已完成",
            note=f"从{comment.platform}评论截流转入线索库",
        )
        db.add(conversion)
        comment.status = "已转线索"
        if lead.id not in lead_ids:
            lead_ids.append(lead.id)

    db.commit()
    return {
        "converted": converted,
        "skipped": skipped,
        "leadIds": lead_ids,
        "message": f"已新增 {converted} 条线索，复用/跳过 {skipped} 条。",
    }
