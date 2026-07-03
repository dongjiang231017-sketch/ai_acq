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
