from secrets import compare_digest

from fastapi import FastAPI, Request
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.responses import RedirectResponse

from app.core.config import settings
from app.db.session import engine
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
from app.models.lead import MerchantLead
from app.models.operations import ReportExport, SystemAuditLog, SystemSetting
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
    admin.add_view(SystemSettingAdmin)
    admin.add_view(SystemAuditLogAdmin)
