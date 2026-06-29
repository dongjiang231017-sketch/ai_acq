from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, read_access_token, verify_password
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.user import RegistrationRequest, User
from app.schemas.auth import (
    AuthUserRead,
    LoginRequest,
    LoginResponse,
    RegistrationRequestCreate,
    RegistrationRequestRead,
)

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def _read_user(user: User) -> AuthUserRead:
    return AuthUserRead(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        phone=user.phone,
        status=user.status,
        roles=[role.code for role in user.roles],
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = read_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态内容无效")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在或已删除")
    if user.status != "启用":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用，请联系管理员")
    return user


@router.get("/me", response_model=AuthUserRead)
def read_me(current_user: User = Depends(get_current_user)) -> AuthUserRead:
    return _read_user(current_user)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    identifier = payload.identifier.strip()
    user = db.scalar(
        select(User).where(or_(User.username == identifier, User.email == identifier, User.phone == identifier)),
    )

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")

    if user.status != "启用":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用，请联系管理员")

    user.last_login_at = datetime.utcnow()
    db.add(
        AuditLog(
            actor_user_id=user.id,
            actor_username=user.username,
            action="login",
            resource_type="user",
            resource_id=user.id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            summary="客户工作台登录",
        ),
    )
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.id, "username": user.username})
    return LoginResponse(
        access_token=token,
        expires_in=settings.access_token_expire_seconds,
        user=_read_user(user),
    )


@router.post(
    "/registration-requests",
    response_model=RegistrationRequestRead,
    status_code=status.HTTP_201_CREATED,
)
def create_registration_request(
    payload: RegistrationRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> RegistrationRequest:
    desired_username = payload.desired_username.strip() if payload.desired_username else None
    contact_email = payload.contact_email.strip() if payload.contact_email else None
    contact_phone = payload.contact_phone.strip()

    user_conditions = [User.phone == contact_phone]
    if contact_email:
        user_conditions.append(User.email == contact_email)
    if desired_username:
        user_conditions.append(User.username == desired_username)

    existing_user = db.scalar(select(User).where(or_(*user_conditions)))
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该联系方式或账号已存在")

    pending_conditions = [
        RegistrationRequest.contact_phone == contact_phone,
    ]
    if contact_email:
        pending_conditions.append(RegistrationRequest.contact_email == contact_email)
    if desired_username:
        pending_conditions.append(RegistrationRequest.desired_username == desired_username)

    existing_request = db.scalar(
        select(RegistrationRequest).where(
            RegistrationRequest.status.in_(["待审核", "处理中"]),
            or_(*pending_conditions),
        ),
    )
    if existing_request is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已有待审核的开通申请")

    registration_request = RegistrationRequest(
        project_name=payload.project_name.strip(),
        company_name=payload.company_name.strip(),
        contact_name=payload.contact_name.strip() if payload.contact_name else None,
        contact_phone=contact_phone,
        contact_email=contact_email,
        desired_username=desired_username,
        note=payload.note,
    )
    db.add(registration_request)
    db.flush()
    db.add(
        AuditLog(
            action="registration_request.create",
            resource_type="registration_request",
            resource_id=registration_request.id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            summary=f"{registration_request.company_name} 提交账号开通申请",
        ),
    )
    db.commit()
    db.refresh(registration_request)
    return registration_request
