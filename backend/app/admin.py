from pathlib import Path
from datetime import datetime
from secrets import compare_digest

from fastapi import FastAPI, Request
from markupsafe import Markup
from sqlalchemy import func, select
from sqladmin import Admin, Flash, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqladmin.forms import ModelConverter
from sqladmin.widgets import BooleanInputWidget, FileInputWidget
from starlette.responses import RedirectResponse
from wtforms import PasswordField
from wtforms.validators import InputRequired, Optional

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.session import SessionLocal, engine
from app.models.audit import AuditLog
from app.models.lead import MerchantLead
from app.models.task import OutreachTask
from app.models.user import AdminUser, RegistrationRequest, Role, User, UserRole
from app.services.registration import (
    RegistrationReviewError,
    approve_registration_request,
    reject_registration_request,
)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


# SQLAdmin's BooleanInputWidget misses this attribute with the current WTForms
# version, which breaks create/edit pages for boolean model fields.
if not hasattr(BooleanInputWidget, "validation_attrs"):
    BooleanInputWidget.validation_attrs = ["required", "disabled"]


class PasswordOptionalModelConverter(ModelConverter):
    def _prepare_column(self, prop, form_include_pk: bool, kwargs: dict):
        kwargs = super()._prepare_column(prop=prop, form_include_pk=form_include_pk, kwargs=kwargs)
        if kwargs is not None and prop.key == "password_hash":
            kwargs["validators"] = [
                validator for validator in kwargs["validators"] if not isinstance(validator, InputRequired)
            ]
        return kwargs


def _localized_file_input(self: FileInputWidget, field, **kwargs) -> Markup:
    if not field.flags.required:
        checkbox_id = f"{field.id}_checkbox"
        checkbox_label = Markup('<label class="form-check-label" for="{}">清除</label>').format(checkbox_id)
        checkbox_input = Markup('<input class="form-check-input" type="checkbox" id="{}" name="{}">').format(
            checkbox_id,
            checkbox_id,
        )
        checkbox = Markup('<div class="form-check">{}{}</div>').format(checkbox_input, checkbox_label)
    else:
        checkbox = Markup()

    if field.data:
        current_value = Markup("<p>当前文件：{}</p>").format(field.data)
        field.flags.required = False
        return current_value + checkbox + super(FileInputWidget, self).__call__(field, **kwargs)

    return super(FileInputWidget, self).__call__(field, **kwargs)


FileInputWidget.__call__ = _localized_file_input


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))

        with SessionLocal() as db:
            admin_user = db.scalar(select(AdminUser).where(AdminUser.username == username))
            admin_count = db.scalar(select(func.count(AdminUser.id))) or 0

            if (
                admin_user is None
                and admin_count == 0
                and compare_digest(username, settings.admin_username)
                and compare_digest(password, settings.admin_password)
            ):
                admin_user = AdminUser(
                    username=username,
                    display_name="系统管理员",
                    password_hash=hash_password(password),
                    status="启用",
                    is_superuser=True,
                )
                db.add(admin_user)
                db.commit()
                db.refresh(admin_user)

            if admin_user is None or admin_user.status != "启用":
                return False
            if not verify_password(password, admin_user.password_hash):
                return False

            admin_user.last_login_at = datetime.utcnow()
            db.commit()
            request.session.update(
                {
                    "admin_user_id": admin_user.id,
                    "admin_user": admin_user.username,
                },
            )
            return True

    async def logout(self, request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(request.url_for("admin:login"), status_code=302)

    async def authenticate(self, request: Request) -> bool:
        admin_user_id = request.session.get("admin_user_id")
        admin_username = request.session.get("admin_user")
        if not admin_user_id and not admin_username:
            return False

        with SessionLocal() as db:
            statement = select(AdminUser)
            if admin_user_id:
                statement = statement.where(AdminUser.id == admin_user_id)
            else:
                statement = statement.where(AdminUser.username == admin_username)
            admin_user = db.scalar(statement)
            return bool(admin_user and admin_user.status == "启用")


class MerchantLeadAdmin(ModelView, model=MerchantLead):
    name = "商家线索"
    name_plural = "商家线索库"
    icon = "fa-solid fa-store"

    column_list = [
        MerchantLead.name,
        MerchantLead.platform,
        MerchantLead.city,
        MerchantLead.category,
        MerchantLead.contact_name,
        MerchantLead.phone,
        MerchantLead.owner_user_id,
        MerchantLead.intent_score,
        MerchantLead.status,
        MerchantLead.follow_up_status,
        MerchantLead.source,
        MerchantLead.created_at,
        MerchantLead.updated_at,
    ]
    column_searchable_list = [
        MerchantLead.name,
        MerchantLead.phone,
        MerchantLead.contact_name,
        MerchantLead.city,
        MerchantLead.address,
        MerchantLead.platform_homepage_url,
    ]
    column_sortable_list = [
        MerchantLead.created_at,
        MerchantLead.updated_at,
        MerchantLead.intent_score,
        MerchantLead.city,
        MerchantLead.next_follow_up_at,
    ]
    column_default_sort = [(MerchantLead.created_at, True)]
    column_labels = {
        MerchantLead.name: "商家名称",
        MerchantLead.platform: "平台",
        MerchantLead.city: "城市",
        MerchantLead.category: "品类",
        MerchantLead.phone: "电话",
        MerchantLead.contact_name: "联系人",
        MerchantLead.contact_title: "联系人职务",
        MerchantLead.wechat_id: "微信号",
        MerchantLead.platform_homepage_url: "平台主页",
        MerchantLead.province: "省份",
        MerchantLead.district: "区县",
        MerchantLead.address: "地址",
        MerchantLead.source: "来源",
        MerchantLead.intent_score: "意向分",
        MerchantLead.status: "状态",
        MerchantLead.follow_up_status: "跟进状态",
        MerchantLead.remark: "备注",
        MerchantLead.owner_user_id: "负责人",
        MerchantLead.created_by_user_id: "创建人",
        MerchantLead.last_contact_at: "最近联系时间",
        MerchantLead.next_follow_up_at: "下次跟进时间",
        MerchantLead.created_at: "创建时间",
        MerchantLead.updated_at: "更新时间",
    }


class OutreachTaskAdmin(ModelView, model=OutreachTask):
    name = "触达任务"
    name_plural = "触达任务"
    icon = "fa-solid fa-phone-volume"

    column_list = [
        OutreachTask.name,
        OutreachTask.channel,
        OutreachTask.status,
        OutreachTask.target_count,
        OutreachTask.scheduled_at,
        OutreachTask.created_at,
    ]
    column_searchable_list = [OutreachTask.name, OutreachTask.channel, OutreachTask.status]
    column_sortable_list = [OutreachTask.created_at, OutreachTask.scheduled_at, OutreachTask.target_count]
    column_default_sort = [(OutreachTask.created_at, True)]
    column_labels = {
        OutreachTask.name: "任务名称",
        OutreachTask.channel: "触达方式",
        OutreachTask.status: "状态",
        OutreachTask.target_count: "目标数量",
        OutreachTask.scheduled_at: "预约时间",
        OutreachTask.created_at: "创建时间",
    }


class UserAdmin(ModelView, model=User):
    name = "用户"
    name_plural = "用户管理"
    icon = "fa-solid fa-user"

    column_list = [
        User.username,
        User.display_name,
        User.email,
        User.phone,
        User.status,
        User.is_superuser,
        User.last_login_at,
        User.created_at,
    ]
    column_searchable_list = [User.username, User.display_name, User.email, User.phone]
    column_sortable_list = [User.created_at, User.last_login_at, User.username]
    column_default_sort = [(User.created_at, True)]
    column_details_exclude_list = [User.password_hash]
    form_converter = PasswordOptionalModelConverter
    form_overrides = {"password_hash": PasswordField}
    form_widget_args = {
        "password_hash": {
            "autocomplete": "new-password",
            "placeholder": "编辑时留空表示不修改密码",
            "required": False,
        },
    }
    form_args = {
        "password_hash": {
            "label": "登录密码",
            "description": "新增用户必须填写；编辑用户时留空表示不修改密码。",
            "validators": [Optional()],
        },
    }
    column_labels = {
        User.username: "登录名",
        User.display_name: "姓名",
        User.email: "邮箱",
        User.phone: "手机号",
        User.password_hash: "登录密码",
        User.status: "状态",
        User.is_superuser: "超级管理员",
        User.last_login_at: "最近登录",
        User.created_at: "创建时间",
        User.updated_at: "更新时间",
    }

    async def on_model_change(self, data: dict, model: User, is_created: bool, request: Request) -> None:
        raw_password = str(data.get("password_hash") or "")
        if raw_password:
            data["password_hash"] = hash_password(raw_password)
            return

        if is_created:
            raise ValueError("请填写用户登录密码")

        data["password_hash"] = model.password_hash


class AdminUserAdmin(ModelView, model=AdminUser):
    name = "后台成员"
    name_plural = "后台成员"
    icon = "fa-solid fa-user-lock"

    column_list = [
        AdminUser.username,
        AdminUser.display_name,
        AdminUser.email,
        AdminUser.phone,
        AdminUser.status,
        AdminUser.is_superuser,
        AdminUser.last_login_at,
        AdminUser.created_at,
    ]
    column_searchable_list = [AdminUser.username, AdminUser.display_name, AdminUser.email, AdminUser.phone]
    column_sortable_list = [AdminUser.created_at, AdminUser.last_login_at, AdminUser.username]
    column_default_sort = [(AdminUser.created_at, True)]
    column_details_exclude_list = [AdminUser.password_hash]
    form_converter = PasswordOptionalModelConverter
    form_overrides = {"password_hash": PasswordField}
    form_widget_args = {
        "password_hash": {
            "autocomplete": "new-password",
            "placeholder": "编辑时留空表示不修改密码",
            "required": False,
        },
    }
    form_args = {
        "password_hash": {
            "label": "登录密码",
            "description": "新增成员必须填写；编辑成员时留空表示不修改密码。",
            "validators": [Optional()],
        },
    }
    column_labels = {
        AdminUser.username: "登录名",
        AdminUser.display_name: "姓名",
        AdminUser.email: "邮箱",
        AdminUser.phone: "手机号",
        AdminUser.password_hash: "登录密码",
        AdminUser.status: "状态",
        AdminUser.is_superuser: "超级管理员",
        AdminUser.last_login_at: "最近登录",
        AdminUser.created_at: "创建时间",
        AdminUser.updated_at: "更新时间",
    }

    async def on_model_change(self, data: dict, model: AdminUser, is_created: bool, request: Request) -> None:
        raw_password = str(data.get("password_hash") or "")
        if raw_password:
            data["password_hash"] = hash_password(raw_password)
            return

        if is_created:
            raise ValueError("请填写后台成员登录密码")

        data["password_hash"] = model.password_hash


class RoleAdmin(ModelView, model=Role):
    name = "角色"
    name_plural = "角色管理"
    icon = "fa-solid fa-users-gear"

    column_list = [Role.code, Role.name, Role.description, Role.is_system, Role.created_at]
    column_searchable_list = [Role.code, Role.name, Role.description]
    column_sortable_list = [Role.created_at, Role.code, Role.name]
    column_default_sort = [(Role.created_at, True)]
    column_labels = {
        Role.code: "角色编码",
        Role.name: "角色名称",
        Role.description: "说明",
        Role.is_system: "系统角色",
        Role.created_at: "创建时间",
        Role.updated_at: "更新时间",
    }


class UserRoleAdmin(ModelView, model=UserRole):
    name = "用户角色"
    name_plural = "用户角色分配"
    icon = "fa-solid fa-user-shield"

    column_list = [UserRole.user_id, UserRole.role_id, UserRole.created_at]
    column_sortable_list = [UserRole.created_at]
    column_default_sort = [(UserRole.created_at, True)]
    column_labels = {
        UserRole.user_id: "用户",
        UserRole.role_id: "角色",
        UserRole.created_at: "创建时间",
    }


class RegistrationRequestAdmin(ModelView, model=RegistrationRequest):
    name = "注册申请"
    name_plural = "注册申请"
    icon = "fa-solid fa-user-plus"

    column_list = [
        RegistrationRequest.company_name,
        RegistrationRequest.project_name,
        RegistrationRequest.contact_name,
        RegistrationRequest.contact_phone,
        RegistrationRequest.contact_email,
        RegistrationRequest.desired_username,
        RegistrationRequest.status,
        RegistrationRequest.created_at,
    ]
    column_searchable_list = [
        RegistrationRequest.company_name,
        RegistrationRequest.project_name,
        RegistrationRequest.contact_name,
        RegistrationRequest.contact_phone,
        RegistrationRequest.contact_email,
        RegistrationRequest.desired_username,
    ]
    column_sortable_list = [RegistrationRequest.created_at, RegistrationRequest.updated_at, RegistrationRequest.status]
    column_default_sort = [(RegistrationRequest.created_at, True)]
    column_labels = {
        RegistrationRequest.project_name: "客户/项目",
        RegistrationRequest.company_name: "公司名称",
        RegistrationRequest.contact_name: "联系人",
        RegistrationRequest.contact_phone: "联系人手机号",
        RegistrationRequest.contact_email: "联系人邮箱",
        RegistrationRequest.desired_username: "期望登录名",
        RegistrationRequest.note: "备注",
        RegistrationRequest.status: "状态",
        RegistrationRequest.reviewer_user_id: "审核人",
        RegistrationRequest.reviewed_at: "审核时间",
        RegistrationRequest.created_at: "创建时间",
        RegistrationRequest.updated_at: "更新时间",
    }

    def _action_redirect(self, request: Request) -> RedirectResponse:
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302)

    def _selected_ids(self, request: Request) -> list[str]:
        return [pk for pk in request.query_params.get("pks", "").split(",") if pk]

    @action(
        name="reject",
        label="驳回申请",
        confirmation_message="确认驳回选中的注册申请？",
        add_in_detail=True,
        add_in_list=True,
    )
    async def reject_requests(self, request: Request) -> RedirectResponse:
        selected_ids = self._selected_ids(request)
        if not selected_ids:
            Flash.warning(request, "请先选择要驳回的注册申请")
            return self._action_redirect(request)

        actor_username = request.session.get("admin_user")
        rejected_count = 0
        errors: list[str] = []
        for request_id in selected_ids:
            with SessionLocal() as db:
                try:
                    reject_registration_request(db, request_id, actor_username)
                    rejected_count += 1
                except RegistrationReviewError as exc:
                    errors.append(str(exc))

        if rejected_count:
            Flash.success(request, f"已驳回 {rejected_count} 条注册申请")
        if errors:
            Flash.error(request, "部分申请处理失败：" + "；".join(errors))
        return self._action_redirect(request)

    @action(
        name="approve",
        label="审核通过",
        confirmation_message="确认通过选中的注册申请并自动创建客户账号？",
        add_in_detail=True,
        add_in_list=True,
    )
    async def approve_requests(self, request: Request) -> RedirectResponse:
        selected_ids = self._selected_ids(request)
        if not selected_ids:
            Flash.warning(request, "请先选择要审核的注册申请")
            return self._action_redirect(request)

        actor_username = request.session.get("admin_user")
        approved_accounts: list[str] = []
        errors: list[str] = []
        for request_id in selected_ids:
            with SessionLocal() as db:
                try:
                    account = approve_registration_request(db, request_id, actor_username)
                    approved_accounts.append(f"{account.username}（初始密码：{account.initial_password}）")
                except RegistrationReviewError as exc:
                    errors.append(str(exc))

        if approved_accounts:
            Flash.success(request, "已通过申请并创建客户账号：" + "；".join(approved_accounts))
        if errors:
            Flash.error(request, "部分申请处理失败：" + "；".join(errors))
        return self._action_redirect(request)


class AuditLogAdmin(ModelView, model=AuditLog):
    name = "审计日志"
    name_plural = "审计日志"
    icon = "fa-solid fa-shield-halved"
    can_create = False
    can_edit = False
    can_delete = False

    column_list = [
        AuditLog.action,
        AuditLog.resource_type,
        AuditLog.resource_id,
        AuditLog.actor_username,
        AuditLog.ip_address,
        AuditLog.created_at,
    ]
    column_searchable_list = [
        AuditLog.action,
        AuditLog.resource_type,
        AuditLog.resource_id,
        AuditLog.actor_username,
        AuditLog.summary,
    ]
    column_sortable_list = [AuditLog.created_at, AuditLog.action, AuditLog.resource_type]
    column_default_sort = [(AuditLog.created_at, True)]
    column_labels = {
        AuditLog.actor_user_id: "操作用户",
        AuditLog.actor_username: "操作账号",
        AuditLog.action: "操作",
        AuditLog.resource_type: "资源类型",
        AuditLog.resource_id: "资源 ID",
        AuditLog.ip_address: "IP 地址",
        AuditLog.user_agent: "浏览器标识",
        AuditLog.summary: "摘要",
        AuditLog.created_at: "创建时间",
    }


def setup_admin(app: FastAPI) -> None:
    authentication_backend = AdminAuth(secret_key=settings.admin_secret_key, same_site="lax")
    admin = Admin(
        app,
        engine=engine,
        title="AI获客管理后台",
        base_url="/admin",
        templates_dir=str(TEMPLATES_DIR),
        authentication_backend=authentication_backend,
    )
    admin.add_view(MerchantLeadAdmin)
    admin.add_view(OutreachTaskAdmin)
    admin.add_view(AdminUserAdmin)
    admin.add_view(UserAdmin)
    admin.add_view(RegistrationRequestAdmin)
    admin.add_view(RoleAdmin)
    admin.add_view(UserRoleAdmin)
    admin.add_view(AuditLogAdmin)
