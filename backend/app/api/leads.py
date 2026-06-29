from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.lead import MerchantLead
from app.schemas.lead import LeadCreate, LeadRead

router = APIRouter()


@router.get("", response_model=list[LeadRead])
def list_leads(db: Session = Depends(get_db)) -> list[MerchantLead]:
    return list(db.scalars(select(MerchantLead).order_by(MerchantLead.created_at.desc())).all())


@router.post("", response_model=LeadRead)
def create_lead(payload: LeadCreate, db: Session = Depends(get_db)) -> MerchantLead:
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
        province=payload.province,
        district=payload.district,
        address=payload.address,
        source=payload.source,
        intent_score=payload.intent_score,
        status=payload.status,
        follow_up_status=payload.follow_up_status,
        remark=payload.remark,
        owner_user_id=payload.owner_user_id,
        created_by_user_id=payload.created_by_user_id,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead
