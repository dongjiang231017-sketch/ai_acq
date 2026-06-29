from secrets import compare_digest

from fastapi import FastAPI, Request
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.responses import RedirectResponse

from app.core.config import settings
from app.db.session import engine
from app.models.lead import MerchantLead
from app.models.task import (
    CallRecord,
    CallScript,
    DirectMessage,
    DirectMessageAccount,
    DirectMessageConversation,
    DirectMessagePlatformConfig,
    DirectMessageTemplate,
    OutreachTask,
    RecallRule,
)


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))

        is_valid = compare_digest(username, settings.admin_username) and compare_digest(password, settings.admin_password)
        if is_valid:
            request.session.update({"admin_user": username})
        return is_valid

    async def logout(self, request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(request.url_for("admin:login"), status_code=302)

    async def authenticate(self, request: Request) -> bool:
        return request.session.get("admin_user") == settings.admin_username


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


def setup_admin(app: FastAPI) -> None:
    authentication_backend = AdminAuth(secret_key=settings.admin_secret_key, same_site="lax")
    admin = Admin(
        app,
        engine=engine,
        title="AI获客管理后台",
        base_url="/admin",
        authentication_backend=authentication_backend,
    )
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
