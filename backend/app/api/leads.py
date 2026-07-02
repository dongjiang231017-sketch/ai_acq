from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.lead import MerchantLead
from app.models.user import User
from app.schemas.lead import LeadCreate, LeadRead

router = APIRouter()


@router.get("", response_model=list[LeadRead])
def list_leads(
    source: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    city: str | None = Query(default=None),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MerchantLead]:
    statement = select(MerchantLead).where(
        MerchantLead.owner_user_id == current_user.id,
        MerchantLead.phone.is_not(None),
        MerchantLead.phone.not_in(["", "-"]),
    )
    if source:
        statement = statement.where(MerchantLead.source == source)
    if platform:
        statement = statement.where(MerchantLead.platform == platform)
    if city:
        statement = statement.where(MerchantLead.city.ilike(f"%{city}%"))
    if category:
        statement = statement.where(MerchantLead.category.ilike(f"%{category}%"))
    if status:
        statement = statement.where(MerchantLead.status == status)
    return list(db.scalars(statement.order_by(MerchantLead.created_at.desc())).all())


@router.post("", response_model=LeadRead)
def create_lead(
    payload: LeadCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MerchantLead:
    lead = MerchantLead(
        name=payload.name,
        platform=payload.platform,
        city=payload.city,
        category=payload.category,
        phone=payload.phone,
        contact_name=payload.contact_name,
        contact_title=payload.contact_title,
        wechat_id=payload.wechat_id,
        platform_homepage_url=payload.platform_homepage_url,
        source_poi_id=payload.source_poi_id,
        province=payload.province,
        district=payload.district,
        address=payload.address,
        longitude=payload.longitude,
        latitude=payload.latitude,
        source=payload.source,
        intent_score=payload.intent_score,
        status=payload.status,
        follow_up_status=payload.follow_up_status,
        remark=payload.remark,
        owner_user_id=current_user.id,
        created_by_user_id=current_user.id,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead
