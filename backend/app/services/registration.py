from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.user import RegistrationRequest, User


class RegistrationReviewError(ValueError):
    pass


@dataclass(frozen=True)
class ApprovedAccount:
    username: str
    initial_password: str


def _initial_password(contact_phone: str) -> str:
    digits = "".join(char for char in contact_phone if char.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return "123456"


def _account_username(registration_request: RegistrationRequest) -> str:
    desired_username = (registration_request.desired_username or "").strip()
    if desired_username:
        return desired_username
    return registration_request.contact_phone.strip()[:80]


def _find_existing_user(db: Session, username: str, email: str | None, phone: str | None) -> User | None:
    conditions = [User.username == username]
    if email:
        conditions.append(User.email == email)
    if phone:
        conditions.append(User.phone == phone)
    return db.scalar(select(User).where(or_(*conditions)))


def approve_registration_request(db: Session, request_id: str, actor_username: str | None = None) -> ApprovedAccount:
    registration_request = db.get(RegistrationRequest, request_id)
    if registration_request is None:
        raise RegistrationReviewError("注册申请不存在")

    if registration_request.status == "已通过":
        raise RegistrationReviewError("该申请已审核通过")
    if registration_request.status == "已驳回":
        raise RegistrationReviewError("该申请已驳回，不能直接通过")

    username = _account_username(registration_request)
    email = registration_request.contact_email or None
    phone = registration_request.contact_phone or None
    existing_user = _find_existing_user(db, username=username, email=email, phone=phone)
    if existing_user is not None:
        raise RegistrationReviewError(f"客户账号已存在：{existing_user.username}")

    initial_password = _initial_password(registration_request.contact_phone)
    user = User(
        username=username,
        display_name=registration_request.contact_name or registration_request.company_name,
        email=email,
        phone=phone,
        password_hash=hash_password(initial_password),
        status="启用",
        is_superuser=False,
    )
    registration_request.status = "已通过"
    registration_request.reviewed_at = datetime.utcnow()
    registration_request.updated_at = datetime.utcnow()

    db.add(user)
    db.add(
        AuditLog(
            actor_username=actor_username,
            action="registration_request.approve",
            resource_type="registration_request",
            resource_id=registration_request.id,
            summary=f"通过注册申请并创建客户账号：{username}",
        ),
    )
    db.commit()
    return ApprovedAccount(username=username, initial_password=initial_password)


def reject_registration_request(db: Session, request_id: str, actor_username: str | None = None) -> None:
    registration_request = db.get(RegistrationRequest, request_id)
    if registration_request is None:
        raise RegistrationReviewError("注册申请不存在")

    if registration_request.status == "已通过":
        raise RegistrationReviewError("该申请已审核通过，不能驳回")
    if registration_request.status == "已驳回":
        raise RegistrationReviewError("该申请已驳回")

    registration_request.status = "已驳回"
    registration_request.reviewed_at = datetime.utcnow()
    registration_request.updated_at = datetime.utcnow()
    db.add(
        AuditLog(
            actor_username=actor_username,
            action="registration_request.reject",
            resource_type="registration_request",
            resource_id=registration_request.id,
            summary=f"驳回注册申请：{registration_request.company_name}",
        ),
    )
    db.commit()
