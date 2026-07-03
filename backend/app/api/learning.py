from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.growth import KnowledgeBaseItem, LearningExperiment, LearningSuggestion
from app.models.task import CallRecord, DirectMessageConversation
from app.schemas.learning import (
    KnowledgeBaseItemRead,
    LearningExperimentRead,
    LearningOverview,
    LearningSuggestionCreate,
    LearningSuggestionRead,
    LearningSuggestionUpdate,
)

router = APIRouter()


def _seed_learning_assets(db: Session) -> None:
    has_suggestions = db.scalar(select(func.count()).select_from(LearningSuggestion)) or 0
    if not has_suggestions:
        call = db.scalar(select(CallRecord).order_by(CallRecord.created_at.desc()))
        conversation = db.scalar(select(DirectMessageConversation).order_by(DirectMessageConversation.created_at.desc()))
        suggestions = [
            LearningSuggestion(
                source_type="call_record" if call else "manual",
                source_record_id=call.id if call else None,
                target_type="外呼话术",
                title="补强价格异议后的案例承接",
                summary="客户追问费用时，先给低风险试跑路径，再引导人工顾问发送资料。",
                proposed_content="遇到价格异议时，先说明可从基础入驻和活动试跑开始，再询问是否愿意接收同城案例。",
                evidence_text=call.transcript if call else "旧 UI 需求要求 AI 只生成建议，人工审核后再灰度发布。",
                status="待审核",
                impact_score=76,
            ),
            LearningSuggestion(
                source_type="dm_conversation" if conversation else "manual",
                source_record_id=conversation.id if conversation else None,
                target_type="私信模板",
                title="私信首句增加商家品类和城市上下文",
                summary="首轮私信需要减少模板感，优先呈现城市、品类和平台来源。",
                proposed_content="您好，看到{城市}{品类}商家{商家名称}适合做视频号团购曝光，想了解下您是否考虑新增线上获客渠道？",
                evidence_text=conversation.last_message if conversation else "平台私信需求要求保留人工审核和模板版本。",
                status="待审核",
                impact_score=68,
            ),
        ]
        db.add_all(suggestions)

    has_knowledge = db.scalar(select(func.count()).select_from(KnowledgeBaseItem)) or 0
    if not has_knowledge:
        db.add(
            KnowledgeBaseItem(
                title="视频号团购入驻基础答疑",
                category="产品资料",
                content="覆盖入驻条件、试跑方式、资料清单、费用说明和人工顾问交接边界。",
                status="已发布",
                version="v1",
            )
        )

    has_experiments = db.scalar(select(func.count()).select_from(LearningExperiment)) or 0
    if not has_experiments:
        db.add(
            LearningExperiment(
                name="价格异议话术灰度实验",
                target_type="外呼话术",
                status="计划中",
                hypothesis="先给基础试跑路径可以降低价格异议流失。",
                variant="A: 标准价格解释；B: 基础试跑加同城案例。",
                sample_size=0,
                success_metric="A/B 级意向率",
                result_summary="等待人工审核建议后开始灰度。",
            )
        )
    db.commit()


@router.get("/overview", response_model=LearningOverview)
def learning_overview(db: Session = Depends(get_db)) -> dict[str, int]:
    _seed_learning_assets(db)
    suggestions = db.scalar(select(func.count()).select_from(LearningSuggestion)) or 0
    pending = db.scalar(select(func.count()).select_from(LearningSuggestion).where(LearningSuggestion.status == "待审核")) or 0
    approved = db.scalar(select(func.count()).select_from(LearningSuggestion).where(LearningSuggestion.status.in_(["已通过", "已发布"]))) or 0
    published = db.scalar(select(func.count()).select_from(LearningSuggestion).where(LearningSuggestion.status == "已发布")) or 0
    knowledge = db.scalar(select(func.count()).select_from(KnowledgeBaseItem)) or 0
    experiments = db.scalar(select(func.count()).select_from(LearningExperiment).where(LearningExperiment.status.in_(["运行中", "计划中"]))) or 0
    return {
        "suggestions": int(suggestions),
        "pending": int(pending),
        "approved": int(approved),
        "published": int(published),
        "knowledgeItems": int(knowledge),
        "activeExperiments": int(experiments),
    }


@router.get("/suggestions", response_model=list[LearningSuggestionRead])
def list_learning_suggestions(db: Session = Depends(get_db)) -> list[LearningSuggestion]:
    _seed_learning_assets(db)
    return list(db.scalars(select(LearningSuggestion).order_by(LearningSuggestion.created_at.desc())).all())


@router.post("/suggestions", response_model=LearningSuggestionRead)
def create_learning_suggestion(payload: LearningSuggestionCreate, db: Session = Depends(get_db)) -> LearningSuggestion:
    suggestion = LearningSuggestion(**payload.model_dump(by_alias=False))
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    return suggestion


@router.patch("/suggestions/{suggestion_id}", response_model=LearningSuggestionRead)
def update_learning_suggestion(
    suggestion_id: str, payload: LearningSuggestionUpdate, db: Session = Depends(get_db)
) -> LearningSuggestion:
    suggestion = db.get(LearningSuggestion, suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=404, detail="学习建议不存在")
    values = payload.model_dump(exclude_unset=True, by_alias=False)
    for field, value in values.items():
        setattr(suggestion, field, value)
    if "status" in values and values["status"] in {"已通过", "已拒绝"}:
        suggestion.reviewed_at = datetime.utcnow()
    if "status" in values and values["status"] == "已发布":
        suggestion.published_at = datetime.utcnow()
        suggestion.rollback_point = suggestion.rollback_point or f"{suggestion.target_type} 发布前版本"
    db.commit()
    db.refresh(suggestion)
    return suggestion


@router.get("/knowledge", response_model=list[KnowledgeBaseItemRead])
def list_knowledge_base(db: Session = Depends(get_db)) -> list[KnowledgeBaseItem]:
    _seed_learning_assets(db)
    return list(db.scalars(select(KnowledgeBaseItem).order_by(KnowledgeBaseItem.updated_at.desc())).all())


@router.get("/experiments", response_model=list[LearningExperimentRead])
def list_learning_experiments(db: Session = Depends(get_db)) -> list[LearningExperiment]:
    _seed_learning_assets(db)
    return list(db.scalars(select(LearningExperiment).order_by(LearningExperiment.created_at.desc())).all())
