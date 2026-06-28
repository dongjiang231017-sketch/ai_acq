from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


TaskChannel = Literal["collector", "call", "dm"]


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    channel: TaskChannel
    target_count: Annotated[int, Field(ge=0, alias="targetCount")] = 0
    scheduled_at: Annotated[datetime | None, Field(alias="scheduledAt")] = None


class TaskRead(BaseModel):
    id: str
    name: str
    channel: TaskChannel
    status: str
    target_count: Annotated[int, Field(alias="targetCount")]
    scheduled_at: Annotated[datetime | None, Field(alias="scheduledAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
