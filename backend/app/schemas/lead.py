from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=40)
    city: str = Field(min_length=1, max_length=40)
    category: str = Field(min_length=1, max_length=80)
    phone: str | None = None
    contact_name: Annotated[str | None, Field(alias="contactName")] = None
    platform_url: Annotated[str | None, Field(alias="platformUrl")] = None
    source: str = "手动录入"

    model_config = ConfigDict(populate_by_name=True)


class LeadRead(BaseModel):
    id: str
    name: str
    platform: str
    city: str
    category: str
    phone: str | None
    contact_name: Annotated[str | None, Field(alias="contactName")]
    platform_url: Annotated[str | None, Field(alias="platformUrl")]
    source: str
    intent_score: Annotated[int, Field(alias="intentScore")]
    status: str

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
