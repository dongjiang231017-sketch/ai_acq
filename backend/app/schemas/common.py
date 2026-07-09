from datetime import datetime, timezone

from pydantic import BaseModel, field_serializer


class ApiModel(BaseModel):
    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_datetimes_as_utc(self, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat().replace("+00:00", "Z")
        return value


# ---- 通用分页信封（2026-07-09）----
# 记录列表类接口统一返回 {items, total, page, pageSize}。
# 不传分页参数时 pageSize 默认取大值，兼容旧前端一次拿全量的用法。

from typing import Generic, TypeVar  # noqa: E402

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    pageSize: int


def paginate(total: int, page: int, page_size: int) -> tuple[int, int]:
    """返回 (offset, 修正后的 page)。page 越界时收敛到合法范围。"""
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), pages)
    return (page - 1) * page_size, page
