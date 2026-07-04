import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from secrets import choice, compare_digest, token_hex
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from sqlalchemy import func, select
from sqladmin import Admin, Flash, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqladmin.forms import ModelConverter
from sqladmin.widgets import BooleanInputWidget
from starlette.responses import RedirectResponse
from wtforms import PasswordField
from wtforms.validators import InputRequired, Optional

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.session import SessionLocal, engine
from app.models.audit import AuditLog
from app.models.collection import LeadCollectionRun, LeadCollectionTask, LeadProviderConfig, PlatformBrowserSession, RawLeadRecord
from app.models.delivery import VoiceGatewayDeviceDiscovery, VoiceGatewayLine, VoiceGatewayLineEvent
from app.models.growth import (
    FollowUpWorkOrder,
    IntentCustomer,
    IntentEvent,
    KnowledgeBaseItem,
    LearningExperiment,
    LearningSuggestion,
    VoiceCloneRecord,
    VoiceProfile,
    VoiceSample,
    VoiceTrainingJob,
    VoiceUsageRecord,
)
from app.models.user import AdminUser, RegistrationRequest, Role, User, UserRole
from app.models.lead import MerchantLead
from app.models.operations import ReportExport, SystemAuditLog, SystemSetting
from app.models.task import (
    CallRecord,
    CallScript,
    CommentInterceptSource,
    CommentLeadConversion,
    DirectMessage,
    DirectMessageAccount,
    DirectMessageConversation,
    DirectMessagePlatformConfig,
    DirectMessageTemplate,
    OutreachTask,
    RecallRule,
    SocialComment,
)
from app.services.platform_browser import (
    BrowserSessionError,
    clear_platform_browser_session,
    open_platform_login_window,
    validate_platform_browser_session,
)
from app.services.registration import (
    RegistrationReviewError,
    approve_registration_request,
    reject_registration_request,
)
from app.services.voice_gateway_profiles import PROFILE_DEFAULTS


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
DEFAULT_SIP_SERVER_HOST = "101.132.63.159"
DEFAULT_CODEC_PRIMARY = "PCMA/alaw"
DEFAULT_CODEC_SECONDARY = "PCMU/ulaw"
DEFAULT_DTMF_MODE = "RFC2833/RFC4733"
DEFAULT_RTP_RANGE = "10000-20000/UDP"
DEFAULT_ROUTE_DIRECTION = "SIP中继/SIP -> VoLTE/GSM/SIM"
SECRET_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
ASTERISK_DYNAMIC_PJSIP_PATH = Path(
    os.getenv("AI_ACQ_ASTERISK_DYNAMIC_PJSIP_PATH", "/etc/asterisk/pjsip_ai_acq_delivery_dynamic.conf")
)
PROFILE_CHANNEL_DEFAULTS = {
    "dinstar_8t_server": 8,
    "multi_sim_lte_gateway": 8,
    "uc100_sip_volte": 1,
    "sip_volte_gateway": 1,
    "sip_trunk": 1,
}

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
        MerchantLead.platform_url,
        MerchantLead.intent_score,
        MerchantLead.status,
        MerchantLead.source,
        MerchantLead.created_at,
    ]
    column_searchable_list = [MerchantLead.name, MerchantLead.phone, MerchantLead.contact_name, MerchantLead.city]
    column_sortable_list = [MerchantLead.created_at, MerchantLead.intent_score, MerchantLead.city]
    column_default_sort = [(MerchantLead.created_at, True)]
    column_labels = {
        MerchantLead.name: "商家名称",
        MerchantLead.platform: "平台",
        MerchantLead.city: "城市",
        MerchantLead.category: "品类",
        MerchantLead.phone: "电话",
        MerchantLead.contact_name: "联系人",
        MerchantLead.platform_url: "平台店铺URL",
        MerchantLead.source: "来源",
        MerchantLead.intent_score: "意向分",
        MerchantLead.status: "状态",
        MerchantLead.created_at: "创建时间",
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
    column_searchable_list = [User.username, User.display_name, User.phone, User.email]
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
    column_details_exclude_list = [RegistrationRequest.password_hash]
    form_excluded_columns = [RegistrationRequest.password_hash]
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
                    if account.used_requested_password:
                        approved_accounts.append(f"{account.username}（使用客户申请时设置的密码）")
                    else:
                        approved_accounts.append(f"{account.username}（初始密码：{account.initial_password}）")
                except RegistrationReviewError as exc:
                    errors.append(str(exc))

        if approved_accounts:
            Flash.success(request, "已通过申请并创建客户账号：" + "；".join(approved_accounts))
        if errors:
            Flash.error(request, "部分申请处理失败：" + "；".join(errors))
        return self._action_redirect(request)


class LeadProviderConfigAdmin(ModelView, model=LeadProviderConfig):
    name = "接口配置"
    name_plural = "采集接口配置"
    icon = "fa-solid fa-key"

    column_list = [
        LeadProviderConfig.name,
        LeadProviderConfig.provider,
        LeadProviderConfig.enabled,
        LeadProviderConfig.daily_limit,
        LeadProviderConfig.qps_limit,
        LeadProviderConfig.updated_at,
    ]
    column_searchable_list = [LeadProviderConfig.name, LeadProviderConfig.provider, LeadProviderConfig.remark]
    column_sortable_list = [LeadProviderConfig.updated_at, LeadProviderConfig.provider]
    column_default_sort = [(LeadProviderConfig.updated_at, True)]
    column_details_exclude_list = [LeadProviderConfig.api_key, LeadProviderConfig.secret_key]
    form_overrides = {
        "api_key": PasswordField,
        "secret_key": PasswordField,
    }
    form_widget_args = {
        "api_key": {
            "autocomplete": "new-password",
            "placeholder": "编辑时留空表示不修改",
        },
        "secret_key": {
            "autocomplete": "new-password",
            "placeholder": "没有则留空；编辑时留空表示不修改",
        },
    }
    form_args = {
        "api_key": {
            "label": "访问密钥",
            "description": "地图平台填写访问密钥；平台公开页面采集来源可留空。",
            "validators": [Optional()],
        },
        "secret_key": {
            "label": "签名密钥",
            "description": "百度如果启用签名校验可填写；其他来源没有则留空。",
            "validators": [Optional()],
        },
    }
    column_labels = {
        LeadProviderConfig.provider: "平台编码",
        LeadProviderConfig.name: "平台名称",
        LeadProviderConfig.api_key: "访问密钥",
        LeadProviderConfig.secret_key: "签名密钥",
        LeadProviderConfig.service_url: "接口地址",
        LeadProviderConfig.enabled: "启用",
        LeadProviderConfig.daily_limit: "日限额",
        LeadProviderConfig.qps_limit: "QPS",
        LeadProviderConfig.remark: "备注",
        LeadProviderConfig.created_at: "创建时间",
        LeadProviderConfig.updated_at: "更新时间",
    }

    async def on_model_change(
        self,
        data: dict,
        model: LeadProviderConfig,
        is_created: bool,
        request: Request,
    ) -> None:
        if not is_created:
            if not data.get("api_key"):
                data["api_key"] = model.api_key
            if not data.get("secret_key"):
                data["secret_key"] = model.secret_key


class LeadCollectionTaskAdmin(ModelView, model=LeadCollectionTask):
    name = "采集任务"
    name_plural = "采集任务"
    icon = "fa-solid fa-magnifying-glass-location"

    column_list = [
        LeadCollectionTask.name,
        LeadCollectionTask.provider,
        LeadCollectionTask.cities,
        LeadCollectionTask.categories,
        LeadCollectionTask.keywords,
        LeadCollectionTask.target_per_keyword,
        LeadCollectionTask.status,
        LeadCollectionTask.last_run_status,
        LeadCollectionTask.created_at,
    ]
    column_searchable_list = [LeadCollectionTask.name, LeadCollectionTask.provider, LeadCollectionTask.status]
    column_sortable_list = [LeadCollectionTask.created_at, LeadCollectionTask.updated_at]
    column_default_sort = [(LeadCollectionTask.created_at, True)]


class LeadCollectionRunAdmin(ModelView, model=LeadCollectionRun):
    name = "采集运行"
    name_plural = "采集运行"
    icon = "fa-solid fa-rotate"

    can_create = False
    can_edit = False
    column_list = [
        LeadCollectionRun.task_id,
        LeadCollectionRun.provider,
        LeadCollectionRun.status,
        LeadCollectionRun.requested_count,
        LeadCollectionRun.fetched_count,
        LeadCollectionRun.inserted_count,
        LeadCollectionRun.duplicate_count,
        LeadCollectionRun.failed_count,
        LeadCollectionRun.started_at,
        LeadCollectionRun.finished_at,
    ]
    column_searchable_list = [LeadCollectionRun.provider, LeadCollectionRun.status, LeadCollectionRun.error_message]
    column_sortable_list = [LeadCollectionRun.started_at, LeadCollectionRun.finished_at]
    column_default_sort = [(LeadCollectionRun.started_at, True)]


class RawLeadRecordAdmin(ModelView, model=RawLeadRecord):
    name = "原始线索"
    name_plural = "原始采集线索"
    icon = "fa-solid fa-database"

    can_create = False
    can_edit = False
    column_list = [
        RawLeadRecord.name,
        RawLeadRecord.provider,
        RawLeadRecord.source_poi_id,
        RawLeadRecord.city,
        RawLeadRecord.category,
        RawLeadRecord.phone,
        RawLeadRecord.import_status,
        RawLeadRecord.created_at,
    ]
    column_searchable_list = [RawLeadRecord.name, RawLeadRecord.source_poi_id, RawLeadRecord.city, RawLeadRecord.phone]
    column_sortable_list = [RawLeadRecord.created_at, RawLeadRecord.city]
    column_default_sort = [(RawLeadRecord.created_at, True)]


class PlatformBrowserSessionAdmin(ModelView, model=PlatformBrowserSession):
    name = "浏览器登录态"
    name_plural = "平台浏览器登录态"
    icon = "fa-solid fa-desktop"

    can_create = False
    can_delete = False
    can_edit = False
    column_list = [
        PlatformBrowserSession.name,
        PlatformBrowserSession.provider,
        PlatformBrowserSession.status,
        PlatformBrowserSession.login_process_id,
        PlatformBrowserSession.last_login_started_at,
        PlatformBrowserSession.last_login_finished_at,
        PlatformBrowserSession.last_validated_at,
        PlatformBrowserSession.updated_at,
    ]
    column_searchable_list = [
        PlatformBrowserSession.name,
        PlatformBrowserSession.provider,
        PlatformBrowserSession.status,
        PlatformBrowserSession.last_error,
        PlatformBrowserSession.note,
    ]
    column_sortable_list = [
        PlatformBrowserSession.updated_at,
        PlatformBrowserSession.last_validated_at,
        PlatformBrowserSession.provider,
    ]
    column_default_sort = [(PlatformBrowserSession.updated_at, True)]
    column_labels = {
        PlatformBrowserSession.provider: "平台编码",
        PlatformBrowserSession.name: "平台名称",
        PlatformBrowserSession.login_url: "登录入口",
        PlatformBrowserSession.home_url: "首页地址",
        PlatformBrowserSession.profile_dir: "本地配置目录",
        PlatformBrowserSession.status: "状态",
        PlatformBrowserSession.login_process_id: "登录进程 PID",
        PlatformBrowserSession.last_login_started_at: "最近打开窗口",
        PlatformBrowserSession.last_login_finished_at: "最近关闭窗口",
        PlatformBrowserSession.last_validated_at: "最近校验时间",
        PlatformBrowserSession.last_error: "最近错误",
        PlatformBrowserSession.note: "说明",
        PlatformBrowserSession.created_at: "创建时间",
        PlatformBrowserSession.updated_at: "更新时间",
    }

    def _action_redirect(self, request: Request) -> RedirectResponse:
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302)

    def _selected_ids(self, request: Request) -> list[str]:
        return [pk for pk in request.query_params.get("pks", "").split(",") if pk]

    @action(
        name="open-login",
        label="打开登录窗口",
        confirmation_message="确认打开选中平台的登录窗口？请在弹出的浏览器里手动登录，登录后直接关闭窗口。",
        add_in_detail=True,
        add_in_list=True,
    )
    async def open_login(self, request: Request) -> RedirectResponse:
        selected_ids = self._selected_ids(request)
        if not selected_ids:
            Flash.warning(request, "请先选择要登录的平台")
            return self._action_redirect(request)

        opened: list[str] = []
        errors: list[str] = []
        for session_id in selected_ids:
            with SessionLocal() as db:
                session = db.get(PlatformBrowserSession, session_id)
                if session is None:
                    errors.append(f"未找到记录：{session_id}")
                    continue
                try:
                    open_platform_login_window(db, session.provider)
                    opened.append(session.name)
                except BrowserSessionError as exc:
                    errors.append(str(exc))

        if opened:
            Flash.success(request, "已打开登录窗口：" + "；".join(opened))
        if errors:
            Flash.error(request, "部分平台处理失败：" + "；".join(errors))
        return self._action_redirect(request)

    @action(
        name="validate-session",
        label="校验登录态",
        confirmation_message="确认校验选中平台的本地登录态？",
        add_in_detail=True,
        add_in_list=True,
    )
    async def validate_login(self, request: Request) -> RedirectResponse:
        selected_ids = self._selected_ids(request)
        if not selected_ids:
            Flash.warning(request, "请先选择要校验的平台")
            return self._action_redirect(request)

        results: list[str] = []
        for session_id in selected_ids:
            with SessionLocal() as db:
                session = db.get(PlatformBrowserSession, session_id)
                if session is None:
                    continue
                validated = validate_platform_browser_session(db, session.provider)
                message = validated.name + "：" + validated.status
                if validated.last_error:
                    message += f"（{validated.last_error}）"
                results.append(message)

        if results:
            Flash.success(request, "；".join(results))
        return self._action_redirect(request)

    @action(
        name="clear-session",
        label="清空登录态",
        confirmation_message="确认删除选中平台的本地登录态目录？下次使用前需要重新登录。",
        add_in_detail=True,
        add_in_list=True,
    )
    async def clear_login(self, request: Request) -> RedirectResponse:
        selected_ids = self._selected_ids(request)
        if not selected_ids:
            Flash.warning(request, "请先选择要清空的平台")
            return self._action_redirect(request)

        cleared: list[str] = []
        errors: list[str] = []
        for session_id in selected_ids:
            with SessionLocal() as db:
                session = db.get(PlatformBrowserSession, session_id)
                if session is None:
                    errors.append(f"未找到记录：{session_id}")
                    continue
                try:
                    clear_platform_browser_session(db, session.provider)
                    cleared.append(session.name)
                except BrowserSessionError as exc:
                    errors.append(str(exc))

        if cleared:
            Flash.success(request, "已清空登录态：" + "；".join(cleared))
        if errors:
            Flash.error(request, "部分平台处理失败：" + "；".join(errors))
        return self._action_redirect(request)


class OutreachTaskAdmin(ModelView, model=OutreachTask):
    name = "触达任务"
    name_plural = "触达任务"
    icon = "fa-solid fa-phone-volume"

    column_list = [
        OutreachTask.name,
        OutreachTask.channel,
        OutreachTask.status,
        OutreachTask.target_count,
        OutreachTask.completed_count,
        OutreachTask.connected_count,
        OutreachTask.intent_count,
        OutreachTask.concurrency,
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
        OutreachTask.completed_count: "完成数量",
        OutreachTask.connected_count: "接通数量",
        OutreachTask.intent_count: "意向数量",
        OutreachTask.failed_count: "失败数量",
        OutreachTask.concurrency: "并发坐席",
        OutreachTask.script_id: "话术ID",
        OutreachTask.scheduled_at: "预约时间",
        OutreachTask.started_at: "开始时间",
        OutreachTask.finished_at: "完成时间",
        OutreachTask.created_at: "创建时间",
    }


class CallScriptAdmin(ModelView, model=CallScript):
    name = "外呼话术"
    name_plural = "外呼话术"
    icon = "fa-solid fa-comments"

    column_list = [CallScript.name, CallScript.is_active, CallScript.created_at]
    column_searchable_list = [CallScript.name, CallScript.opening, CallScript.qualification]
    column_sortable_list = [CallScript.created_at, CallScript.is_active]
    column_labels = {
        CallScript.name: "话术名称",
        CallScript.opening: "开场白",
        CallScript.qualification: "筛选问题",
        CallScript.objection: "异议处理",
        CallScript.closing: "收尾动作",
        CallScript.is_active: "启用",
        CallScript.created_at: "创建时间",
    }


class CallRecordAdmin(ModelView, model=CallRecord):
    name = "通话记录"
    name_plural = "通话记录"
    icon = "fa-solid fa-headset"

    column_list = [
        CallRecord.merchant_name,
        CallRecord.phone,
        CallRecord.ai_seat,
        CallRecord.duration_seconds,
        CallRecord.intent_level,
        CallRecord.current_node,
        CallRecord.outcome,
        CallRecord.gateway_status,
        CallRecord.need_handoff,
        CallRecord.recall_at,
        CallRecord.created_at,
    ]
    column_searchable_list = [CallRecord.merchant_name, CallRecord.phone, CallRecord.ai_seat, CallRecord.outcome]
    column_sortable_list = [CallRecord.created_at, CallRecord.duration_seconds, CallRecord.intent_level]
    column_default_sort = [(CallRecord.created_at, True)]
    column_labels = {
        CallRecord.merchant_name: "商家",
        CallRecord.phone: "电话",
        CallRecord.ai_seat: "AI坐席",
        CallRecord.duration_seconds: "通话时长",
        CallRecord.intent_level: "意向等级",
        CallRecord.current_node: "当前节点",
        CallRecord.outcome: "结果",
        CallRecord.transcript: "转写内容",
        CallRecord.gateway_call_id: "网关通话ID",
        CallRecord.gateway_status: "网关状态",
        CallRecord.raw_payload: "网关原始事件",
        CallRecord.need_handoff: "需人工接管",
        CallRecord.recall_at: "重拨时间",
        CallRecord.created_at: "创建时间",
    }


class RecallRuleAdmin(ModelView, model=RecallRule):
    name = "重拨规则"
    name_plural = "重拨规则"
    icon = "fa-solid fa-clock-rotate-left"

    column_list = [
        RecallRule.name,
        RecallRule.no_answer_interval_minutes,
        RecallRule.busy_interval_minutes,
        RecallRule.max_attempts,
        RecallRule.quiet_start,
        RecallRule.quiet_end,
        RecallRule.enabled,
    ]
    column_labels = {
        RecallRule.name: "规则名称",
        RecallRule.no_answer_interval_minutes: "未接间隔分钟",
        RecallRule.busy_interval_minutes: "忙线间隔分钟",
        RecallRule.max_attempts: "最大次数",
        RecallRule.quiet_start: "勿扰开始",
        RecallRule.quiet_end: "勿扰结束",
        RecallRule.enabled: "启用",
    }


class DirectMessageAccountAdmin(ModelView, model=DirectMessageAccount):
    name = "平台个人号"
    name_plural = "平台私信个人号"
    icon = "fa-solid fa-user-shield"

    column_list = [
        DirectMessageAccount.platform,
        DirectMessageAccount.account_name,
        DirectMessageAccount.login_label,
        DirectMessageAccount.status,
        DirectMessageAccount.session_status,
        DirectMessageAccount.risk_status,
        DirectMessageAccount.browser_profile_key,
        DirectMessageAccount.daily_limit,
        DirectMessageAccount.sent_today,
        DirectMessageAccount.last_sent_at,
        DirectMessageAccount.last_sync_at,
    ]
    column_searchable_list = [
        DirectMessageAccount.platform,
        DirectMessageAccount.account_name,
        DirectMessageAccount.status,
        DirectMessageAccount.session_status,
        DirectMessageAccount.risk_status,
    ]
    column_sortable_list = [DirectMessageAccount.created_at, DirectMessageAccount.sent_today, DirectMessageAccount.daily_limit]
    column_labels = {
        DirectMessageAccount.platform: "平台",
        DirectMessageAccount.account_name: "个人号名称",
        DirectMessageAccount.login_label: "个人号标识",
        DirectMessageAccount.status: "状态",
        DirectMessageAccount.browser_profile_key: "浏览器Profile",
        DirectMessageAccount.browser_profile_path: "Profile路径",
        DirectMessageAccount.session_status: "登录态",
        DirectMessageAccount.risk_status: "风险状态",
        DirectMessageAccount.daily_limit: "日上限",
        DirectMessageAccount.sent_today: "今日已发",
        DirectMessageAccount.min_send_interval_seconds: "最小发送间隔秒",
        DirectMessageAccount.cooldown_until: "冷却至",
        DirectMessageAccount.last_sent_at: "最近发送",
        DirectMessageAccount.last_sync_at: "最近同步",
        DirectMessageAccount.last_login_check_at: "最近登录检测",
        DirectMessageAccount.last_error: "错误原因",
        DirectMessageAccount.created_at: "创建时间",
    }


class DirectMessagePlatformConfigAdmin(ModelView, model=DirectMessagePlatformConfig):
    name = "平台选择器"
    name_plural = "平台私信选择器"
    icon = "fa-solid fa-code"

    column_list = [
        DirectMessagePlatformConfig.platform,
        DirectMessagePlatformConfig.home_url,
        DirectMessagePlatformConfig.inbox_url,
        DirectMessagePlatformConfig.enabled,
        DirectMessagePlatformConfig.created_at,
    ]
    column_searchable_list = [DirectMessagePlatformConfig.platform, DirectMessagePlatformConfig.home_url]
    column_sortable_list = [DirectMessagePlatformConfig.created_at, DirectMessagePlatformConfig.enabled]
    column_labels = {
        DirectMessagePlatformConfig.platform: "平台",
        DirectMessagePlatformConfig.home_url: "首页",
        DirectMessagePlatformConfig.inbox_url: "收件箱",
        DirectMessagePlatformConfig.merchant_search_url: "商家搜索页",
        DirectMessagePlatformConfig.login_check_selector: "登录态选择器",
        DirectMessagePlatformConfig.risk_check_selector: "风控选择器",
        DirectMessagePlatformConfig.merchant_link_selector: "商家结果选择器",
        DirectMessagePlatformConfig.message_button_selector: "私信按钮选择器",
        DirectMessagePlatformConfig.input_selector: "输入框选择器",
        DirectMessagePlatformConfig.send_button_selector: "发送按钮选择器",
        DirectMessagePlatformConfig.sent_success_selector: "发送成功选择器",
        DirectMessagePlatformConfig.unread_selector: "未读选择器",
        DirectMessagePlatformConfig.conversation_item_selector: "会话条目选择器",
        DirectMessagePlatformConfig.conversation_title_selector: "会话标题选择器",
        DirectMessagePlatformConfig.message_text_selector: "消息文本选择器",
        DirectMessagePlatformConfig.enabled: "启用",
        DirectMessagePlatformConfig.created_at: "创建时间",
    }


class DirectMessageTemplateAdmin(ModelView, model=DirectMessageTemplate):
    name = "私信模板"
    name_plural = "私信模板"
    icon = "fa-solid fa-message"

    column_list = [
        DirectMessageTemplate.name,
        DirectMessageTemplate.platform,
        DirectMessageTemplate.is_active,
        DirectMessageTemplate.created_at,
    ]
    column_searchable_list = [DirectMessageTemplate.name, DirectMessageTemplate.platform, DirectMessageTemplate.content]
    column_sortable_list = [DirectMessageTemplate.created_at, DirectMessageTemplate.is_active]
    column_labels = {
        DirectMessageTemplate.name: "模板名称",
        DirectMessageTemplate.platform: "适用平台",
        DirectMessageTemplate.content: "内容",
        DirectMessageTemplate.is_active: "启用",
        DirectMessageTemplate.created_at: "创建时间",
    }


class DirectMessageConversationAdmin(ModelView, model=DirectMessageConversation):
    name = "私信会话"
    name_plural = "私信会话"
    icon = "fa-solid fa-comments"

    column_list = [
        DirectMessageConversation.platform,
        DirectMessageConversation.merchant_name,
        DirectMessageConversation.status,
        DirectMessageConversation.intent_level,
        DirectMessageConversation.need_handoff,
        DirectMessageConversation.last_message_at,
        DirectMessageConversation.created_at,
    ]
    column_searchable_list = [
        DirectMessageConversation.platform,
        DirectMessageConversation.merchant_name,
        DirectMessageConversation.status,
    ]
    column_sortable_list = [DirectMessageConversation.created_at, DirectMessageConversation.last_message_at]
    column_default_sort = [(DirectMessageConversation.created_at, True)]
    column_labels = {
        DirectMessageConversation.platform: "平台",
        DirectMessageConversation.merchant_name: "商家",
        DirectMessageConversation.status: "状态",
        DirectMessageConversation.intent_level: "意向等级",
        DirectMessageConversation.last_message: "最后消息",
        DirectMessageConversation.need_handoff: "需接管",
        DirectMessageConversation.last_message_at: "最后消息时间",
        DirectMessageConversation.created_at: "创建时间",
    }


class DirectMessageAdmin(ModelView, model=DirectMessage):
    name = "私信消息"
    name_plural = "私信消息"
    icon = "fa-solid fa-envelope-open-text"

    column_list = [
        DirectMessage.direction,
        DirectMessage.status,
        DirectMessage.external_message_id,
        DirectMessage.created_at,
    ]
    column_searchable_list = [DirectMessage.direction, DirectMessage.status, DirectMessage.content]
    column_sortable_list = [DirectMessage.created_at]
    column_default_sort = [(DirectMessage.created_at, True)]
    column_labels = {
        DirectMessage.direction: "方向",
        DirectMessage.content: "内容",
        DirectMessage.status: "状态",
        DirectMessage.external_message_id: "平台消息ID",
        DirectMessage.raw_payload: "原始事件",
        DirectMessage.created_at: "创建时间",
    }


class CommentInterceptSourceAdmin(ModelView, model=CommentInterceptSource):
    name = "评论截流源"
    name_plural = "评论截流源"
    icon = "fa-solid fa-filter"

    column_list = [
        CommentInterceptSource.platform,
        CommentInterceptSource.source_type,
        CommentInterceptSource.name,
        CommentInterceptSource.sync_status,
        CommentInterceptSource.last_sync_at,
        CommentInterceptSource.created_at,
    ]
    column_searchable_list = [CommentInterceptSource.platform, CommentInterceptSource.name, CommentInterceptSource.keyword]
    column_sortable_list = [CommentInterceptSource.created_at, CommentInterceptSource.last_sync_at]
    column_default_sort = [(CommentInterceptSource.created_at, True)]
    column_labels = {
        CommentInterceptSource.platform: "平台",
        CommentInterceptSource.source_type: "来源类型",
        CommentInterceptSource.name: "来源名称",
        CommentInterceptSource.keyword: "关键词",
        CommentInterceptSource.video_url: "视频URL",
        CommentInterceptSource.video_title: "视频标题",
        CommentInterceptSource.owner_account_id: "归属个人号",
        CommentInterceptSource.sync_status: "同步状态",
        CommentInterceptSource.sync_frequency_minutes: "同步间隔分钟",
        CommentInterceptSource.keyword_rules: "意向关键词",
        CommentInterceptSource.auto_reply_enabled: "自动回复",
        CommentInterceptSource.human_confirm_required: "人工确认",
        CommentInterceptSource.last_sync_at: "最近同步",
        CommentInterceptSource.last_error: "错误原因",
        CommentInterceptSource.created_at: "创建时间",
    }


class SocialCommentAdmin(ModelView, model=SocialComment):
    name = "截流评论"
    name_plural = "截流评论池"
    icon = "fa-solid fa-comment-dots"

    column_list = [
        SocialComment.platform,
        SocialComment.author_name,
        SocialComment.intent_level,
        SocialComment.intent_score,
        SocialComment.status,
        SocialComment.risk_status,
        SocialComment.commented_at,
        SocialComment.created_at,
    ]
    column_searchable_list = [SocialComment.platform, SocialComment.author_name, SocialComment.content]
    column_sortable_list = [SocialComment.intent_score, SocialComment.created_at, SocialComment.commented_at]
    column_default_sort = [(SocialComment.intent_score, True)]
    column_labels = {
        SocialComment.source_id: "截流源",
        SocialComment.platform: "平台",
        SocialComment.external_comment_id: "评论ID",
        SocialComment.video_url: "视频URL",
        SocialComment.author_name: "评论用户",
        SocialComment.author_profile_url: "用户主页",
        SocialComment.content: "评论内容",
        SocialComment.city: "城市",
        SocialComment.category: "品类",
        SocialComment.like_count: "点赞",
        SocialComment.reply_count: "回复",
        SocialComment.intent_score: "意向分",
        SocialComment.intent_level: "意向等级",
        SocialComment.status: "状态",
        SocialComment.risk_status: "风险",
        SocialComment.raw_payload: "原始数据",
        SocialComment.commented_at: "评论时间",
        SocialComment.created_at: "创建时间",
    }


class CommentLeadConversionAdmin(ModelView, model=CommentLeadConversion):
    name = "评论转线索"
    name_plural = "评论转线索记录"
    icon = "fa-solid fa-arrow-right-to-bracket"

    column_list = [
        CommentLeadConversion.comment_id,
        CommentLeadConversion.lead_id,
        CommentLeadConversion.action,
        CommentLeadConversion.status,
        CommentLeadConversion.created_at,
    ]
    column_searchable_list = [CommentLeadConversion.action, CommentLeadConversion.status, CommentLeadConversion.note]
    column_sortable_list = [CommentLeadConversion.created_at]
    column_labels = {
        CommentLeadConversion.comment_id: "评论ID",
        CommentLeadConversion.lead_id: "线索ID",
        CommentLeadConversion.action: "动作",
        CommentLeadConversion.status: "状态",
        CommentLeadConversion.note: "备注",
        CommentLeadConversion.created_at: "创建时间",
    }


class IntentCustomerAdmin(ModelView, model=IntentCustomer):
    name = "意向客户"
    name_plural = "意向客户池"
    icon = "fa-solid fa-user-check"

    column_list = [
        IntentCustomer.merchant_name,
        IntentCustomer.platform,
        IntentCustomer.city,
        IntentCustomer.intent_level,
        IntentCustomer.intent_score,
        IntentCustomer.owner_name,
        IntentCustomer.follow_status,
        IntentCustomer.need_handoff,
        IntentCustomer.dnc_status,
        IntentCustomer.updated_at,
    ]
    column_searchable_list = [IntentCustomer.merchant_name, IntentCustomer.phone, IntentCustomer.owner_name]
    column_sortable_list = [IntentCustomer.intent_score, IntentCustomer.updated_at]
    column_default_sort = [(IntentCustomer.updated_at, True)]
    column_labels = {
        IntentCustomer.merchant_name: "商家",
        IntentCustomer.platform: "平台",
        IntentCustomer.city: "城市",
        IntentCustomer.category: "品类",
        IntentCustomer.contact_name: "联系人",
        IntentCustomer.phone: "电话",
        IntentCustomer.intent_level: "意向等级",
        IntentCustomer.intent_score: "意向分",
        IntentCustomer.source_channels: "来源渠道",
        IntentCustomer.latest_signal: "最近信号",
        IntentCustomer.evidence_summary: "证据摘要",
        IntentCustomer.owner_name: "负责人",
        IntentCustomer.follow_status: "跟进状态",
        IntentCustomer.next_follow_at: "下次跟进",
        IntentCustomer.need_handoff: "需人工接管",
        IntentCustomer.dnc_status: "勿扰",
        IntentCustomer.created_at: "创建时间",
        IntentCustomer.updated_at: "更新时间",
    }


class IntentEventAdmin(ModelView, model=IntentEvent):
    name = "意向事件"
    name_plural = "意向证据事件"
    icon = "fa-solid fa-timeline"

    column_list = [
        IntentEvent.channel,
        IntentEvent.source_type,
        IntentEvent.intent_level,
        IntentEvent.summary,
        IntentEvent.need_handoff,
        IntentEvent.created_at,
    ]
    column_searchable_list = [IntentEvent.channel, IntentEvent.source_type, IntentEvent.summary, IntentEvent.evidence_text]
    column_sortable_list = [IntentEvent.created_at]
    column_default_sort = [(IntentEvent.created_at, True)]
    column_labels = {
        IntentEvent.customer_id: "客户ID",
        IntentEvent.lead_id: "线索ID",
        IntentEvent.source_type: "来源类型",
        IntentEvent.source_record_id: "来源记录ID",
        IntentEvent.channel: "渠道",
        IntentEvent.intent_level: "意向等级",
        IntentEvent.summary: "摘要",
        IntentEvent.evidence_text: "证据内容",
        IntentEvent.need_handoff: "需人工接管",
        IntentEvent.created_at: "创建时间",
    }


class FollowUpWorkOrderAdmin(ModelView, model=FollowUpWorkOrder):
    name = "跟进工单"
    name_plural = "跟进工单"
    icon = "fa-solid fa-list-check"

    column_list = [
        FollowUpWorkOrder.title,
        FollowUpWorkOrder.owner_name,
        FollowUpWorkOrder.status,
        FollowUpWorkOrder.priority,
        FollowUpWorkOrder.sla_due_at,
        FollowUpWorkOrder.created_at,
    ]
    column_searchable_list = [FollowUpWorkOrder.title, FollowUpWorkOrder.owner_name, FollowUpWorkOrder.status]
    column_sortable_list = [FollowUpWorkOrder.created_at, FollowUpWorkOrder.sla_due_at]
    column_labels = {
        FollowUpWorkOrder.customer_id: "客户ID",
        FollowUpWorkOrder.title: "工单标题",
        FollowUpWorkOrder.owner_name: "负责人",
        FollowUpWorkOrder.status: "状态",
        FollowUpWorkOrder.priority: "优先级",
        FollowUpWorkOrder.sla_due_at: "SLA截止",
        FollowUpWorkOrder.last_note: "最近记录",
        FollowUpWorkOrder.closed_reason: "关闭原因",
        FollowUpWorkOrder.created_at: "创建时间",
        FollowUpWorkOrder.updated_at: "更新时间",
    }


class LearningSuggestionAdmin(ModelView, model=LearningSuggestion):
    name = "AI学习建议"
    name_plural = "AI学习建议"
    icon = "fa-solid fa-lightbulb"

    column_list = [
        LearningSuggestion.title,
        LearningSuggestion.target_type,
        LearningSuggestion.status,
        LearningSuggestion.impact_score,
        LearningSuggestion.reviewer,
        LearningSuggestion.created_at,
    ]
    column_searchable_list = [LearningSuggestion.title, LearningSuggestion.summary, LearningSuggestion.proposed_content]
    column_sortable_list = [LearningSuggestion.created_at, LearningSuggestion.impact_score]
    column_labels = {
        LearningSuggestion.source_type: "来源类型",
        LearningSuggestion.source_record_id: "来源记录ID",
        LearningSuggestion.target_type: "作用对象",
        LearningSuggestion.title: "标题",
        LearningSuggestion.summary: "摘要",
        LearningSuggestion.proposed_content: "建议内容",
        LearningSuggestion.evidence_text: "证据",
        LearningSuggestion.status: "状态",
        LearningSuggestion.reviewer: "审核人",
        LearningSuggestion.review_note: "审核意见",
        LearningSuggestion.impact_score: "影响分",
        LearningSuggestion.rollback_point: "回滚点",
        LearningSuggestion.created_at: "创建时间",
        LearningSuggestion.reviewed_at: "审核时间",
        LearningSuggestion.published_at: "发布时间",
    }


class KnowledgeBaseItemAdmin(ModelView, model=KnowledgeBaseItem):
    name = "知识库条目"
    name_plural = "AI知识库"
    icon = "fa-solid fa-book"

    column_list = [
        KnowledgeBaseItem.title,
        KnowledgeBaseItem.category,
        KnowledgeBaseItem.status,
        KnowledgeBaseItem.version,
        KnowledgeBaseItem.updated_at,
    ]
    column_searchable_list = [KnowledgeBaseItem.title, KnowledgeBaseItem.category, KnowledgeBaseItem.content]
    column_sortable_list = [KnowledgeBaseItem.updated_at]
    column_labels = {
        KnowledgeBaseItem.title: "标题",
        KnowledgeBaseItem.category: "分类",
        KnowledgeBaseItem.content: "内容",
        KnowledgeBaseItem.status: "状态",
        KnowledgeBaseItem.version: "版本",
        KnowledgeBaseItem.source_suggestion_id: "来源建议ID",
        KnowledgeBaseItem.created_at: "创建时间",
        KnowledgeBaseItem.updated_at: "更新时间",
    }


class LearningExperimentAdmin(ModelView, model=LearningExperiment):
    name = "效果实验"
    name_plural = "学习效果实验"
    icon = "fa-solid fa-flask"

    column_list = [
        LearningExperiment.name,
        LearningExperiment.target_type,
        LearningExperiment.status,
        LearningExperiment.sample_size,
        LearningExperiment.success_metric,
        LearningExperiment.created_at,
    ]
    column_searchable_list = [LearningExperiment.name, LearningExperiment.hypothesis, LearningExperiment.variant]
    column_sortable_list = [LearningExperiment.created_at, LearningExperiment.sample_size]
    column_labels = {
        LearningExperiment.name: "实验名称",
        LearningExperiment.target_type: "作用对象",
        LearningExperiment.status: "状态",
        LearningExperiment.hypothesis: "假设",
        LearningExperiment.variant: "变量",
        LearningExperiment.sample_size: "样本量",
        LearningExperiment.success_metric: "成功指标",
        LearningExperiment.result_summary: "结果摘要",
        LearningExperiment.started_at: "开始时间",
        LearningExperiment.ended_at: "结束时间",
        LearningExperiment.created_at: "创建时间",
    }


class VoiceProfileAdmin(ModelView, model=VoiceProfile):
    name = "声音档案"
    name_plural = "声音档案"
    icon = "fa-solid fa-microphone-lines"

    column_list = [
        VoiceProfile.name,
        VoiceProfile.owner_name,
        VoiceProfile.scenario,
        VoiceProfile.status,
        VoiceProfile.authorization_status,
        VoiceProfile.sample_count,
        VoiceProfile.updated_at,
    ]
    column_searchable_list = [VoiceProfile.name, VoiceProfile.owner_name, VoiceProfile.scenario]
    column_sortable_list = [VoiceProfile.updated_at, VoiceProfile.sample_count]
    column_labels = {
        VoiceProfile.name: "档案名称",
        VoiceProfile.owner_name: "授权人",
        VoiceProfile.scenario: "使用场景",
        VoiceProfile.status: "状态",
        VoiceProfile.authorization_status: "授权状态",
        VoiceProfile.sample_count: "样本数",
        VoiceProfile.fallback_voice: "回退音色",
        VoiceProfile.consent_material: "授权材料",
        VoiceProfile.risk_note: "风险备注",
        VoiceProfile.created_at: "创建时间",
        VoiceProfile.updated_at: "更新时间",
    }


class VoiceTrainingJobAdmin(ModelView, model=VoiceTrainingJob):
    name = "音色复刻"
    name_plural = "音色复刻任务"
    icon = "fa-solid fa-wave-square"

    column_list = [
        VoiceTrainingJob.profile_id,
        VoiceTrainingJob.status,
        VoiceTrainingJob.progress,
        VoiceTrainingJob.engine,
        VoiceTrainingJob.sample_minutes,
        VoiceTrainingJob.created_at,
    ]
    column_searchable_list = [VoiceTrainingJob.status, VoiceTrainingJob.engine, VoiceTrainingJob.message]
    column_sortable_list = [VoiceTrainingJob.created_at, VoiceTrainingJob.progress]
    column_labels = {
        VoiceTrainingJob.profile_id: "声音档案ID",
        VoiceTrainingJob.status: "状态",
        VoiceTrainingJob.progress: "进度",
        VoiceTrainingJob.engine: "训练引擎",
        VoiceTrainingJob.sample_minutes: "样本分钟",
        VoiceTrainingJob.message: "消息",
        VoiceTrainingJob.created_at: "创建时间",
        VoiceTrainingJob.started_at: "开始时间",
        VoiceTrainingJob.finished_at: "完成时间",
    }


class VoiceSampleAdmin(ModelView, model=VoiceSample):
    name = "声音样本"
    name_plural = "声音样本"
    icon = "fa-solid fa-file-audio"

    column_list = [
        VoiceSample.profile_id,
        VoiceSample.file_name,
        VoiceSample.content_type,
        VoiceSample.size_bytes,
        VoiceSample.duration_seconds,
        VoiceSample.quality_status,
        VoiceSample.created_at,
    ]
    column_searchable_list = [VoiceSample.file_name, VoiceSample.quality_status, VoiceSample.uploaded_by]
    column_sortable_list = [VoiceSample.created_at, VoiceSample.size_bytes, VoiceSample.duration_seconds]
    column_labels = {
        VoiceSample.profile_id: "声音档案ID",
        VoiceSample.file_name: "文件名",
        VoiceSample.content_type: "文件类型",
        VoiceSample.storage_path: "本地存储路径",
        VoiceSample.size_bytes: "文件大小",
        VoiceSample.duration_seconds: "样本时长",
        VoiceSample.quality_status: "质检状态",
        VoiceSample.transcript: "转写文本",
        VoiceSample.uploaded_by: "上传人",
        VoiceSample.created_at: "上传时间",
    }


class VoiceCloneRecordAdmin(ModelView, model=VoiceCloneRecord):
    name = "克隆记录"
    name_plural = "克隆语音记录"
    icon = "fa-solid fa-record-vinyl"

    column_list = [
        VoiceCloneRecord.cloned_voice_name,
        VoiceCloneRecord.status,
        VoiceCloneRecord.engine,
        VoiceCloneRecord.external_voice_id,
        VoiceCloneRecord.sample_count,
        VoiceCloneRecord.sample_minutes,
        VoiceCloneRecord.created_at,
    ]
    column_searchable_list = [VoiceCloneRecord.cloned_voice_name, VoiceCloneRecord.status, VoiceCloneRecord.engine]
    column_sortable_list = [VoiceCloneRecord.created_at, VoiceCloneRecord.sample_count]
    column_labels = {
        VoiceCloneRecord.profile_id: "声音档案ID",
        VoiceCloneRecord.training_job_id: "训练任务ID",
        VoiceCloneRecord.cloned_voice_name: "克隆音色",
        VoiceCloneRecord.engine: "克隆引擎",
        VoiceCloneRecord.external_voice_id: "外部音色ID",
        VoiceCloneRecord.preview_audio_path: "试听音频路径",
        VoiceCloneRecord.status: "状态",
        VoiceCloneRecord.sample_count: "样本数",
        VoiceCloneRecord.sample_minutes: "样本分钟",
        VoiceCloneRecord.result: "结果",
        VoiceCloneRecord.created_at: "创建时间",
        VoiceCloneRecord.completed_at: "完成时间",
    }


class VoiceUsageRecordAdmin(ModelView, model=VoiceUsageRecord):
    name = "声音使用记录"
    name_plural = "声音使用记录"
    icon = "fa-solid fa-clock"

    column_list = [
        VoiceUsageRecord.merchant_name,
        VoiceUsageRecord.scenario,
        VoiceUsageRecord.result,
        VoiceUsageRecord.fallback_used,
        VoiceUsageRecord.created_at,
    ]
    column_searchable_list = [VoiceUsageRecord.merchant_name, VoiceUsageRecord.scenario, VoiceUsageRecord.result]
    column_sortable_list = [VoiceUsageRecord.created_at]
    column_labels = {
        VoiceUsageRecord.profile_id: "声音档案ID",
        VoiceUsageRecord.task_id: "任务ID",
        VoiceUsageRecord.merchant_name: "商家",
        VoiceUsageRecord.scenario: "场景",
        VoiceUsageRecord.result: "结果",
        VoiceUsageRecord.fallback_used: "使用回退",
        VoiceUsageRecord.created_at: "创建时间",
    }


class ReportExportAdmin(ModelView, model=ReportExport):
    name = "报表导出"
    name_plural = "报表导出任务"
    icon = "fa-solid fa-file-export"

    column_list = [
        ReportExport.report_type,
        ReportExport.date_range,
        ReportExport.file_format,
        ReportExport.requester,
        ReportExport.status,
        ReportExport.row_count,
        ReportExport.sensitive_fields_included,
        ReportExport.created_at,
    ]
    column_searchable_list = [ReportExport.report_type, ReportExport.requester, ReportExport.status]
    column_sortable_list = [ReportExport.created_at, ReportExport.row_count]
    column_default_sort = [(ReportExport.created_at, True)]
    column_labels = {
        ReportExport.report_type: "报表类型",
        ReportExport.date_range: "时间范围",
        ReportExport.file_format: "格式",
        ReportExport.requester: "申请人",
        ReportExport.status: "状态",
        ReportExport.download_url: "下载地址",
        ReportExport.row_count: "行数",
        ReportExport.sensitive_fields_included: "包含敏感字段",
        ReportExport.created_at: "创建时间",
        ReportExport.finished_at: "完成时间",
    }


class SystemSettingAdmin(ModelView, model=SystemSetting):
    name = "系统设置"
    name_plural = "系统设置"
    icon = "fa-solid fa-sliders"

    column_list = [
        SystemSetting.group_key,
        SystemSetting.item_key,
        SystemSetting.label,
        SystemSetting.value_type,
        SystemSetting.status,
        SystemSetting.sensitive,
        SystemSetting.updated_by,
        SystemSetting.updated_at,
    ]
    column_searchable_list = [SystemSetting.group_key, SystemSetting.item_key, SystemSetting.label, SystemSetting.value]
    column_sortable_list = [SystemSetting.group_key, SystemSetting.updated_at]
    column_labels = {
        SystemSetting.group_key: "分组",
        SystemSetting.item_key: "配置键",
        SystemSetting.label: "名称",
        SystemSetting.value: "配置值",
        SystemSetting.value_type: "值类型",
        SystemSetting.status: "状态",
        SystemSetting.description: "说明",
        SystemSetting.sensitive: "敏感",
        SystemSetting.updated_by: "更新人",
        SystemSetting.created_at: "创建时间",
        SystemSetting.updated_at: "更新时间",
    }


def _admin_text(value: object) -> str:
    return str(value or "").strip()


def _admin_fk_id(value: object) -> str:
    if hasattr(value, "id"):
        return _admin_text(getattr(value, "id"))
    return _admin_text(value)


def _admin_profile_defaults(key: str) -> dict[str, object]:
    return PROFILE_DEFAULTS.get(key, PROFILE_DEFAULTS["sip_volte_gateway"])


def _admin_slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_").lower()
    return cleaned[:40] or token_hex(4)


def _admin_generate_sip_password(length: int = 24) -> str:
    return "".join(choice(SECRET_ALPHABET) for _ in range(length))


def _admin_normalise_device_admin_url(admin_url: str | None, device_ip: str | None) -> str:
    value = _admin_text(admin_url) or _admin_text(device_ip)
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = f"http://{value}"
    value = _admin_strip_sip_port_from_admin_url(value)
    return value.rstrip("/") + "/"


def _admin_strip_sip_port_from_admin_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    try:
        port = parsed.port
    except ValueError:
        return value
    if port not in {5060, 5080, 15060} or not parsed.hostname:
        return value
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme or 'http'}://{host}{parsed.path or ''}"


def _admin_append_note(current: str | None, note: str) -> str:
    if not note:
        return _admin_text(current)
    line = f"{datetime.utcnow().isoformat(timespec='seconds')} {note}"
    return f"{_admin_text(current)}\n{line}".strip() if _admin_text(current) else line


def _admin_device_discovery_note(discovery: VoiceGatewayDeviceDiscovery) -> str:
    parts = [f"source={discovery.source}", f"status={discovery.status}"]
    if discovery.device_admin_url:
        parts.append(f"admin={discovery.device_admin_url}")
    if discovery.device_ip:
        parts.append(f"ip={discovery.device_ip}")
    if discovery.device_mac:
        parts.append(f"mac={discovery.device_mac}")
    if discovery.device_serial:
        parts.append(f"serial={discovery.device_serial}")
    if discovery.summary:
        parts.append(discovery.summary)
    return "；".join(part for part in parts if part)


def _admin_latest_unmatched_device_discovery(owner_user_id: str) -> VoiceGatewayDeviceDiscovery | None:
    if not owner_user_id:
        return None
    with SessionLocal() as db:
        return db.scalar(
            select(VoiceGatewayDeviceDiscovery)
            .where(
                VoiceGatewayDeviceDiscovery.owner_user_id == owner_user_id,
                VoiceGatewayDeviceDiscovery.matched_line_id.is_(None),
            )
            .order_by(VoiceGatewayDeviceDiscovery.updated_at.desc(), VoiceGatewayDeviceDiscovery.created_at.desc())
        )


def _admin_owner(owner_user_id: str) -> User | None:
    if not owner_user_id:
        return None
    with SessionLocal() as db:
        return db.get(User, owner_user_id)


def _admin_line_identity(owner: User | None, owner_user_id: str) -> tuple[str, str]:
    owner_slug = _admin_slug((owner.username if owner else owner_user_id) or owner_user_id)
    with SessionLocal() as db:
        for _ in range(20):
            suffix = token_hex(4)
            sip_username = f"sip_{owner_slug}_{suffix}"
            trunk_name = f"tg_{owner_slug}_{suffix}"
            exists = db.scalar(
                select(VoiceGatewayLine.id).where(
                    (VoiceGatewayLine.sip_username == sip_username) | (VoiceGatewayLine.trunk_name == trunk_name)
                )
            )
            if not exists:
                return sip_username, trunk_name
    suffix = token_hex(8)
    return f"sip_{owner_slug}_{suffix}", f"tg_{owner_slug}_{suffix}"


def _admin_prepare_voice_gateway_line_data(data: dict, model: VoiceGatewayLine, is_created: bool) -> None:
    owner_user_id = _admin_fk_id(data.get("owner_user_id") or data.get("owner_user") or getattr(model, "owner_user_id", ""))
    owner = _admin_owner(owner_user_id)
    profile_key = _admin_text(data.get("gateway_profile_key") or getattr(model, "gateway_profile_key", "")) or "dinstar_8t_server"
    profile = _admin_profile_defaults(profile_key)
    discovery = _admin_latest_unmatched_device_discovery(owner_user_id)

    if not _admin_text(data.get("line_name") or getattr(model, "line_name", "")):
        customer = _admin_text(data.get("customer_name") or (owner.display_name if owner else "") or (owner.username if owner else ""))
        data["line_name"] = f"{customer or '客户'} 语音网关 {datetime.utcnow().strftime('%m%d-%H%M')}"
    if not _admin_text(data.get("customer_name") or getattr(model, "customer_name", "")):
        data["customer_name"] = _admin_text((owner.display_name if owner else "") or (owner.username if owner else ""))

    data["gateway_profile_key"] = profile_key
    if not _admin_text(data.get("gateway_label") or getattr(model, "gateway_label", "")):
        data["gateway_label"] = discovery.gateway_label or str(profile["label"]) if discovery else str(profile["label"])
    if not _admin_text(data.get("gateway_vendor") or getattr(model, "gateway_vendor", "")):
        data["gateway_vendor"] = str(profile["vendor"])
    if not _admin_text(data.get("gateway_model") or getattr(model, "gateway_model", "")):
        data["gateway_model"] = str(profile["model"])
    if not _admin_text(data.get("gateway_category") or getattr(model, "gateway_category", "")):
        data["gateway_category"] = str(profile["category"])
    if not _admin_text(data.get("deployment_mode") or getattr(model, "deployment_mode", "")):
        data["deployment_mode"] = "server"
    if not _admin_text(data.get("sip_server_host") or getattr(model, "sip_server_host", "")):
        data["sip_server_host"] = DEFAULT_SIP_SERVER_HOST
    if not data.get("sip_server_port") and not getattr(model, "sip_server_port", None):
        data["sip_server_port"] = 5060
    if not _admin_text(data.get("sip_transport") or getattr(model, "sip_transport", "")):
        data["sip_transport"] = "UDP"

    needs_identity = (
        is_created
        or not _admin_text(data.get("sip_username") or getattr(model, "sip_username", ""))
        or not _admin_text(data.get("trunk_name") or getattr(model, "trunk_name", ""))
        or not _admin_text(data.get("sip_password_hash") or getattr(model, "sip_password_hash", ""))
    )
    if needs_identity:
        sip_username, trunk_name = _admin_line_identity(owner, owner_user_id)
        if not _admin_text(data.get("sip_username") or getattr(model, "sip_username", "")):
            data["sip_username"] = sip_username
        if not _admin_text(data.get("sip_auth_username") or getattr(model, "sip_auth_username", "")):
            data["sip_auth_username"] = data["sip_username"]
        if not _admin_text(data.get("trunk_name") or getattr(model, "trunk_name", "")):
            data["trunk_name"] = trunk_name
        if not _admin_text(data.get("sip_password_hash") or getattr(model, "sip_password_hash", "")):
            data["sip_password_hash"] = hash_password(_admin_generate_sip_password())
    else:
        for field in ("sip_username", "sip_auth_username", "trunk_name", "sip_password_hash"):
            if not _admin_text(data.get(field)):
                data[field] = getattr(model, field, "")

    trunk_name = _admin_text(data.get("trunk_name") or getattr(model, "trunk_name", ""))
    if not _admin_text(data.get("sip_auth_username") or getattr(model, "sip_auth_username", "")):
        data["sip_auth_username"] = _admin_text(data.get("sip_username") or getattr(model, "sip_username", ""))
    if not _admin_text(data.get("sip_password_secret_alias") or getattr(model, "sip_password_secret_alias", "")):
        data["sip_password_secret_alias"] = f"voice-gateway/{owner_user_id}/{trunk_name}/sip-password"

    if not data.get("channel_count") and not getattr(model, "channel_count", None):
        data["channel_count"] = PROFILE_CHANNEL_DEFAULTS.get(profile_key, 1)
    if not _admin_text(data.get("codec_primary") or getattr(model, "codec_primary", "")):
        data["codec_primary"] = DEFAULT_CODEC_PRIMARY
    if not _admin_text(data.get("codec_secondary") or getattr(model, "codec_secondary", "")):
        data["codec_secondary"] = DEFAULT_CODEC_SECONDARY
    if not _admin_text(data.get("dtmf_mode") or getattr(model, "dtmf_mode", "")):
        data["dtmf_mode"] = DEFAULT_DTMF_MODE
    if not _admin_text(data.get("rtp_port_range") or getattr(model, "rtp_port_range", "")):
        data["rtp_port_range"] = DEFAULT_RTP_RANGE
    if not _admin_text(data.get("route_direction") or getattr(model, "route_direction", "")):
        data["route_direction"] = DEFAULT_ROUTE_DIRECTION

    if discovery is not None:
        if not _admin_text(data.get("device_admin_url") or getattr(model, "device_admin_url", "")):
            data["device_admin_url"] = _admin_normalise_device_admin_url(discovery.device_admin_url, discovery.device_ip)
        if not _admin_text(data.get("device_mac") or getattr(model, "device_mac", "")):
            data["device_mac"] = discovery.device_mac
        if not _admin_text(data.get("device_serial") or getattr(model, "device_serial", "")):
            data["device_serial"] = discovery.device_serial
        note = _admin_device_discovery_note(discovery)
        data["network_note"] = _admin_append_note(data.get("network_note") or getattr(model, "network_note", ""), note)
        if _admin_text(data.get("status") or getattr(model, "status", "")) in {"", "待配置", "待设备发现", "设备未发现"}:
            data["status"] = "待设备注册"

    if is_created and not _admin_text(data.get("notes") or getattr(model, "notes", "")):
        data["notes"] = "SQLAdmin 自动生成线路；SIP 明文密码只通过配置卡/轮换接口一次性展示，不能从后台找回。"


def _admin_mark_latest_discovery_matched(line: VoiceGatewayLine) -> None:
    if not line.id or not line.owner_user_id:
        return
    with SessionLocal() as db:
        discovery = db.scalar(
            select(VoiceGatewayDeviceDiscovery)
            .where(
                VoiceGatewayDeviceDiscovery.owner_user_id == line.owner_user_id,
                VoiceGatewayDeviceDiscovery.matched_line_id.is_(None),
            )
            .order_by(VoiceGatewayDeviceDiscovery.updated_at.desc(), VoiceGatewayDeviceDiscovery.created_at.desc())
        )
        if discovery is None:
            return
        discovery.matched_line_id = line.id
        discovery.status = "matched"
        discovery.updated_at = datetime.utcnow()
        db.add(
            VoiceGatewayLineEvent(
                line_id=line.id,
                owner_user_id=line.owner_user_id,
                actor_user_id=None,
                event_type="device_discovery",
                status="matched",
                summary="SQLAdmin 新增线路时自动匹配客户客户端发现的语音网关",
                detail=_admin_device_discovery_note(discovery),
                evidence_json=discovery.evidence_json,
            )
        )
        db.commit()


def _admin_selected_ids(request: Request) -> list[str]:
    return [pk for pk in request.query_params.get("pks", "").split(",") if pk]


def _admin_action_redirect(request: Request, identity: str) -> RedirectResponse:
    return RedirectResponse(request.url_for("admin:list", identity=identity), status_code=302)


def _admin_safe_pjsip_token(value: str, label: str) -> str:
    token = _admin_text(value)
    if not token or not re.fullmatch(r"[0-9A-Za-z_.@-]+", token):
        raise ValueError(f"{label} 只能包含字母、数字、下划线、点、@ 或短横线")
    return token


def _admin_render_pjsip_line(line: VoiceGatewayLine, password: str) -> str:
    trunk_name = _admin_safe_pjsip_token(line.trunk_name, "云端 Trunk")
    sip_username = _admin_safe_pjsip_token(line.sip_username, "SIP 账号")
    sip_auth_username = _admin_safe_pjsip_token(line.sip_auth_username or line.sip_username, "鉴权账号")
    max_contacts = max(1, int(line.channel_count or 1))
    context = "from-dinstar8t" if line.gateway_profile_key != "uc100_sip_volte" else "from-uc100"
    return f"""; BEGIN AI_ACQ_LINE {line.id}
[{trunk_name}]
type = endpoint
transport = transport-udp
context = {context}
disallow = all
allow = alaw
allow = ulaw
direct_media = no
force_rport = yes
rewrite_contact = yes
rtp_symmetric = yes
timers = no
auth = {trunk_name}-auth
aors = {trunk_name}-aor
from_user = {sip_username}
callerid = AI获客 <{sip_username}>

[{trunk_name}-auth]
type = auth
auth_type = userpass
username = {sip_auth_username}
password = {password}

[{trunk_name}-aor]
type = aor
max_contacts = {max_contacts}
remove_existing = no
qualify_frequency = 30
; END AI_ACQ_LINE {line.id}
"""


def _admin_upsert_asterisk_dynamic_pjsip(line: VoiceGatewayLine, password: str) -> None:
    path = ASTERISK_DYNAMIC_PJSIP_PATH
    marker_start = f"; BEGIN AI_ACQ_LINE {line.id}"
    marker_end = f"; END AI_ACQ_LINE {line.id}"
    next_block = _admin_render_pjsip_line(line, password)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(
        rf"^; BEGIN AI_ACQ_LINE {re.escape(line.id)}\n.*?^; END AI_ACQ_LINE {re.escape(line.id)}\n?",
        flags=re.MULTILINE | re.DOTALL,
    )
    if marker_start in current and marker_end in current:
        updated = pattern.sub(next_block, current).strip() + "\n"
    else:
        updated = (current.rstrip() + "\n\n" + next_block).lstrip()
    path.write_text(updated, encoding="utf-8")


def _admin_reload_asterisk_pjsip() -> str:
    commands = [
        ["asterisk", "-rx", "pjsip reload"],
        ["asterisk", "-rx", "dialplan reload"],
    ]
    outputs: list[str] = []
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=12)
        output = (result.stdout or result.stderr or "").strip()
        outputs.append(output)
        if result.returncode != 0:
            raise RuntimeError(output or f"{' '.join(command)} 执行失败")
    return "；".join(item for item in outputs if item) or "Asterisk 已重新加载"


class VoiceGatewayLineAdmin(ModelView, model=VoiceGatewayLine):
    name = "语音网关线路"
    name_plural = "语音网关线路"
    icon = "fa-solid fa-network-wired"

    column_list = [
        VoiceGatewayLine.customer_name,
        VoiceGatewayLine.line_name,
        VoiceGatewayLine.gateway_label,
        VoiceGatewayLine.device_admin_url,
        VoiceGatewayLine.sip_server_host,
        VoiceGatewayLine.sip_server_port,
        VoiceGatewayLine.sip_transport,
        VoiceGatewayLine.sip_username,
        VoiceGatewayLine.trunk_name,
        VoiceGatewayLine.channel_count,
        VoiceGatewayLine.status,
        VoiceGatewayLine.registration_status,
        VoiceGatewayLine.acceptance_status,
        VoiceGatewayLine.updated_at,
    ]
    column_searchable_list = [
        VoiceGatewayLine.customer_name,
        VoiceGatewayLine.line_name,
        VoiceGatewayLine.sip_username,
        VoiceGatewayLine.trunk_name,
        VoiceGatewayLine.device_admin_url,
        VoiceGatewayLine.device_mac,
        VoiceGatewayLine.device_serial,
    ]
    column_sortable_list = [VoiceGatewayLine.created_at, VoiceGatewayLine.updated_at, VoiceGatewayLine.status]
    column_default_sort = [(VoiceGatewayLine.updated_at, True)]
    column_details_exclude_list = [VoiceGatewayLine.sip_password_hash]
    form_excluded_columns = [VoiceGatewayLine.sip_password_hash, VoiceGatewayLine.events]
    form_args = {
        "line_name": {
            "label": "线路名称",
            "description": "可留空；后台会按客户账号自动生成。",
            "validators": [Optional()],
        },
        "gateway_profile_key": {
            "label": "网关档案",
            "description": "默认鼎信 8T/通用语音网关；不要写死 UC100。",
            "validators": [Optional()],
        },
        "gateway_label": {
            "label": "网关名称",
            "description": "可留空；后台按网关档案或客户客户端扫描结果自动生成。",
            "validators": [Optional()],
        },
        "gateway_vendor": {"validators": [Optional()]},
        "gateway_model": {"validators": [Optional()]},
        "gateway_category": {"validators": [Optional()]},
        "sip_server_host": {
            "label": "SIP服务器",
            "description": "可留空；默认生成云端公网 SIP 服务器 101.132.63.159。",
            "validators": [Optional()],
        },
        "sip_server_port": {
            "label": "SIP端口",
            "description": "可留空；默认 5060。",
            "validators": [Optional()],
        },
        "sip_transport": {
            "label": "SIP协议",
            "description": "可留空；默认 UDP。",
            "validators": [Optional()],
        },
        "sip_username": {
            "label": "SIP账号",
            "description": "可留空；保存时按客户账号自动生成。",
            "validators": [Optional()],
        },
        "sip_auth_username": {
            "label": "鉴权账号",
            "description": "可留空；默认与 SIP账号一致。",
            "validators": [Optional()],
        },
        "sip_password_secret_alias": {
            "label": "密码密钥别名",
            "description": "这里不是明文密码。明文 SIP 密码只在生成或轮换时一次性显示；后台新增后如需交付给设备，请通过轮换/配置卡流程取得一次性密码。",
            "validators": [Optional()],
        },
        "trunk_name": {
            "label": "云端Trunk",
            "description": "可留空；保存时按客户账号自动生成。",
            "validators": [Optional()],
        },
        "channel_count": {
            "label": "通道数",
            "description": "可留空；鼎信 8T 默认 8 路，通用/UC100 默认 1 路。",
            "validators": [Optional()],
        },
        "codec_primary": {"validators": [Optional()]},
        "codec_secondary": {"validators": [Optional()]},
        "dtmf_mode": {"validators": [Optional()]},
        "rtp_port_range": {"validators": [Optional()]},
        "route_direction": {"validators": [Optional()]},
        "device_admin_url": {
            "label": "设备后台地址",
            "description": "可留空；如果客户客户端已经扫描到现场设备，保存线路时会自动带入。否则由交付电脑/客户端扫描、路由器 DHCP 列表、设备屏幕或说明书默认地址确认后填写。",
            "validators": [Optional()],
        },
        "device_mac": {
            "label": "设备MAC",
            "description": "用于多客户/多设备时绑定具体硬件，避免换网络后只靠 IP 认错设备。",
            "validators": [Optional()],
        },
        "device_serial": {
            "label": "设备序列号",
            "description": "建议提前录入设备标签或采购台账里的序列号，现场发现后与设备核对。",
            "validators": [Optional()],
        },
        "network_note": {
            "label": "网络说明",
            "description": "记录客户现场网段、交换机/路由器 DHCP 线索、固定 IP 或保留地址等交付信息。",
            "validators": [Optional()],
        },
    }
    column_labels = {
        VoiceGatewayLine.owner_user_id: "客户账号",
        VoiceGatewayLine.created_by_user_id: "创建人",
        VoiceGatewayLine.line_name: "线路名称",
        VoiceGatewayLine.customer_name: "客户名称",
        VoiceGatewayLine.status: "交付状态",
        VoiceGatewayLine.gateway_profile_key: "网关档案",
        VoiceGatewayLine.gateway_label: "网关名称",
        VoiceGatewayLine.gateway_vendor: "厂商",
        VoiceGatewayLine.gateway_model: "型号",
        VoiceGatewayLine.gateway_category: "类型",
        VoiceGatewayLine.deployment_mode: "部署模式",
        VoiceGatewayLine.sip_server_host: "SIP服务器",
        VoiceGatewayLine.sip_server_port: "SIP端口",
        VoiceGatewayLine.sip_transport: "SIP协议",
        VoiceGatewayLine.sip_username: "SIP账号",
        VoiceGatewayLine.sip_auth_username: "鉴权账号",
        VoiceGatewayLine.sip_password_secret_alias: "密码密钥别名",
        VoiceGatewayLine.trunk_name: "云端Trunk",
        VoiceGatewayLine.channel_count: "通道数",
        VoiceGatewayLine.codec_primary: "主编码",
        VoiceGatewayLine.codec_secondary: "备用编码",
        VoiceGatewayLine.dtmf_mode: "DTMF",
        VoiceGatewayLine.rtp_port_range: "RTP端口",
        VoiceGatewayLine.route_direction: "路由方向",
        VoiceGatewayLine.device_admin_url: "设备后台地址",
        VoiceGatewayLine.device_serial: "设备序列号",
        VoiceGatewayLine.device_mac: "设备MAC",
        VoiceGatewayLine.network_note: "网络说明",
        VoiceGatewayLine.registration_status: "注册状态",
        VoiceGatewayLine.route_status: "路由状态",
        VoiceGatewayLine.sim_status: "SIM/VoLTE状态",
        VoiceGatewayLine.rtp_status: "RTP状态",
        VoiceGatewayLine.acceptance_status: "验收状态",
        VoiceGatewayLine.last_registered_at: "最近注册时间",
        VoiceGatewayLine.last_preflight_at: "最近预检时间",
        VoiceGatewayLine.notes: "备注",
        VoiceGatewayLine.created_at: "创建时间",
        VoiceGatewayLine.updated_at: "更新时间",
    }

    async def on_model_change(
        self,
        data: dict,
        model: VoiceGatewayLine,
        is_created: bool,
        request: Request,
    ) -> None:
        _admin_prepare_voice_gateway_line_data(data, model, is_created)

    async def after_model_change(
        self,
        data: dict,
        model: VoiceGatewayLine,
        is_created: bool,
        request: Request,
    ) -> None:
        _admin_mark_latest_discovery_matched(model)

    @action(
        name="rotate-sip-password",
        label="生成一次性 SIP 密码",
        confirmation_message="确认为选中的语音网关线路生成新 SIP 密码？旧密码会失效，并会写入云端 Asterisk。",
        add_in_detail=True,
        add_in_list=True,
    )
    async def rotate_sip_password(self, request: Request) -> RedirectResponse:
        selected_ids = _admin_selected_ids(request)
        if not selected_ids:
            Flash.warning(request, "请先选择要生成密码的语音网关线路")
            return _admin_action_redirect(request, self.identity)

        actor_username = request.session.get("admin_user")
        results: list[str] = []
        errors: list[str] = []
        with SessionLocal() as db:
            for line_id in selected_ids:
                line = db.get(VoiceGatewayLine, line_id)
                if line is None:
                    errors.append(f"未找到线路：{line_id}")
                    continue
                try:
                    password = _admin_generate_sip_password()
                    _admin_upsert_asterisk_dynamic_pjsip(line, password)
                    reload_message = _admin_reload_asterisk_pjsip()
                    line.sip_password_hash = hash_password(password)
                    line.status = "待重新下发"
                    line.registration_status = "待重新注册"
                    line.updated_at = datetime.utcnow()
                    db.add(
                        VoiceGatewayLineEvent(
                            line_id=line.id,
                            owner_user_id=line.owner_user_id,
                            actor_user_id=None,
                            event_type="credential_rotated",
                            status="rotated",
                            summary="SQLAdmin 生成一次性 SIP 密码",
                            detail="已写入云端 Asterisk；交付人员需要立刻同步填写到现场语音网关后台。",
                        )
                    )
                    db.add(
                        AuditLog(
                            actor_user_id=None,
                            actor_username=actor_username,
                            action="voice_gateway_line.rotate_credential",
                            resource_type="voice_gateway_line",
                            resource_id=line.id,
                            summary=f"SQLAdmin 生成语音网关一次性 SIP 密码：{line.line_name}",
                        )
                    )
                    db.commit()
                    results.append(
                        f"{line.customer_name or line.line_name}：SIP账号 {line.sip_username}，"
                        f"鉴权账号 {line.sip_auth_username}，一次性密码 {password}，Asterisk：{reload_message}"
                    )
                except Exception as exc:
                    db.rollback()
                    errors.append(f"{line.line_name if line else line_id}：{exc}")
                    continue

        if results:
            Flash.success(request, "只显示本次，请马上复制到设备后台。 " + "；".join(results))
        if errors:
            Flash.error(request, "部分线路生成失败：" + "；".join(errors))
        return _admin_action_redirect(request, self.identity)


class VoiceGatewayDeviceDiscoveryAdmin(ModelView, model=VoiceGatewayDeviceDiscovery):
    name = "待匹配设备发现"
    name_plural = "待匹配设备发现"
    icon = "fa-solid fa-satellite-dish"
    can_create = False
    can_delete = False

    column_list = [
        VoiceGatewayDeviceDiscovery.owner_user_id,
        VoiceGatewayDeviceDiscovery.status,
        VoiceGatewayDeviceDiscovery.gateway_label,
        VoiceGatewayDeviceDiscovery.device_admin_url,
        VoiceGatewayDeviceDiscovery.device_ip,
        VoiceGatewayDeviceDiscovery.device_mac,
        VoiceGatewayDeviceDiscovery.device_serial,
        VoiceGatewayDeviceDiscovery.matched_line_id,
        VoiceGatewayDeviceDiscovery.updated_at,
    ]
    column_searchable_list = [
        VoiceGatewayDeviceDiscovery.owner_user_id,
        VoiceGatewayDeviceDiscovery.gateway_label,
        VoiceGatewayDeviceDiscovery.device_admin_url,
        VoiceGatewayDeviceDiscovery.device_ip,
        VoiceGatewayDeviceDiscovery.device_mac,
        VoiceGatewayDeviceDiscovery.device_serial,
    ]
    column_sortable_list = [
        VoiceGatewayDeviceDiscovery.updated_at,
        VoiceGatewayDeviceDiscovery.created_at,
        VoiceGatewayDeviceDiscovery.status,
    ]
    column_default_sort = [(VoiceGatewayDeviceDiscovery.updated_at, True)]
    form_excluded_columns = [
        VoiceGatewayDeviceDiscovery.owner_user,
        VoiceGatewayDeviceDiscovery.reporter_user,
        VoiceGatewayDeviceDiscovery.matched_line,
    ]
    column_labels = {
        VoiceGatewayDeviceDiscovery.owner_user_id: "客户账号",
        VoiceGatewayDeviceDiscovery.reporter_user_id: "上报账号",
        VoiceGatewayDeviceDiscovery.matched_line_id: "已匹配线路",
        VoiceGatewayDeviceDiscovery.status: "状态",
        VoiceGatewayDeviceDiscovery.source: "来源",
        VoiceGatewayDeviceDiscovery.gateway_profile_key: "网关档案",
        VoiceGatewayDeviceDiscovery.gateway_label: "网关名称",
        VoiceGatewayDeviceDiscovery.device_admin_url: "设备后台地址",
        VoiceGatewayDeviceDiscovery.device_ip: "设备IP",
        VoiceGatewayDeviceDiscovery.device_mac: "设备MAC",
        VoiceGatewayDeviceDiscovery.device_serial: "设备序列号",
        VoiceGatewayDeviceDiscovery.sip_port: "SIP端口",
        VoiceGatewayDeviceDiscovery.summary: "摘要",
        VoiceGatewayDeviceDiscovery.detail: "详情",
        VoiceGatewayDeviceDiscovery.evidence_json: "检测证据",
        VoiceGatewayDeviceDiscovery.created_at: "创建时间",
        VoiceGatewayDeviceDiscovery.updated_at: "更新时间",
    }


class VoiceGatewayLineEventAdmin(ModelView, model=VoiceGatewayLineEvent):
    name = "线路验收事件"
    name_plural = "线路验收事件"
    icon = "fa-solid fa-list-check"

    can_edit = False
    column_list = [
        VoiceGatewayLineEvent.line_id,
        VoiceGatewayLineEvent.event_type,
        VoiceGatewayLineEvent.status,
        VoiceGatewayLineEvent.summary,
        VoiceGatewayLineEvent.created_at,
    ]
    column_searchable_list = [VoiceGatewayLineEvent.event_type, VoiceGatewayLineEvent.status, VoiceGatewayLineEvent.summary]
    column_sortable_list = [VoiceGatewayLineEvent.created_at, VoiceGatewayLineEvent.status]
    column_default_sort = [(VoiceGatewayLineEvent.created_at, True)]
    column_labels = {
        VoiceGatewayLineEvent.line_id: "线路",
        VoiceGatewayLineEvent.owner_user_id: "客户账号",
        VoiceGatewayLineEvent.actor_user_id: "操作人",
        VoiceGatewayLineEvent.event_type: "事件类型",
        VoiceGatewayLineEvent.status: "状态",
        VoiceGatewayLineEvent.summary: "摘要",
        VoiceGatewayLineEvent.detail: "详情",
        VoiceGatewayLineEvent.evidence_json: "证据JSON",
        VoiceGatewayLineEvent.created_at: "创建时间",
    }


class SystemAuditLogAdmin(ModelView, model=SystemAuditLog):
    name = "系统审计"
    name_plural = "系统审计"
    icon = "fa-solid fa-shield-halved"

    can_create = False
    can_edit = False
    column_list = [
        SystemAuditLog.actor,
        SystemAuditLog.action,
        SystemAuditLog.target_type,
        SystemAuditLog.summary,
        SystemAuditLog.created_at,
    ]
    column_searchable_list = [SystemAuditLog.actor, SystemAuditLog.action, SystemAuditLog.summary]
    column_sortable_list = [SystemAuditLog.created_at]
    column_default_sort = [(SystemAuditLog.created_at, True)]
    column_labels = {
        SystemAuditLog.actor: "操作者",
        SystemAuditLog.action: "动作",
        SystemAuditLog.target_type: "对象类型",
        SystemAuditLog.target_id: "对象ID",
        SystemAuditLog.summary: "摘要",
        SystemAuditLog.before_value: "变更前",
        SystemAuditLog.after_value: "变更后",
        SystemAuditLog.created_at: "时间",
    }


class AuditLogAdmin(ModelView, model=AuditLog):
    name = "客户审计"
    name_plural = "客户审计日志"
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
    admin.add_view(AdminUserAdmin)
    admin.add_view(UserAdmin)
    admin.add_view(RoleAdmin)
    admin.add_view(UserRoleAdmin)
    admin.add_view(RegistrationRequestAdmin)
    admin.add_view(AuditLogAdmin)
    admin.add_view(LeadProviderConfigAdmin)
    admin.add_view(LeadCollectionTaskAdmin)
    admin.add_view(LeadCollectionRunAdmin)
    admin.add_view(RawLeadRecordAdmin)
    admin.add_view(PlatformBrowserSessionAdmin)
    admin.add_view(MerchantLeadAdmin)
    admin.add_view(OutreachTaskAdmin)
    admin.add_view(CallScriptAdmin)
    admin.add_view(CallRecordAdmin)
    admin.add_view(RecallRuleAdmin)
    admin.add_view(DirectMessageAccountAdmin)
    admin.add_view(DirectMessagePlatformConfigAdmin)
    admin.add_view(DirectMessageTemplateAdmin)
    admin.add_view(DirectMessageConversationAdmin)
    admin.add_view(DirectMessageAdmin)
    admin.add_view(CommentInterceptSourceAdmin)
    admin.add_view(SocialCommentAdmin)
    admin.add_view(CommentLeadConversionAdmin)
    admin.add_view(IntentCustomerAdmin)
    admin.add_view(IntentEventAdmin)
    admin.add_view(FollowUpWorkOrderAdmin)
    admin.add_view(LearningSuggestionAdmin)
    admin.add_view(KnowledgeBaseItemAdmin)
    admin.add_view(LearningExperimentAdmin)
    admin.add_view(VoiceProfileAdmin)
    admin.add_view(VoiceTrainingJobAdmin)
    admin.add_view(VoiceSampleAdmin)
    admin.add_view(VoiceCloneRecordAdmin)
    admin.add_view(VoiceUsageRecordAdmin)
    admin.add_view(ReportExportAdmin)
    admin.add_view(VoiceGatewayLineAdmin)
    admin.add_view(VoiceGatewayDeviceDiscoveryAdmin)
    admin.add_view(VoiceGatewayLineEventAdmin)
    admin.add_view(SystemSettingAdmin)
    admin.add_view(SystemAuditLogAdmin)
