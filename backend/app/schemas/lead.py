from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=40)
    city: str = Field(min_length=1, max_length=40)
    category: str = Field(min_length=1, max_length=80)
    phone: str | None = None
    contact_name: Annotated[str | None, Field(alias="contactName")] = None
    contact_title: Annotated[str | None, Field(alias="contactTitle")] = None
    wechat_id: Annotated[str | None, Field(alias="wechatId")] = None
    platform_homepage_url: Annotated[str | None, Field(alias="platformHomepageUrl")] = None
    source_poi_id: Annotated[str | None, Field(alias="sourcePoiId")] = None
    province: str | None = None
    district: str | None = None
    address: str | None = None
    longitude: str | None = None
    latitude: str | None = None
    source: str = "手动录入"
    intent_score: Annotated[int, Field(ge=0, le=100, alias="intentScore")] = 60
    status: str = "待外呼"
    follow_up_status: Annotated[str, Field(alias="followUpStatus")] = "未跟进"
    remark: str | None = None
    owner_user_id: Annotated[str | None, Field(alias="ownerUserId")] = None
    created_by_user_id: Annotated[str | None, Field(alias="createdByUserId")] = None

    model_config = ConfigDict(populate_by_name=True)


class LeadRead(BaseModel):
    id: str
    name: str
    platform: str
    city: str
    category: str
    phone: str | None
    contact_name: Annotated[str | None, Field(alias="contactName")]
    contact_title: Annotated[str | None, Field(alias="contactTitle")]
    wechat_id: Annotated[str | None, Field(alias="wechatId")]
    platform_homepage_url: Annotated[str | None, Field(alias="platformHomepageUrl")]
    source_poi_id: Annotated[str | None, Field(alias="sourcePoiId")]
    province: str | None
    district: str | None
    address: str | None
    longitude: str | None
    latitude: str | None
    source: str
    intent_score: Annotated[int, Field(alias="intentScore")]
    status: str
    follow_up_status: Annotated[str, Field(alias="followUpStatus")]
    remark: str | None
    owner_user_id: Annotated[str | None, Field(alias="ownerUserId")]
    created_by_user_id: Annotated[str | None, Field(alias="createdByUserId")]
    last_contact_at: Annotated[datetime | None, Field(alias="lastContactAt")]
    next_follow_up_at: Annotated[datetime | None, Field(alias="nextFollowUpAt")]
    created_at: Annotated[datetime, Field(alias="createdAt")]
    updated_at: Annotated[datetime, Field(alias="updatedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
