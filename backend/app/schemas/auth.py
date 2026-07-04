from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel as BaseModel


class AuthUserRead(BaseModel):
    id: str
    username: str
    display_name: Annotated[str, Field(alias="displayName")]
    email: str | None
    phone: str | None
    status: str
    roles: list[str]
    last_login_at: Annotated[datetime | None, Field(alias="lastLoginAt")]
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: Annotated[str, Field(alias="accessToken")]
    token_type: Annotated[str, Field(alias="tokenType")] = "bearer"
    expires_in: Annotated[int, Field(alias="expiresIn")]
    user: AuthUserRead

    model_config = ConfigDict(populate_by_name=True)


class RegistrationRequestCreate(BaseModel):
    project_name: Annotated[str, Field(min_length=1, max_length=120, alias="projectName")]
    company_name: Annotated[str, Field(min_length=1, max_length=160, alias="companyName")]
    contact_name: Annotated[str | None, Field(max_length=80, alias="contactName")] = None
    contact_phone: Annotated[str, Field(min_length=1, max_length=40, alias="contactPhone")]
    contact_email: Annotated[str | None, Field(max_length=120, alias="contactEmail")] = None
    desired_username: Annotated[str | None, Field(max_length=80, alias="desiredUsername")] = None
    password: Annotated[str, Field(min_length=8, max_length=128)]
    note: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class RegistrationRequestRead(BaseModel):
    id: str
    project_name: Annotated[str, Field(alias="projectName")]
    company_name: Annotated[str, Field(alias="companyName")]
    contact_name: Annotated[str | None, Field(alias="contactName")]
    contact_phone: Annotated[str, Field(alias="contactPhone")]
    contact_email: Annotated[str | None, Field(alias="contactEmail")]
    desired_username: Annotated[str | None, Field(alias="desiredUsername")]
    note: str | None
    status: str
    created_at: Annotated[datetime, Field(alias="createdAt")]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
