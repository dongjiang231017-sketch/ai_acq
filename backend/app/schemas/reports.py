from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel as BaseModel


class ReportFunnelStep(BaseModel):
    key: str
    label: str
    value: int
    rate: int


class ReportOverview(BaseModel):
    total_leads: Annotated[int, Field(alias="totalLeads")]
    total_touches: Annotated[int, Field(alias="totalTouches")]
    connected: int
    high_intent: Annotated[int, Field(alias="highIntent")]
    pending_work_orders: Annotated[int, Field(alias="pendingWorkOrders")]
    conversion_rate: Annotated[int, Field(alias="conversionRate")]
    export_jobs: Annotated[int, Field(alias="exportJobs")]
    funnel: list[ReportFunnelStep]
    updated_at: Annotated[datetime, Field(alias="updatedAt")]

    model_config = ConfigDict(populate_by_name=True)


class ChannelReport(BaseModel):
    id: str
    channel: str
    leads: int
    touches: int
    connected: int
    intent: int
    handoff: int
    conversion_rate: Annotated[int, Field(alias="conversionRate")]
    status: str
    insight: str

    model_config = ConfigDict(populate_by_name=True)


class SalesPerformanceReport(BaseModel):
    id: str
    owner_name: Annotated[str, Field(alias="ownerName")]
    assigned_customers: Annotated[int, Field(alias="assignedCustomers")]
    pending_work_orders: Annotated[int, Field(alias="pendingWorkOrders")]
    closed_work_orders: Annotated[int, Field(alias="closedWorkOrders")]
    high_intent: Annotated[int, Field(alias="highIntent")]
    handoff: int
    conversion_rate: Annotated[int, Field(alias="conversionRate")]
    last_activity_at: Annotated[datetime | None, Field(alias="lastActivityAt")]

    model_config = ConfigDict(populate_by_name=True)


class ReportExportCreate(BaseModel):
    report_type: Annotated[str, Field(alias="reportType")] = "经营总览"
    date_range: Annotated[str, Field(alias="dateRange")] = "近30天"
    file_format: Annotated[str, Field(alias="fileFormat")] = "xlsx"
    requester: str = "运营管理员"
    include_sensitive_fields: Annotated[bool, Field(alias="includeSensitiveFields")] = False

    model_config = ConfigDict(populate_by_name=True)


class ReportExportRead(BaseModel):
    id: str
    report_type: Annotated[str, Field(alias="reportType")]
    date_range: Annotated[str, Field(alias="dateRange")]
    file_format: Annotated[str, Field(alias="fileFormat")]
    requester: str
    status: str
    download_url: Annotated[str, Field(alias="downloadUrl")]
    row_count: Annotated[int, Field(alias="rowCount")]
    sensitive_fields_included: Annotated[bool, Field(alias="sensitiveFieldsIncluded")]
    created_at: Annotated[datetime, Field(alias="createdAt")]
    finished_at: Annotated[datetime | None, Field(alias="finishedAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
