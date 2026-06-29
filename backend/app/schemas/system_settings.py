from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class SettingsGroupOverview(BaseModel):
    group_key: Annotated[str, Field(alias="groupKey")]
    label: str
    total: int
    enabled: int
    warning: int

    model_config = ConfigDict(populate_by_name=True)


class SettingsOverview(BaseModel):
    total_settings: Annotated[int, Field(alias="totalSettings")]
    enabled_settings: Annotated[int, Field(alias="enabledSettings")]
    warning_settings: Annotated[int, Field(alias="warningSettings")]
    sensitive_settings: Annotated[int, Field(alias="sensitiveSettings")]
    audit_logs: Annotated[int, Field(alias="auditLogs")]
    groups: list[SettingsGroupOverview]

    model_config = ConfigDict(populate_by_name=True)


class SystemSettingUpdate(BaseModel):
    value: str | None = None
    status: str | None = None
    description: str | None = None
    actor: str = "运营管理员"


class SystemSettingRead(BaseModel):
    id: str
    group_key: Annotated[str, Field(alias="groupKey")]
    item_key: Annotated[str, Field(alias="itemKey")]
    label: str
    value: str
    value_type: Annotated[str, Field(alias="valueType")]
    status: str
    description: str
    sensitive: bool
    updated_by: Annotated[str, Field(alias="updatedBy")]
    created_at: Annotated[datetime, Field(alias="createdAt")]
    updated_at: Annotated[datetime, Field(alias="updatedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SystemAuditLogRead(BaseModel):
    id: str
    actor: str
    action: str
    target_type: Annotated[str, Field(alias="targetType")]
    target_id: Annotated[str | None, Field(alias="targetId")]
    summary: str
    before_value: Annotated[str | None, Field(alias="beforeValue")]
    after_value: Annotated[str | None, Field(alias="afterValue")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
