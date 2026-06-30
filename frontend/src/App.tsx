import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BarChart3,
  Bot,
  CheckCircle2,
  ClipboardList,
  Clock3,
  Code2,
  Database,
  ExternalLink,
  Headphones,
  KeyRound,
  MessageSquareText,
  PhoneCall,
  Plus,
  Radio,
  RefreshCw,
  Search,
  Settings,
  ShieldAlert,
  Sparkles,
  Upload,
  Users,
  Zap,
} from "lucide-react";
import {
  CallRecord,
  CallScript,
  ChannelReport,
  DmAccount,
  DmConversation,
  DmDesktopLoginEvidence,
  DmLoginSession,
  DmMessage,
  DmOverview,
  DmPlatformConfig,
  DmSyncResult,
  DmTemplate,
  FollowUpWorkOrder,
  IntentCustomer,
  IntentEvent,
  IntentOverview,
  Lead,
  ModuleSummary,
  OutboundOverview,
  OutreachTask,
  RecallRule,
  ReportExport,
  ReportOverview,
  SalesPerformanceReport,
  SystemVoice,
  TelephonyConfig,
  TelephonyHealth,
  TelephonyPreflight,
  TelephonyTestCallResult,
  VoiceCloneRecord,
  VoiceOverview,
  VoiceProfile,
  VoiceProviderStatus,
  VoiceSample,
  VoiceTrainingJob,
  VoiceUsageRecord,
  SettingsOverview,
  SystemSetting,
  api,
  apiAssetUrl,
} from "./lib/api";

const icons = [BarChart3, Search, Database, PhoneCall, MessageSquareText, Users, Headphones, ClipboardList, Settings];
const customerHiddenModuleKeys = new Set(["learning"]);
const customerVisibleModules = (items: ModuleSummary[]) => items.filter((module) => !customerHiddenModuleKeys.has(module.key));

const fallbackModules: ModuleSummary[] = [
  { key: "dashboard", name: "实时工作台", description: "监控今日获客、外呼、私信和预警。", pageCount: 4, status: "ready" },
  { key: "collector", name: "线索采集", description: "采集任务、来源配置、清洗规则。", pageCount: 5, status: "ready" },
  { key: "leads", name: "商家线索库", description: "商家资料、电话库、主页和去重审核。", pageCount: 5, status: "ready" },
  { key: "outbound", name: "AI外呼系统", description: "外呼任务、话术流程、通话记录。", pageCount: 6, status: "ready" },
  { key: "dm", name: "平台私信系统", description: "平台个人号、私信任务、模板和会话。", pageCount: 7, status: "ready" },
  { key: "intent", name: "意向客户池", description: "客户分级、工单跟进和分配规则。", pageCount: 4, status: "ready" },
  { key: "voice", name: "声音档案", description: "授权、音色复刻和使用记录。", pageCount: 4, status: "ready" },
  { key: "reports", name: "数据报表", description: "渠道、绩效和导出中心。", pageCount: 4, status: "ready" },
  { key: "settings", name: "系统设置", description: "线路、账号和合规保护。", pageCount: 4, status: "ready" },
];

type DmLoginWebviewElement = HTMLElement & {
  getWebContentsId?: () => number;
  reload?: () => void;
};

const fallbackLeads: Lead[] = [
  {
    id: "lead_1",
    name: "青岚美甲工作室",
    platform: "视频号",
    city: "南昌",
    category: "丽人美业",
    phone: "13800000001",
    contactName: "陈店长",
    platformUrl: null,
    source: "平台采集",
    intentScore: 86,
    status: "待外呼",
  },
  {
    id: "lead_2",
    name: "南昌餐饮店",
    platform: "美团",
    city: "南昌",
    category: "本地餐饮",
    phone: "13800000002",
    contactName: "周经理",
    platformUrl: null,
    source: "导入线索",
    intentScore: 58,
    status: "待外呼",
  },
  {
    id: "lead_3",
    name: "宠物生活馆",
    platform: "抖音",
    city: "南昌",
    category: "宠物服务",
    phone: "13800000003",
    contactName: "李老板",
    platformUrl: "https://business.douyin.com/",
    source: "公开商源",
    intentScore: 77,
    status: "跟进中",
  },
];

const fallbackTasks: OutreachTask[] = [
  {
    id: "task_1",
    name: "南昌本地商家首轮外呼",
    channel: "call",
    status: "运行中",
    targetCount: 120,
    completedCount: 326,
    connectedCount: 91,
    intentCount: 28,
    failedCount: 32,
    concurrency: 10,
    scriptId: null,
    scheduledAt: null,
    startedAt: null,
    finishedAt: null,
  },
  {
    id: "task_2",
    name: "高意向商家私信触达",
    channel: "dm",
    status: "待启动",
    targetCount: 68,
    completedCount: 0,
    connectedCount: 0,
    intentCount: 0,
    failedCount: 0,
    concurrency: 1,
    scriptId: null,
    scheduledAt: null,
    startedAt: null,
    finishedAt: null,
  },
];

const fallbackOverview: OutboundOverview = {
  aiSeats: 10,
  activeCalls: 7,
  needsHandoff: 2,
  silentAlerts: 1,
  todayCalls: 326,
  connectedRate: 28,
  intentCount: 58,
};

const fallbackTelephonyConfig: TelephonyConfig = {
  gatewayMode: "simulator",
  queueEnabled: false,
  queueName: "ai_acq:outbound_tasks",
  redisUrlConfigured: true,
  asteriskHost: "127.0.0.1",
  asteriskAmiPort: 5038,
  asteriskUsernameConfigured: false,
  asteriskTrunkName: "uc100",
  asteriskMaxChannels: 1,
  asteriskLiveCallEnabled: false,
  asteriskBulkCallEnabled: false,
};

const fallbackTelephonyHealth: TelephonyHealth = {
  checkedAt: new Date().toISOString(),
  gatewayMode: "simulator",
  configured: false,
  liveCallEnabled: false,
  bulkCallEnabled: false,
  amiReachable: false,
  authenticated: false,
  pingOk: false,
  trunkConfigured: false,
  trunkReachable: null,
  trunkStatus: "待配置",
  maxChannels: 1,
  readyForTestCall: false,
  errors: ["Asterisk AMI 账号或密码未配置"],
};

const fallbackTelephonyPreflight: TelephonyPreflight = {
  checkedAt: fallbackTelephonyHealth.checkedAt,
  readyForDeviceTest: false,
  readyForSingleNumberTest: false,
  readyForBulkTasks: false,
  nextStep: "先配置 AMI 账号、UC100 trunk，并切到 Asterisk 真实线路模式。",
  health: fallbackTelephonyHealth,
  steps: [
    {
      key: "gateway_mode",
      label: "网关模式",
      status: "warn",
      detail: "当前仍是模拟线路，代码不会访问 UC100。",
      action: "实机联调时设置 TELEPHONY_GATEWAY_MODE=asterisk。",
    },
    {
      key: "ami_credentials",
      label: "AMI 账号",
      status: "fail",
      detail: "AMI 用户名或密码未配置。",
      action: "在 backend/.env 配置 ASTERISK_AMI_USERNAME 和 ASTERISK_AMI_PASSWORD。",
    },
  ],
};

const fallbackRecords: CallRecord[] = [
  {
    id: "call_1",
    taskId: "task_1",
    leadId: "lead_1",
    merchantName: "青岚美甲工作室",
    phone: "13800000001",
    aiSeat: "AI-03",
    durationSeconds: 138,
    intentLevel: "B",
    currentNode: "价格异议",
    outcome: "已接通",
    transcript: "商家：怎么收费？AI：可以先给您发基础方案。",
    gatewayCallId: "sim-task_1-lead_1",
    gatewayStatus: "completed",
    rawPayload: '{"provider":"simulator","disposition":"connected"}',
    needHandoff: true,
    recallAt: null,
    createdAt: new Date().toISOString(),
  },
  {
    id: "call_2",
    taskId: "task_1",
    leadId: "lead_2",
    merchantName: "南昌餐饮店",
    phone: "13800000002",
    aiSeat: "AI-07",
    durationSeconds: 46,
    intentLevel: "C",
    currentNode: "老板忙",
    outcome: "稍后联系",
    transcript: "商家：现在忙，下午再打。",
    gatewayCallId: "sim-task_1-lead_2",
    gatewayStatus: "completed",
    rawPayload: '{"provider":"simulator","disposition":"busy"}',
    needHandoff: false,
    recallAt: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
    createdAt: new Date().toISOString(),
  },
  {
    id: "call_3",
    taskId: "task_1",
    leadId: "lead_3",
    merchantName: "宠物生活馆",
    phone: "13800000003",
    aiSeat: "AI-01",
    durationSeconds: 182,
    intentLevel: "A",
    currentNode: "加微信",
    outcome: "有意向",
    transcript: "商家：可以发一下资料。",
    gatewayCallId: "sim-task_1-lead_3",
    gatewayStatus: "completed",
    rawPayload: '{"provider":"simulator","disposition":"interested"}',
    needHandoff: true,
    recallAt: null,
    createdAt: new Date().toISOString(),
  },
];

const fallbackScripts: CallScript[] = [
  {
    id: "script_1",
    name: "视频号团购商家邀约话术",
    opening: "您好，我是视频号本地生活服务顾问，看到您店铺适合做团购曝光。",
    qualification: "目前店里是否有团购、直播或短视频获客需求？",
    objection: "如果您担心费用，我们可以先按基础入驻和活动试跑讲。",
    closing: "我先把入驻资料和适合您品类的案例发您。",
    isActive: true,
    createdAt: new Date().toISOString(),
  },
];

const fallbackRules: RecallRule[] = [
  {
    id: "rule_1",
    name: "默认重拨规则",
    noAnswerIntervalMinutes: 240,
    busyIntervalMinutes: 120,
    maxAttempts: 3,
    quietStart: "21:00",
    quietEnd: "09:00",
    enabled: true,
  },
];

const fallbackDmOverview: DmOverview = {
  accounts: 3,
  activeAccounts: 3,
  todaySent: 128,
  replies: 32,
  needsHandoff: 9,
  intentCount: 18,
};

const fallbackDmAccounts: DmAccount[] = [
  {
    id: "dm_account_1",
    platform: "美团",
    accountName: "美团个人号-南昌本地生活",
    loginLabel: "待绑定个人号",
    status: "待登录",
    browserProfileKey: "meituan-nanchang-local",
    browserProfilePath: ".dm_browser_profiles/meituan-nanchang-local",
    sessionStatus: "未登录",
    riskStatus: "正常",
    dailyLimit: 200,
    sentToday: 86,
    minSendIntervalSeconds: 0,
    cooldownUntil: null,
    lastSentAt: new Date().toISOString(),
    lastSyncAt: new Date().toISOString(),
    lastLoginCheckAt: new Date().toISOString(),
    lastError: null,
    createdAt: new Date().toISOString(),
  },
  {
    id: "dm_account_2",
    platform: "饿了么",
    accountName: "饿了么个人号-餐饮招商",
    loginLabel: "待绑定个人号",
    status: "待登录",
    browserProfileKey: "eleme-food-growth",
    browserProfilePath: ".dm_browser_profiles/eleme-food-growth",
    sessionStatus: "未登录",
    riskStatus: "正常",
    dailyLimit: 150,
    sentToday: 0,
    minSendIntervalSeconds: 45,
    cooldownUntil: null,
    lastSentAt: null,
    lastSyncAt: null,
    lastLoginCheckAt: null,
    lastError: null,
    createdAt: new Date().toISOString(),
  },
  {
    id: "dm_account_3",
    platform: "抖音",
    accountName: "抖音个人号-团购拓客",
    loginLabel: "待绑定个人号",
    status: "待登录",
    browserProfileKey: "douyin-group-growth",
    browserProfilePath: ".dm_browser_profiles/douyin-group-growth",
    sessionStatus: "未登录",
    riskStatus: "正常",
    dailyLimit: 120,
    sentToday: 0,
    minSendIntervalSeconds: 60,
    cooldownUntil: null,
    lastSentAt: null,
    lastSyncAt: null,
    lastLoginCheckAt: null,
    lastError: null,
    createdAt: new Date().toISOString(),
  },
];

const createFallbackDmPlatformConfig = (id: string, platform: string): DmPlatformConfig => ({
  id,
  platform,
  homeUrl: "",
  inboxUrl: "",
  merchantSearchUrl: "",
  loginCheckSelector: "",
  riskCheckSelector: "",
  merchantLinkSelector: "",
  messageButtonSelector: "",
  inputSelector: "",
  sendButtonSelector: "",
  sentSuccessSelector: "",
  unreadSelector: "",
  conversationItemSelector: "",
  conversationTitleSelector: "",
  messageTextSelector: "",
  enabled: false,
  createdAt: new Date().toISOString(),
});

const fallbackDmPlatformConfigs: DmPlatformConfig[] = [
  createFallbackDmPlatformConfig("dm_platform_1", "美团"),
  createFallbackDmPlatformConfig("dm_platform_2", "饿了么"),
  createFallbackDmPlatformConfig("dm_platform_3", "抖音"),
];

const fallbackDmSyncResult: DmSyncResult = {
  checked: 0,
  newReplies: 0,
  needsHandoff: 0,
};

const platformLoginUrls: Record<string, string> = {
  美团: "https://passport.meituan.com/account/unitivelogin",
  饿了么: "https://h5.ele.me/login/",
  抖音: "https://www.douyin.com/",
};

const supportedDmPlatforms = ["美团", "饿了么", "抖音"] as const;
const unsupportedDmPlatformTips: Record<string, string> = {
  视频号: "视频号助手当前不支持主动私信商家，可改用外呼或其他合规触达方式。",
};

function isSupportedDmPlatform(platform: string) {
  return supportedDmPlatforms.includes(platform as (typeof supportedDmPlatforms)[number]);
}

function isSupportedDmAccount(account: DmAccount) {
  return isSupportedDmPlatform(account.platform) && account.status !== "不支持私信";
}

function isLegacyBusinessBackendUrl(platform: string, url?: string | null) {
  const normalized = (url ?? "").trim().replace(/\/+$/, "");
  return (
    (platform === "美团" && normalized === "https://e.meituan.com") ||
    (platform === "饿了么" && normalized === "https://open.shop.ele.me") ||
    (platform === "抖音" && normalized === "https://business.douyin.com")
  );
}

function personalLoginUrl(platform: string, url?: string | null) {
  const value = (url ?? "").trim();
  return value && !isLegacyBusinessBackendUrl(platform, value) ? value : "";
}

function loginEntryHost(url: string) {
  if (!url) return "未配置";
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function accountLoginLabel(account: DmAccount) {
  const label = account.loginLabel?.trim();
  if (!label || label === "待绑定真实平台账号" || label === "待绑定商家号") return "待绑定个人号";
  return label;
}

function isDmLoginReadyStatus(status?: string | null) {
  return status === "已登录";
}

function displayDmLoginStatus(status?: string | null) {
  if (status === "模拟可用") return "未检测";
  return status || "未登录";
}

function dmLoginStatusHint(status?: string | null) {
  if (status === "已登录") return "已检测到该个人号的真实平台登录态。";
  if (status === "模拟可用") return "旧模拟状态不会放行，请重新完成真实登录检测。";
  return "在客户端内置登录区完成平台登录，然后点击登录后检测。";
}

function platformLoginEntryLabel(config: DmPlatformConfig) {
  if (isLegacyBusinessBackendUrl(config.platform, config.homeUrl)) return "客户端内置个人号入口";
  if (config.homeUrl?.trim()) return "客户端内置个人号入口";
  if (platformLoginUrls[config.platform]) return "客户端内置个人号入口";
  return "客户端内置个人号入口";
}

const defaultDmPlatformForm: Omit<DmPlatformConfig, "id" | "createdAt"> = {
  platform: "美团",
  homeUrl: "",
  inboxUrl: "",
  merchantSearchUrl: "",
  loginCheckSelector: "",
  riskCheckSelector: "",
  merchantLinkSelector: "",
  messageButtonSelector: "",
  inputSelector: "",
  sendButtonSelector: "",
  sentSuccessSelector: "",
  unreadSelector: "",
  conversationItemSelector: "",
  conversationTitleSelector: "",
  messageTextSelector: "",
  enabled: false,
};

const fallbackDmTemplates: DmTemplate[] = [
  {
    id: "dm_template_1",
    name: "视频号团购邀约私信",
    platform: "通用",
    content: "您好，看到{商家名称}适合做视频号本地生活团购曝光，想了解下您是否考虑新增线上获客渠道？",
    isActive: true,
    createdAt: new Date().toISOString(),
  },
];

const fallbackDmConversations: DmConversation[] = [
  {
    id: "dm_conv_1",
    taskId: "task_2",
    leadId: "lead_3",
    accountId: "dm_account_1",
    platform: "美团",
    merchantName: "宠物生活馆",
    status: "已回复",
    intentLevel: "A",
    lastMessage: "可以，发我入驻资料看看。",
    lastMessageAt: new Date().toISOString(),
    needHandoff: true,
    createdAt: new Date().toISOString(),
  },
  {
    id: "dm_conv_2",
    taskId: "task_2",
    leadId: "lead_2",
    accountId: "dm_account_1",
    platform: "美团",
    merchantName: "南昌餐饮店",
    status: "已发送",
    intentLevel: "C",
    lastMessage: "您好，看到南昌餐饮店适合做视频号本地生活团购曝光。",
    lastMessageAt: new Date().toISOString(),
    needHandoff: false,
    createdAt: new Date().toISOString(),
  },
];

const fallbackDmMessages: DmMessage[] = [
  {
    id: "dm_msg_1",
    conversationId: "dm_conv_1",
    direction: "outbound",
    content: "您好，看到宠物生活馆适合做视频号本地生活团购曝光，想了解下您是否考虑新增线上获客渠道？",
    status: "已回复",
    externalMessageId: "sim-dm-task_2-lead_3",
    rawPayload: '{"provider":"simulator","disposition":"interested_reply"}',
    createdAt: new Date().toISOString(),
  },
  {
    id: "dm_msg_2",
    conversationId: "dm_conv_1",
    direction: "inbound",
    content: "可以，发我入驻资料看看。",
    status: "已接收",
    externalMessageId: "sim-dm-task_2-lead_3-reply",
    rawPayload: '{"provider":"simulator","direction":"inbound"}',
    createdAt: new Date().toISOString(),
  },
];

const fallbackIntentOverview: IntentOverview = {
  totalCustomers: 3,
  highIntent: 2,
  needsHandoff: 2,
  pendingWorkOrders: 2,
  dncBlocked: 0,
};

const fallbackIntentCustomers: IntentCustomer[] = [
  {
    id: "intent_1",
    leadId: "lead_3",
    merchantName: "宠物生活馆",
    platform: "美团",
    city: "南昌",
    category: "宠物服务",
    contactName: "李老板",
    phone: "13800000003",
    intentLevel: "A",
    intentScore: 92,
    sourceChannels: "外呼,私信",
    latestSignal: "可以，发我入驻资料看看。",
    evidenceSummary: "外呼加私信均表现为高意向",
    ownerName: "待分配",
    followStatus: "待分配",
    nextFollowAt: null,
    needHandoff: true,
    dncStatus: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "intent_2",
    leadId: "lead_1",
    merchantName: "青岚美甲工作室",
    platform: "视频号",
    city: "南昌",
    category: "丽人美业",
    contactName: "陈店长",
    phone: "13800000001",
    intentLevel: "B",
    intentScore: 86,
    sourceChannels: "外呼",
    latestSignal: "商家追问费用，需要发基础方案。",
    evidenceSummary: "价格异议后仍愿意收资料",
    ownerName: "待分配",
    followStatus: "待分配",
    nextFollowAt: null,
    needHandoff: true,
    dncStatus: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const fallbackIntentEvents: IntentEvent[] = [
  {
    id: "intent_event_1",
    customerId: "intent_1",
    leadId: "lead_3",
    sourceType: "dm_conversation",
    sourceRecordId: "dm_conv_1",
    channel: "私信",
    intentLevel: "A",
    summary: "已回复",
    evidenceText: "可以，发我入驻资料看看。",
    needHandoff: true,
    createdAt: new Date().toISOString(),
  },
  {
    id: "intent_event_2",
    customerId: "intent_2",
    leadId: "lead_1",
    sourceType: "call_record",
    sourceRecordId: "call_1",
    channel: "外呼",
    intentLevel: "B",
    summary: "已接通",
    evidenceText: "商家：怎么收费？AI：可以先给您发基础方案。",
    needHandoff: true,
    createdAt: new Date().toISOString(),
  },
];

const fallbackWorkOrders: FollowUpWorkOrder[] = [
  {
    id: "work_order_1",
    customerId: "intent_1",
    title: "宠物生活馆 A级意向跟进",
    ownerName: "待分配",
    status: "待分配",
    priority: "P0",
    slaDueAt: new Date(Date.now() + 4 * 60 * 60 * 1000).toISOString(),
    lastNote: "私信回复要求发送资料",
    closedReason: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "work_order_2",
    customerId: "intent_2",
    title: "青岚美甲工作室 B级意向跟进",
    ownerName: "待分配",
    status: "待分配",
    priority: "P1",
    slaDueAt: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
    lastNote: "价格异议后需要人工发案例",
    closedReason: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const qwenTtsPresetVoices = [
  { voiceParam: "Cherry", name: "芊悦", description: "阳光积极、亲切自然小姐姐（女性）", gender: "女声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Serena", name: "苏瑶", description: "温柔小姐姐（女性）", gender: "女声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Ethan", name: "晨煦", description: "标准普通话，带部分北方口音。阳光、温暖、活力、朝气（男性）", gender: "男声", style: "标准普通话", scenario: "默认外呼" },
  { voiceParam: "Chelsie", name: "千雪", description: "二次元虚拟女友（女性）", gender: "女声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Momo", name: "茉兔", description: "撒娇搞怪，逗你开心（女性）", gender: "女声", style: "轻松亲和", scenario: "轻松互动" },
  { voiceParam: "Vivian", name: "十三", description: "拽拽的、可爱的小暴躁（女性）", gender: "女声", style: "轻松亲和", scenario: "轻松互动" },
  { voiceParam: "Moon", name: "月白", description: "率性帅气的月白（男性）", gender: "男声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Maia", name: "四月", description: "知性与温柔的碰撞（女性）", gender: "女声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Kai", name: "凯", description: "耳朵的一场 SPA（男性）", gender: "男声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Nofish", name: "不吃鱼", description: "不会翘舌音的设计师（男性）", gender: "男声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Bella", name: "萌宝", description: "喝酒不打醉拳的小萝莉（女性）", gender: "女声", style: "轻松亲和", scenario: "轻松互动" },
  { voiceParam: "Jennifer", name: "詹妮弗", description: "品牌级、电影质感般美语女声（女性）", gender: "女声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Ryan", name: "甜茶", description: "节奏拉满，戏感炸裂，真实与张力共舞（男性）", gender: "男声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Katerina", name: "卡捷琳娜", description: "御姐音色，韵律回味十足（女性）", gender: "女声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Aiden", name: "艾登", description: "精通厨艺的美语大男孩（男性）", gender: "男声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Eldric Sage", name: "沧明子", description: "沉稳睿智的老者，沧桑如松却心明如镜（男性）", gender: "男声", style: "沉稳叙事", scenario: "方案说明" },
  { voiceParam: "Mia", name: "乖小妹", description: "温顺如春水，乖巧如初雪（女性）", gender: "女声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Mochi", name: "沙小弥", description: "聪明伶俐的小大人，童真未泯却早慧如禅（男性）", gender: "男声", style: "轻松亲和", scenario: "轻松互动" },
  { voiceParam: "Bellona", name: "燕铮莺", description: "声音洪亮，吐字清晰，人物鲜活，听得人热血沸腾；金戈铁马入梦来，字正腔圆间尽显千面人声的江湖（女性）", gender: "女声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Vincent", name: "田叔", description: "一口独特的沙哑烟嗓，一开口便道尽了千军万马与江湖豪情（男性）", gender: "男声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Bunny", name: "萌小姬", description: "“萌属性”爆棚的小萝莉（女性）", gender: "女声", style: "轻松亲和", scenario: "轻松互动" },
  { voiceParam: "Neil", name: "阿闻", description: "平直的基线语调，字正腔圆的咬字发音，这就是最专业的新闻主持人（男性）", gender: "男声", style: "专业播报", scenario: "新闻播报" },
  { voiceParam: "Elias", name: "墨讲师", description: "既保持学科严谨性，又通过叙事技巧将复杂知识转化为可消化的认知模块（女性）", gender: "女声", style: "知识讲解", scenario: "内容讲解" },
  { voiceParam: "Arthur", name: "徐大爷", description: "被岁月和旱烟浸泡过的质朴嗓音，不疾不徐地摇开了满村的奇闻异事（男性）", gender: "男声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Nini", name: "邻家妹妹", description: "糯米糍一样又软又黏的嗓音，那一声声拉长了的“哥哥”，甜得能把人的骨头都叫酥了（女性）", gender: "女声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Seren", name: "小婉", description: "温和舒缓的声线，助你更快地进入睡眠，晚安，好梦（女性）", gender: "女声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Pip", name: "顽屁小孩", description: "调皮捣蛋却充满童真的他来了，这是你记忆中的小新吗（男性）", gender: "男声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Stella", name: "少女阿月", description: "平时是甜到发腻的迷糊少女音，但在喊出“代表月亮消灭你”时，瞬间充满不容置疑的爱与正义（女性）", gender: "女声", style: "自然对话", scenario: "客服外呼" },
  { voiceParam: "Bodega", name: "博德加", description: "热情的西班牙大叔（男性）", gender: "男声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Sonrisa", name: "索尼莎", description: "热情开朗的拉美大姐（女性）", gender: "女声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Alek", name: "阿列克", description: "一开口，是战斗民族的冷，也是毛呢大衣下的暖（男性）", gender: "男声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Dolce", name: "多尔切", description: "慵懒的意大利大叔（男性）", gender: "男声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Sohee", name: "素熙", description: "温柔开朗，情绪丰富的韩国欧尼（女性）", gender: "女声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Ono Anna", name: "小野杏", description: "鬼灵精怪的青梅竹马（女性）", gender: "女声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Lenn", name: "莱恩", description: "理性是底色，叛逆藏在细节里——穿西装也听后朋克的德国青年（男性）", gender: "男声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Emilien", name: "埃米尔安", description: "浪漫的法国大哥哥（男性）", gender: "男声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Andre", name: "安德雷", description: "声音磁性，自然舒服、沉稳男生（男性）", gender: "男声", style: "沉稳叙事", scenario: "方案说明" },
  { voiceParam: "Radio Gol", name: "拉迪奥·戈尔", description: "足球诗人 Rádio Gol！今天我要用名字为你们解说足球（男性）", gender: "男声", style: "多语种", scenario: "多语种触达" },
  { voiceParam: "Jada", name: "上海-阿珍", description: "风风火火的沪上阿姐（女性）", gender: "女声", style: "地方方言", scenario: "本地触达" },
  { voiceParam: "Dylan", name: "北京-晓东", description: "北京胡同里长大的少年（男性）", gender: "男声", style: "地方方言", scenario: "本地触达" },
  { voiceParam: "Li", name: "南京-老李", description: "耐心的瑜伽老师（男性）", gender: "男声", style: "地方方言", scenario: "本地触达" },
  { voiceParam: "Marcus", name: "陕西-秦川", description: "面宽话短，心实声沉——老陕的味道（男性）", gender: "男声", style: "地方方言", scenario: "本地触达" },
  { voiceParam: "Roy", name: "闽南-阿杰", description: "诙谐直爽、市井活泼的台湾哥仔形象（男性）", gender: "男声", style: "地方方言", scenario: "本地触达" },
  { voiceParam: "Peter", name: "天津-李彼得", description: "天津相声，专业捧哏（男性）", gender: "男声", style: "地方方言", scenario: "本地触达" },
  { voiceParam: "Sunny", name: "四川-晴儿", description: "甜到你心里的川妹子（女性）", gender: "女声", style: "地方方言", scenario: "本地触达" },
  { voiceParam: "Eric", name: "四川-程川", description: "一个跳脱市井的四川成都男子（男性）", gender: "男声", style: "地方方言", scenario: "本地触达" },
  { voiceParam: "Rocky", name: "粤语-阿强", description: "幽默风趣的阿强，在线陪聊（男性）", gender: "男声", style: "地方方言", scenario: "本地触达" },
  { voiceParam: "Kiki", name: "粤语-阿清", description: "甜美的港妹闺蜜（女性）", gender: "女声", style: "地方方言", scenario: "本地触达" },
] as const;

function qwenTtsVoiceId(voiceParam: string) {
  return `qwen_tts_${voiceParam.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "")}`;
}

const fallbackSystemVoices: SystemVoice[] = qwenTtsPresetVoices.map((voice) => ({
  id: qwenTtsVoiceId(voice.voiceParam),
  name: `${voice.name}（${voice.voiceParam}）`,
  provider: "Qwen-TTS",
  voiceParam: voice.voiceParam,
  gender: voice.gender,
  style: voice.style,
  scenario: voice.scenario,
  status: "可用",
  isDefault: voice.voiceParam === "Ethan",
  sampleText: voice.description,
}));

const fallbackVoiceOverview: VoiceOverview = {
  profiles: 1,
  usableProfiles: 0,
  pendingAuthorization: 1,
  trainingJobs: 0,
  usageRecords: 1,
  fallbackUsage: 0,
  systemVoices: fallbackSystemVoices.length,
  defaultVoice: "晨煦（Ethan）",
  cloneTrainingEnabled: false,
  cloneEngineName: "",
  cloneEngineStatus: "未接入",
  cloneEngineMessage: "真实声音克隆服务未接入",
};

const fallbackVoiceProviderStatus: VoiceProviderStatus = {
  provider: "dashscope",
  configured: false,
  ready: false,
  status: "未启用",
  message: "请配置 DashScope/CosyVoice 后生成复刻音色。",
  engineName: "DashScope CosyVoice",
  cloneModel: "cosyvoice-v2",
  ttsModel: "cosyvoice-v2",
  samplePublicBaseUrlConfigured: false,
};

const fallbackVoiceProfiles: VoiceProfile[] = [
  {
    id: "voice_2",
    name: "招商顾问克隆音色",
    ownerName: "待授权顾问",
    scenario: "外呼",
    status: "待授权",
    authorizationStatus: "待提交",
    sampleCount: 0,
    fallbackVoice: "晨煦（Ethan）",
    consentMaterial: "等待上传授权材料和样本元数据。",
    riskNote: "未授权前不可复刻、不可被任务选择。",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const fallbackVoiceTrainingJobs: VoiceTrainingJob[] = [];

const fallbackVoiceSamples: VoiceSample[] = [];

const fallbackVoiceCloneRecords: VoiceCloneRecord[] = [];

const fallbackVoiceUsageRecords: VoiceUsageRecord[] = [
  {
    id: "voice_usage_1",
    profileId: null,
    taskId: null,
    merchantName: "模拟商家",
    scenario: "外呼",
    result: "使用系统内置音色：晨煦（Ethan）",
    fallbackUsed: false,
    createdAt: new Date().toISOString(),
  },
];

const fallbackReportOverview: ReportOverview = {
  totalLeads: 3,
  totalTouches: 5,
  connected: 3,
  highIntent: 3,
  pendingWorkOrders: 2,
  conversionRate: 100,
  exportJobs: 1,
  updatedAt: new Date().toISOString(),
  funnel: [
    { key: "leads", label: "商家线索", value: 3, rate: 100 },
    { key: "touches", label: "电话/私信触达", value: 5, rate: 100 },
    { key: "connected", label: "有效接通/回复", value: 3, rate: 60 },
    { key: "intent", label: "A/B 意向", value: 3, rate: 100 },
  ],
};

const fallbackChannelReports: ChannelReport[] = [
  {
    id: "collector",
    channel: "线索采集",
    leads: 3,
    touches: 0,
    connected: 0,
    intent: 2,
    handoff: 0,
    conversionRate: 67,
    status: "稳定",
    insight: "采集池已有可跟进商家，建议优先补齐联系方式。",
  },
  {
    id: "call",
    channel: "AI外呼",
    leads: 120,
    touches: 3,
    connected: 3,
    intent: 2,
    handoff: 2,
    conversionRate: 67,
    status: "重点跟进",
    insight: "人工接管较多，建议销售优先处理。",
  },
  {
    id: "dm",
    channel: "平台私信",
    leads: 68,
    touches: 2,
    connected: 1,
    intent: 1,
    handoff: 1,
    conversionRate: 50,
    status: "重点跟进",
    insight: "回复监听有人工接管信号，适合纳入销售跟进。",
  },
];

const fallbackSalesReports: SalesPerformanceReport[] = [
  {
    id: "待分配",
    ownerName: "待分配",
    assignedCustomers: 3,
    pendingWorkOrders: 2,
    closedWorkOrders: 0,
    highIntent: 3,
    handoff: 2,
    conversionRate: 100,
    lastActivityAt: new Date().toISOString(),
  },
];

const fallbackReportExports: ReportExport[] = [
  {
    id: "export_1",
    reportType: "经营总览",
    dateRange: "近30天",
    fileFormat: "xlsx",
    requester: "系统",
    status: "已生成",
    downloadUrl: "/api/reports/exports/sample/download",
    rowCount: 12,
    sensitiveFieldsIncluded: false,
    createdAt: new Date().toISOString(),
    finishedAt: new Date().toISOString(),
  },
];

const fallbackSettingsOverview: SettingsOverview = {
  totalSettings: 8,
  enabledSettings: 6,
  warningSettings: 2,
  sensitiveSettings: 0,
  auditLogs: 1,
  groups: [
    { groupKey: "telephony", label: "电话线路", total: 3, enabled: 2, warning: 1 },
    { groupKey: "dm", label: "平台账号", total: 3, enabled: 2, warning: 1 },
    { groupKey: "compliance", label: "合规保护", total: 2, enabled: 2, warning: 0 },
  ],
};

const fallbackSystemSettings: SystemSetting[] = [
  {
    id: "setting_telephony_gateway",
    groupKey: "telephony",
    itemKey: "gateway_mode",
    label: "电话网关模式",
    value: "simulator",
    valueType: "select:simulator,asterisk",
    status: "模拟模式",
    description: "控制外呼任务使用模拟网关还是真实 Asterisk/线路网关。",
    sensitive: false,
    updatedBy: "系统",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "setting_telephony_queue",
    groupKey: "telephony",
    itemKey: "queue_enabled",
    label: "外呼队列",
    value: "false",
    valueType: "boolean",
    status: "未启用",
    description: "启用后外呼任务进入队列，由 worker 按节奏执行。",
    sensitive: false,
    updatedBy: "系统",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "setting_telephony_trunk",
    groupKey: "telephony",
    itemKey: "trunk_name",
    label: "线路中继名称",
    value: "",
    valueType: "text",
    status: "待配置",
    description: "真实线路接入后的主线路别名。",
    sensitive: false,
    updatedBy: "系统",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "setting_dm_gateway",
    groupKey: "dm",
    itemKey: "gateway_mode",
    label: "私信发送模式",
    value: "simulator",
    valueType: "select:simulator,browser",
    status: "模拟模式",
    description: "控制平台私信用模拟器还是浏览器助手执行。",
    sensitive: false,
    updatedBy: "系统",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "setting_dm_live",
    groupKey: "dm",
    itemKey: "live_send_enabled",
    label: "真实发送开关",
    value: "false",
    valueType: "boolean",
    status: "受控",
    description: "真实发送属于高风险动作，默认关闭，仅在人工确认后开启。",
    sensitive: false,
    updatedBy: "系统",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "setting_dm_queue",
    groupKey: "dm",
    itemKey: "queue_enabled",
    label: "私信任务队列",
    value: "false",
    valueType: "boolean",
    status: "未启用",
    description: "启用后私信任务进入队列，便于限速和隔离执行。",
    sensitive: false,
    updatedBy: "系统",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "setting_compliance_dnc",
    groupKey: "compliance",
    itemKey: "dnc_enabled",
    label: "勿扰保护",
    value: "true",
    valueType: "boolean",
    status: "已启用",
    description: "客户拒绝触达或进入勿扰名单后阻断后续任务。",
    sensitive: false,
    updatedBy: "系统",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: "setting_compliance_refusal",
    groupKey: "compliance",
    itemKey: "refusal_stop_enabled",
    label: "拒绝即停",
    value: "true",
    valueType: "boolean",
    status: "已启用",
    description: "外呼或私信明确拒绝后停止自动追触。",
    sensitive: false,
    updatedBy: "系统",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const outboundTabs = ["外呼总览", "任务列表", "话术流程", "通话记录", "重拨规则", "实时监听"] as const;
type OutboundTab = (typeof outboundTabs)[number];
const dmTabs = ["私信总览", "任务列表", "账号管理", "轮换规则", "消息模板", "会话记录", "回复监听"] as const;
type DmTab = (typeof dmTabs)[number];
const intentTabs = ["客户池", "跟进工单", "客户详情", "分配规则"] as const;
type IntentTab = (typeof intentTabs)[number];
const voiceTabs = ["声音档案", "授权审核", "音色复刻", "使用记录"] as const;
type VoiceTab = (typeof voiceTabs)[number];
const reportsTabs = ["报表总览", "渠道分析", "销售绩效", "导出中心"] as const;
type ReportsTab = (typeof reportsTabs)[number];
const settingsTabs = ["设置总览", "电话线路", "平台账号", "合规保护"] as const;
type SettingsTab = (typeof settingsTabs)[number];

const clientSettingGroupLabels: Record<string, SettingsTab> = {
  telephony: "电话线路",
  dm: "平台账号",
  compliance: "合规保护",
};

function isClientVisibleSetting(setting: SystemSetting) {
  if (setting.itemKey === "audit_retention_days") return false;
  return Boolean(clientSettingGroupLabels[setting.groupKey]);
}

function isClientEnabledSetting(setting: SystemSetting) {
  return !["待配置", "未启用"].includes(setting.status);
}

function formatSettingValue(setting: SystemSetting, value = setting.value) {
  if (setting.valueType === "boolean") return value === "true" ? "开启" : "关闭";
  if (setting.groupKey === "telephony" && setting.itemKey === "gateway_mode") {
    return value === "asterisk" ? "真实线路" : "模拟线路";
  }
  if (setting.groupKey === "dm" && setting.itemKey === "gateway_mode") {
    return value === "browser" ? "浏览器助手" : "模拟模式";
  }
  return value || "待配置";
}

function formatSettingOption(setting: SystemSetting, option: string) {
  return formatSettingValue({ ...setting, value: option }, option);
}

function telephonyReadinessLabel(health: TelephonyHealth, preflight?: TelephonyPreflight) {
  if (preflight?.readyForBulkTasks) return "可批量外呼";
  if (preflight?.readyForSingleNumberTest) return "可单号试拨";
  if (preflight?.readyForDeviceTest) return "设备可联调";
  if (health.readyForTestCall && health.liveCallEnabled) return "可单号试拨";
  if (health.readyForTestCall) return "线路已就绪";
  if (health.amiReachable && health.authenticated) return "AMI 已连接";
  return "待配置";
}

function telephonyReadinessDetail(config: TelephonyConfig, health: TelephonyHealth) {
  if (config.gatewayMode !== "asterisk") return "当前仍为模拟线路";
  if (!health.configured) return "请先配置 AMI 账号和密码";
  if (!health.amiReachable) return "后端还连不上 Asterisk AMI";
  if (!health.pingOk) return "AMI Ping 未通过";
  if (health.trunkReachable === false) return health.trunkStatus;
  if (!health.liveCallEnabled) return "单号试拨开关未开启";
  return health.trunkStatus || "UC100 线路待测试";
}

function telephonyPreflightStatusText(status: string) {
  if (status === "pass") return "PASS";
  if (status === "fail") return "FAIL";
  return "WARN";
}

function telephonyPreflightSummary(preflight: TelephonyPreflight) {
  if (preflight.readyForBulkTasks) return "真实批量外呼已开放";
  if (preflight.readyForSingleNumberTest) return "可做单号试拨";
  if (preflight.readyForDeviceTest) return "设备链路可联调";
  return "等待配置";
}

function formatDuration(seconds: number) {
  const minute = Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0");
  const second = Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0");
  return `${minute}:${second}`;
}

function App() {
  const [modules, setModules] = useState<ModuleSummary[]>(fallbackModules);
  const [leads, setLeads] = useState<Lead[]>(fallbackLeads);
  const [tasks, setTasks] = useState<OutreachTask[]>(fallbackTasks);
  const [overview, setOverview] = useState<OutboundOverview>(fallbackOverview);
  const [telephonyConfig, setTelephonyConfig] = useState<TelephonyConfig>(fallbackTelephonyConfig);
  const [telephonyHealth, setTelephonyHealth] = useState<TelephonyHealth>(fallbackTelephonyHealth);
  const [telephonyPreflight, setTelephonyPreflight] = useState<TelephonyPreflight>(fallbackTelephonyPreflight);
  const [callRecords, setCallRecords] = useState<CallRecord[]>(fallbackRecords);
  const [liveCalls, setLiveCalls] = useState<CallRecord[]>(fallbackRecords);
  const [scripts, setScripts] = useState<CallScript[]>(fallbackScripts);
  const [recallRules, setRecallRules] = useState<RecallRule[]>(fallbackRules);
  const [dmOverview, setDmOverview] = useState<DmOverview>(fallbackDmOverview);
  const [dmAccounts, setDmAccounts] = useState<DmAccount[]>(fallbackDmAccounts);
  const [dmTemplates, setDmTemplates] = useState<DmTemplate[]>(fallbackDmTemplates);
  const [dmConversations, setDmConversations] = useState<DmConversation[]>(fallbackDmConversations);
  const [dmMessages, setDmMessages] = useState<DmMessage[]>(fallbackDmMessages);
  const [dmPlatformConfigs, setDmPlatformConfigs] = useState<DmPlatformConfig[]>(fallbackDmPlatformConfigs);
  const [dmSyncResult, setDmSyncResult] = useState<DmSyncResult>(fallbackDmSyncResult);
  const [intentOverview, setIntentOverview] = useState<IntentOverview>(fallbackIntentOverview);
  const [intentCustomers, setIntentCustomers] = useState<IntentCustomer[]>(fallbackIntentCustomers);
  const [intentEvents, setIntentEvents] = useState<IntentEvent[]>(fallbackIntentEvents);
  const [followUpWorkOrders, setFollowUpWorkOrders] = useState<FollowUpWorkOrder[]>(fallbackWorkOrders);
  const [voiceOverview, setVoiceOverview] = useState<VoiceOverview>(fallbackVoiceOverview);
  const [voiceProviderStatus, setVoiceProviderStatus] = useState<VoiceProviderStatus>(fallbackVoiceProviderStatus);
  const [systemVoices, setSystemVoices] = useState<SystemVoice[]>(fallbackSystemVoices);
  const [voiceProfiles, setVoiceProfiles] = useState<VoiceProfile[]>(fallbackVoiceProfiles);
  const [voiceTrainingJobs, setVoiceTrainingJobs] = useState<VoiceTrainingJob[]>(fallbackVoiceTrainingJobs);
  const [voiceSamples, setVoiceSamples] = useState<VoiceSample[]>(fallbackVoiceSamples);
  const [voiceCloneRecords, setVoiceCloneRecords] = useState<VoiceCloneRecord[]>(fallbackVoiceCloneRecords);
  const [voiceUsageRecords, setVoiceUsageRecords] = useState<VoiceUsageRecord[]>(fallbackVoiceUsageRecords);
  const [isSystemVoiceLibraryOpen, setIsSystemVoiceLibraryOpen] = useState(false);
  const [systemVoiceSearch, setSystemVoiceSearch] = useState("");
  const [systemVoicePreviewState, setSystemVoicePreviewState] = useState<
    Record<string, { audioUrl?: string; loading?: boolean; error?: string; message?: string }>
  >({});
  const [reportOverview, setReportOverview] = useState<ReportOverview>(fallbackReportOverview);
  const [channelReports, setChannelReports] = useState<ChannelReport[]>(fallbackChannelReports);
  const [salesReports, setSalesReports] = useState<SalesPerformanceReport[]>(fallbackSalesReports);
  const [reportExports, setReportExports] = useState<ReportExport[]>(fallbackReportExports);
  const [settingsOverview, setSettingsOverview] = useState<SettingsOverview>(fallbackSettingsOverview);
  const [systemSettings, setSystemSettings] = useState<SystemSetting[]>(fallbackSystemSettings);
  const [activeModule, setActiveModule] = useState("outbound");
  const [apiStatus, setApiStatus] = useState("连接中");
  const [isLoading, setIsLoading] = useState(false);
  const [activeOutboundTab, setActiveOutboundTab] = useState<OutboundTab>("实时监听");
  const [activeDmTab, setActiveDmTab] = useState<DmTab>("回复监听");
  const [activeIntentTab, setActiveIntentTab] = useState<IntentTab>("客户池");
  const [activeVoiceTab, setActiveVoiceTab] = useState<VoiceTab>("声音档案");
  const [activeReportsTab, setActiveReportsTab] = useState<ReportsTab>("报表总览");
  const [activeSettingsTab, setActiveSettingsTab] = useState<SettingsTab>("设置总览");
  const [selectedIntentCustomerId, setSelectedIntentCustomerId] = useState<string>(fallbackIntentCustomers[0]?.id ?? "");
  const [selectedSystemVoiceId, setSelectedSystemVoiceId] = useState<string>(
    fallbackSystemVoices.find((voice) => voice.isDefault)?.id ?? fallbackSystemVoices[0]?.id ?? "",
  );
  const [selectedVoiceProfileId, setSelectedVoiceProfileId] = useState<string>(fallbackVoiceProfiles[0]?.id ?? "");
  const [selectedChannelReportId, setSelectedChannelReportId] = useState<string>(fallbackChannelReports[0]?.id ?? "");
  const [selectedSalesReportId, setSelectedSalesReportId] = useState<string>(fallbackSalesReports[0]?.id ?? "");
  const [selectedReportExportId, setSelectedReportExportId] = useState<string>(fallbackReportExports[0]?.id ?? "");
  const [selectedSystemSettingId, setSelectedSystemSettingId] = useState<string>(fallbackSystemSettings[0]?.id ?? "");
  const [settingDraft, setSettingDraft] = useState(fallbackSystemSettings[0]?.value ?? "");
  const [settingsMessage, setSettingsMessage] = useState("请选择左侧配置项，修改后点击保存设置。");
  const [isSavingSetting, setIsSavingSetting] = useState(false);
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>(fallbackLeads.map((lead) => lead.id));
  const [selectedDmLeadIds, setSelectedDmLeadIds] = useState<string[]>(fallbackLeads.map((lead) => lead.id));
  const [leadForm, setLeadForm] = useState({
    name: "",
    platform: "视频号",
    city: "",
    category: "",
    phone: "",
    contactName: "",
    platformUrl: "",
    source: "手动录入",
  });
  const [taskForm, setTaskForm] = useState({
    name: "",
    channel: "call" as OutreachTask["channel"],
    targetCount: 50,
    scheduledAt: "",
  });
  const [outboundForm, setOutboundForm] = useState({
    name: "南昌本地商家首轮外呼",
    concurrency: 10,
    scheduledAt: "",
  });
  const [telephonyTestForm, setTelephonyTestForm] = useState({
    phone: "",
    callerId: "",
  });
  const [telephonyTestResult, setTelephonyTestResult] = useState<TelephonyTestCallResult | null>(null);
  const [telephonyMessage, setTelephonyMessage] = useState("先检查线路，确认 UC100/Asterisk 可用后再做单号试拨。");
  const [isCheckingTelephony, setIsCheckingTelephony] = useState(false);
  const [isTestingTelephony, setIsTestingTelephony] = useState(false);
  const [dmForm, setDmForm] = useState({
    name: "美团高意向商家首轮私信",
    accountId: "",
    templateId: "",
    scheduledAt: "",
  });
  const [dmAccountForm, setDmAccountForm] = useState({
    platform: "美团",
    accountName: "",
    loginLabel: "待绑定个人号",
    status: "待登录",
    browserProfileKey: "",
    sessionStatus: "未登录",
    riskStatus: "正常",
    dailyLimit: 200,
    minSendIntervalSeconds: 45,
  });
  const [dmRuleDrafts, setDmRuleDrafts] = useState<Record<string, { dailyLimit: number; minSendIntervalSeconds: number }>>({});
  const [dmRotationMessage, setDmRotationMessage] = useState("");
  const [dmTemplateForm, setDmTemplateForm] = useState({
    name: "视频号团购邀约私信",
    platform: "通用",
    content: "您好，看到{商家名称}适合做视频号本地生活团购曝光，想了解下您是否考虑新增线上获客渠道？",
    isActive: true,
  });
  const [dmLoginSession, setDmLoginSession] = useState<DmLoginSession | null>(null);
  const [dmLoginMessage, setDmLoginMessage] = useState("");
  const [dmLoginEntryReady, setDmLoginEntryReady] = useState(false);
  const [isPreparingDmLogin, setIsPreparingDmLogin] = useState(false);
  const [isCheckingDmLogin, setIsCheckingDmLogin] = useState(false);
  const [checkingDmAccountId, setCheckingDmAccountId] = useState<string | null>(null);
  const [isDesktopClient, setIsDesktopClient] = useState(false);
  const [selectedDmLoginAccountId, setSelectedDmLoginAccountId] = useState<string | null>(null);
  const [editingDmPlatformConfigId, setEditingDmPlatformConfigId] = useState<string | null>(null);
  const [dmPlatformForm, setDmPlatformForm] = useState(defaultDmPlatformForm);
  const [voiceProfileForm, setVoiceProfileForm] = useState({
    name: "",
    ownerName: "",
    scenario: "外呼",
    authorizationStatus: "待提交",
    sampleCount: 0,
    fallbackVoice: "晨煦（Ethan）",
    consentMaterial: "",
    riskNote: "未授权前不可复刻、不可被任务选择。",
  });
  const [voiceSampleFile, setVoiceSampleFile] = useState<File | null>(null);
  const [voiceSampleMessage, setVoiceSampleMessage] = useState("");
  const [isUploadingVoiceSample, setIsUploadingVoiceSample] = useState(false);
  const [isCheckingVoiceProvider, setIsCheckingVoiceProvider] = useState(false);
  const [creatingVoiceCloneProfileId, setCreatingVoiceCloneProfileId] = useState<string | null>(null);
  const settingsEditorRef = useRef<HTMLElement | null>(null);
  const loginWorkbenchRef = useRef<HTMLElement | null>(null);
  const nativeLoginViewportRef = useRef<HTMLDivElement | null>(null);
  const nativeLoginWebviewRef = useRef<DmLoginWebviewElement | null>(null);

  const active = useMemo(
    () => modules.find((module) => module.key === activeModule) ?? modules[0],
    [activeModule, modules],
  );
  const outboundTasks = useMemo(() => tasks.filter((task) => task.channel === "call"), [tasks]);
  const dmTasks = useMemo(() => tasks.filter((task) => task.channel === "dm"), [tasks]);
  const callableLeads = useMemo(() => leads.filter((lead) => Boolean(lead.phone)), [leads]);
  const dmReachableLeads = useMemo(() => leads.filter((lead) => isSupportedDmPlatform(lead.platform)), [leads]);
  const dmUnsupportedLeads = useMemo(
    () => leads.filter((lead) => Boolean(lead.platform) && !isSupportedDmPlatform(lead.platform)),
    [leads],
  );
  const activeScript = scripts.find((script) => script.isActive) ?? scripts[0];
  const activeRule = recallRules[0];
  const activeDmTemplate = dmTemplates.find((template) => template.id === dmForm.templateId) ?? dmTemplates[0];
  const dmSupportedAccounts = useMemo(() => dmAccounts.filter(isSupportedDmAccount), [dmAccounts]);
  const dmLoggedInAccounts = useMemo(
    () =>
      dmSupportedAccounts.filter(
        (account) =>
          account.status === "可用" &&
          isDmLoginReadyStatus(account.sessionStatus) &&
          !["需验证", "风控暂停", "封禁", "异常"].includes(account.riskStatus ?? ""),
      ),
    [dmSupportedAccounts],
  );
  const dmLoggedInRemainingQuota = useMemo(
    () => dmLoggedInAccounts.reduce((sum, account) => sum + Math.max(0, account.dailyLimit - account.sentToday), 0),
    [dmLoggedInAccounts],
  );
  const dmAccountPlatforms = supportedDmPlatforms;
  const dmAccountCountByPlatform = useMemo(
    () =>
      dmSupportedAccounts.reduce<Record<string, number>>((counts, account) => {
        counts[account.platform] = (counts[account.platform] ?? 0) + 1;
        return counts;
      }, {}),
    [dmSupportedAccounts],
  );
  const isolatedDmAccountCount = useMemo(
    () => dmSupportedAccounts.filter((account) => Boolean(account.browserProfileKey || account.browserProfilePath)).length,
    [dmSupportedAccounts],
  );
  const activeLoginAccount = useMemo(() => {
    return (
      dmSupportedAccounts.find((account) => account.id === selectedDmLoginAccountId) ??
      dmSupportedAccounts.find((account) => account.id === dmLoginSession?.accountId) ??
      dmSupportedAccounts[0]
    );
  }, [dmSupportedAccounts, dmLoginSession, selectedDmLoginAccountId]);
  const activeLoginConfig = useMemo(() => {
    if (!activeLoginAccount) return null;
    return dmPlatformConfigs.find((config) => config.platform === activeLoginAccount.platform) ?? null;
  }, [activeLoginAccount, dmPlatformConfigs]);
  const activeLoginSession = dmLoginSession?.accountId === activeLoginAccount?.id ? dmLoginSession : null;
  const activeLoginUrl =
    personalLoginUrl(activeLoginAccount?.platform ?? "", activeLoginSession?.loginUrl) ||
    personalLoginUrl(activeLoginAccount?.platform ?? "", activeLoginConfig?.homeUrl) ||
    personalLoginUrl(activeLoginAccount?.platform ?? "", activeLoginAccount ? platformLoginUrls[activeLoginAccount.platform] : "") ||
    "";
  const activeLoginEntryText = activeLoginAccount
    ? activeLoginConfig
      ? platformLoginEntryLabel(activeLoginConfig)
      : activeLoginUrl
        ? "客户端内置个人号入口"
        : "客户端内置个人号入口"
    : "选择平台个人号";
  const dmLoginFeedbackTone = isCheckingDmLogin
    ? "is-loading"
    : dmLoginMessage.includes("检测通过") || dmLoginMessage.includes("已加入")
      ? "is-success"
      : dmLoginMessage.includes("失败") || dmLoginMessage.includes("未检测") || dmLoginMessage.includes("还未")
        ? "is-warning"
        : "";
  const dmRotationRows = useMemo(
    () =>
      dmAccountPlatforms.map((platformName) => {
        const accountsForPlatform = dmSupportedAccounts
          .filter((account) => account.platform === platformName)
          .sort((left, right) => {
            if (left.sentToday !== right.sentToday) return left.sentToday - right.sentToday;
            return new Date(left.lastSentAt ?? 0).getTime() - new Date(right.lastSentAt ?? 0).getTime();
          });
        const availableAccounts = accountsForPlatform.filter(
          (account) =>
            account.status === "可用" &&
            isDmLoginReadyStatus(account.sessionStatus) &&
            !["需验证", "风控暂停", "封禁", "异常"].includes(account.riskStatus ?? ""),
        );
        const totalRemaining = accountsForPlatform.reduce(
          (sum, account) => sum + Math.max(0, account.dailyLimit - account.sentToday),
          0,
        );
        return {
          platform: platformName,
          accounts: accountsForPlatform,
          availableAccounts,
          nextAccount: availableAccounts[0],
          totalRemaining,
        };
      }),
    [dmAccountPlatforms, dmSupportedAccounts],
  );
  const activeIntentCustomer =
    intentCustomers.find((customer) => customer.id === selectedIntentCustomerId) ?? intentCustomers[0];
  const activeIntentCustomerEvents = activeIntentCustomer
    ? intentEvents.filter((event) => event.customerId === activeIntentCustomer.id)
    : [];
  const defaultSystemVoice = systemVoices.find((voice) => voice.isDefault) ?? systemVoices[0];
  const activeSystemVoice = systemVoices.find((voice) => voice.id === selectedSystemVoiceId) ?? defaultSystemVoice;
  const filteredSystemVoices = useMemo(() => {
    const keyword = systemVoiceSearch.trim().toLowerCase();
    if (!keyword) return systemVoices;
    return systemVoices.filter((voice) =>
      [voice.name, voice.voiceParam, voice.gender, voice.style, voice.scenario, voice.sampleText]
        .join(" ")
        .toLowerCase()
        .includes(keyword),
    );
  }, [systemVoiceSearch, systemVoices]);
  const customerVoiceProfiles = useMemo(
    () => voiceProfiles.filter((profile) => profile.authorizationStatus !== "系统内置" && profile.ownerName !== "系统"),
    [voiceProfiles],
  );
  const customerVoiceProfileIds = useMemo(() => new Set(customerVoiceProfiles.map((profile) => profile.id)), [customerVoiceProfiles]);
  const customerVoiceTrainingJobs = useMemo(
    () => voiceTrainingJobs.filter((job) => customerVoiceProfileIds.has(job.profileId)),
    [customerVoiceProfileIds, voiceTrainingJobs],
  );
  const customerVoiceSamples = useMemo(
    () => voiceSamples.filter((sample) => customerVoiceProfileIds.has(sample.profileId)),
    [customerVoiceProfileIds, voiceSamples],
  );
  const customerVoiceCloneRecords = useMemo(
    () => voiceCloneRecords.filter((record) => customerVoiceProfileIds.has(record.profileId)),
    [customerVoiceProfileIds, voiceCloneRecords],
  );
  const availableCloneVoiceRecords = useMemo(
    () => customerVoiceCloneRecords.filter((record) => record.status === "可用" && record.externalVoiceId),
    [customerVoiceCloneRecords],
  );
  const filteredCloneVoiceRecords = useMemo(() => {
    const keyword = systemVoiceSearch.trim().toLowerCase();
    if (!keyword) return availableCloneVoiceRecords;
    return availableCloneVoiceRecords.filter((record) =>
      [record.clonedVoiceName, record.externalVoiceId, record.engine, record.status, record.result]
        .join(" ")
        .toLowerCase()
        .includes(keyword),
    );
  }, [availableCloneVoiceRecords, systemVoiceSearch]);
  const activeVoiceProfile = customerVoiceProfiles.find((profile) => profile.id === selectedVoiceProfileId) ?? customerVoiceProfiles[0];
  const activeVoiceProfileSamples = activeVoiceProfile
    ? customerVoiceSamples.filter((sample) => sample.profileId === activeVoiceProfile.id)
    : [];
  const activeChannelReport = channelReports.find((channel) => channel.id === selectedChannelReportId) ?? channelReports[0];
  const activeSalesReport = salesReports.find((report) => report.id === selectedSalesReportId) ?? salesReports[0];
  const activeReportExport = reportExports.find((exportJob) => exportJob.id === selectedReportExportId) ?? reportExports[0];
  const clientSettings = useMemo(() => systemSettings.filter(isClientVisibleSetting), [systemSettings]);
  const activeSystemSetting = clientSettings.find((setting) => setting.id === selectedSystemSettingId) ?? clientSettings[0];
  const settingGroups = useMemo(() => {
    return clientSettings.reduce<Record<string, SystemSetting[]>>((groups, setting) => {
      groups[setting.groupKey] = [...(groups[setting.groupKey] ?? []), setting];
      return groups;
    }, {});
  }, [clientSettings]);

  useEffect(() => {
    setIsDesktopClient(Boolean(window.aiAcqDesktop?.isDesktopClient));
  }, []);

  useEffect(() => {
    const viewport = nativeLoginViewportRef.current;
    nativeLoginWebviewRef.current = null;
    if (!viewport) return;

    viewport.replaceChildren();
    if (activeModule !== "dm" || !["私信总览", "账号管理"].includes(activeDmTab)) return;
    if (!isDesktopClient || !dmLoginEntryReady || !activeLoginSession || !activeLoginAccount || !activeLoginUrl) return;

    const webview = document.createElement("webview") as DmLoginWebviewElement;
    webview.className = "native-login-webview";
    webview.setAttribute("src", activeLoginUrl);
    webview.setAttribute("partition", `persist:dm-${activeLoginSession.profileKey || activeLoginSession.accountId}`);
    webview.setAttribute("data-account-id", activeLoginAccount.id);
    webview.setAttribute("data-platform", activeLoginAccount.platform);

    const handleStart = () => setDmLoginMessage("内置登录页正在加载，请在当前区域完成平台登录。");
    const handleStop = () => setDmLoginMessage("请在内置页面完成登录，完成后点击“登录后检测”。");
    const handleFail = (event: Event) => {
      const failure = event as Event & { errorCode?: number; errorDescription?: string };
      if (failure.errorCode === -3) return;
      setDmLoginMessage(failure.errorDescription || "内置登录页加载失败，请检查平台入口是否可访问。");
    };

    webview.addEventListener("did-start-loading", handleStart);
    webview.addEventListener("did-stop-loading", handleStop);
    webview.addEventListener("did-fail-load", handleFail);
    viewport.appendChild(webview);
    nativeLoginWebviewRef.current = webview;

    return () => {
      webview.removeEventListener("did-start-loading", handleStart);
      webview.removeEventListener("did-stop-loading", handleStop);
      webview.removeEventListener("did-fail-load", handleFail);
      webview.remove();
      if (nativeLoginWebviewRef.current === webview) nativeLoginWebviewRef.current = null;
    };
  }, [activeDmTab, activeLoginAccount, activeLoginUrl, activeLoginSession, activeModule, dmLoginEntryReady, isDesktopClient]);

  async function loadData() {
    setIsLoading(true);
    const results = await Promise.allSettled([
      api.health(),
      api.modules(),
      api.leads(),
      api.tasks(),
      api.outboundOverview(),
      api.callRecords(),
      api.liveCalls(),
      api.callScripts(),
      api.recallRules(),
      api.dmOverview(),
      api.dmAccounts(),
      api.dmTemplates(),
      api.dmConversations(),
      api.dmMessages(),
      api.dmPlatformConfigs(),
      api.intentOverview(),
      api.intentCustomers(),
      api.intentEvents(),
      api.followUpWorkOrders(),
      api.voiceOverview(),
      api.voiceProviderStatus(),
      api.systemVoices(),
      api.voiceProfiles(),
      api.voiceTrainingJobs(),
      api.voiceSamples(),
      api.voiceCloneRecords(),
      api.voiceUsageRecords(),
      api.reportsOverview(),
      api.reportChannels(),
      api.salesReports(),
      api.reportExports(),
      api.settingsOverview(),
      api.systemSettings(),
      api.telephonyConfig(),
      api.telephonyHealth(),
      api.telephonyPreflight(),
    ]);

    if (results[0].status === "fulfilled") {
      setApiStatus(results[0].value.status === "ok" ? "后端已连接" : results[0].value.status);
    } else {
      setApiStatus("使用前端示例数据");
    }
    if (results[1].status === "fulfilled") setModules(customerVisibleModules(results[1].value));
    const leadResult = results[2];
    if (leadResult.status === "fulfilled") {
      const nextLeads = leadResult.value;
      setLeads(nextLeads);
      setSelectedLeadIds((current) => current.filter((id) => nextLeads.some((lead) => lead.id === id)));
      setSelectedDmLeadIds((current) => current.filter((id) => nextLeads.some((lead) => lead.id === id && isSupportedDmPlatform(lead.platform))));
    }
    if (results[3].status === "fulfilled") setTasks(results[3].value);
    if (results[4].status === "fulfilled") setOverview(results[4].value);
    if (results[5].status === "fulfilled") setCallRecords(results[5].value);
    if (results[6].status === "fulfilled") setLiveCalls(results[6].value);
    if (results[7].status === "fulfilled") setScripts(results[7].value);
    if (results[8].status === "fulfilled") setRecallRules(results[8].value);
    if (results[9].status === "fulfilled") setDmOverview(results[9].value);
    const dmAccountsResult = results[10];
    if (dmAccountsResult.status === "fulfilled") {
      const nextAccounts = dmAccountsResult.value;
      setDmAccounts(nextAccounts);
      setDmForm((current) => ({
        ...current,
        accountId:
          current.accountId && nextAccounts.some((account) => account.id === current.accountId && isSupportedDmAccount(account))
            ? current.accountId
            : "",
      }));
    }
    const dmTemplatesResult = results[11];
    if (dmTemplatesResult.status === "fulfilled") {
      const nextTemplates = dmTemplatesResult.value;
      setDmTemplates(nextTemplates);
      setDmForm((current) => ({
        ...current,
        templateId: current.templateId || nextTemplates[0]?.id || "",
      }));
    }
    if (results[12].status === "fulfilled") setDmConversations(results[12].value);
    if (results[13].status === "fulfilled") setDmMessages(results[13].value);
    if (results[14].status === "fulfilled") setDmPlatformConfigs(results[14].value);
    if (results[15].status === "fulfilled") setIntentOverview(results[15].value);
    if (results[16].status === "fulfilled") {
      const nextCustomers = results[16].value;
      setIntentCustomers(nextCustomers);
      setSelectedIntentCustomerId((current) =>
        nextCustomers.some((customer) => customer.id === current) ? current : nextCustomers[0]?.id ?? "",
      );
    }
    if (results[17].status === "fulfilled") setIntentEvents(results[17].value);
    if (results[18].status === "fulfilled") setFollowUpWorkOrders(results[18].value);
    if (results[19].status === "fulfilled") setVoiceOverview(results[19].value);
    if (results[20].status === "fulfilled") setVoiceProviderStatus(results[20].value);
    if (results[21].status === "fulfilled") {
      const nextSystemVoices = results[21].value;
      setSystemVoices(nextSystemVoices);
      setSelectedSystemVoiceId((current) =>
        nextSystemVoices.some((voice) => voice.id === current)
          ? current
          : nextSystemVoices.find((voice) => voice.isDefault)?.id ?? nextSystemVoices[0]?.id ?? "",
      );
      const defaultVoiceName = nextSystemVoices.find((voice) => voice.isDefault)?.name ?? nextSystemVoices[0]?.name ?? "晨煦（Ethan）";
      setVoiceProfileForm((current) => ({ ...current, fallbackVoice: current.fallbackVoice || defaultVoiceName }));
    }
    if (results[22].status === "fulfilled") {
      const nextProfiles = results[22].value;
      const nextCustomerProfiles = nextProfiles.filter((profile) => profile.authorizationStatus !== "系统内置" && profile.ownerName !== "系统");
      setVoiceProfiles(nextProfiles);
      setSelectedVoiceProfileId((current) =>
        nextCustomerProfiles.some((profile) => profile.id === current) ? current : nextCustomerProfiles[0]?.id ?? "",
      );
    }
    if (results[23].status === "fulfilled") setVoiceTrainingJobs(results[23].value);
    if (results[24].status === "fulfilled") setVoiceSamples(results[24].value);
    if (results[25].status === "fulfilled") setVoiceCloneRecords(results[25].value);
    if (results[26].status === "fulfilled") setVoiceUsageRecords(results[26].value);
    if (results[27].status === "fulfilled") setReportOverview(results[27].value);
    if (results[28].status === "fulfilled") {
      const nextChannels = results[28].value;
      setChannelReports(nextChannels);
      setSelectedChannelReportId((current) =>
        nextChannels.some((channel) => channel.id === current) ? current : nextChannels[0]?.id ?? "",
      );
    }
    if (results[29].status === "fulfilled") {
      const nextSalesReports = results[29].value;
      setSalesReports(nextSalesReports);
      setSelectedSalesReportId((current) =>
        nextSalesReports.some((report) => report.id === current) ? current : nextSalesReports[0]?.id ?? "",
      );
    }
    if (results[30].status === "fulfilled") {
      const nextExports = results[30].value;
      setReportExports(nextExports);
      setSelectedReportExportId((current) => (nextExports.some((job) => job.id === current) ? current : nextExports[0]?.id ?? ""));
    }
    if (results[31].status === "fulfilled") setSettingsOverview(results[31].value);
    if (results[32].status === "fulfilled") {
      const nextSettings = results[32].value;
      setSystemSettings(nextSettings);
      setSelectedSystemSettingId((current) => {
        const nextId = nextSettings.some((setting) => setting.id === current) ? current : nextSettings[0]?.id ?? "";
        const nextSetting = nextSettings.find((setting) => setting.id === nextId);
        setSettingDraft(nextSetting?.value ?? "");
        return nextId;
      });
    }
    if (results[33].status === "fulfilled") setTelephonyConfig(results[33].value);
    if (results[34].status === "fulfilled") setTelephonyHealth(results[34].value);
    if (results[35].status === "fulfilled") {
      setTelephonyPreflight(results[35].value);
      setTelephonyHealth(results[35].value.health);
    }
    setIsLoading(false);
  }

  useEffect(() => {
    void loadData();
  }, []);

  async function submitLead(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!leadForm.name.trim() || !leadForm.city.trim() || !leadForm.category.trim()) return;

    const created = await api.createLead({
      ...leadForm,
      phone: leadForm.phone || null,
      contactName: leadForm.contactName || null,
      platformUrl: leadForm.platformUrl || null,
    });
    setLeads((current) => [created, ...current]);
    setSelectedLeadIds((current) => [created.id, ...current]);
    setSelectedDmLeadIds((current) => [created.id, ...current]);
    setLeadForm({
      name: "",
      platform: "视频号",
      city: "",
      category: "",
      phone: "",
      contactName: "",
      platformUrl: "",
      source: "手动录入",
    });
  }

  async function submitTask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!taskForm.name.trim()) return;

    const created = await api.createTask({
      ...taskForm,
      scheduledAt: taskForm.scheduledAt || null,
      targetCount: Number(taskForm.targetCount),
    });
    setTasks((current) => [created, ...current]);
    setTaskForm({ name: "", channel: "call", targetCount: 50, scheduledAt: "" });
  }

  async function submitOutboundTask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const leadIds = selectedLeadIds.length > 0 ? selectedLeadIds : callableLeads.slice(0, 20).map((lead) => lead.id);
    if (!outboundForm.name.trim() || leadIds.length === 0) return;

    const created = await api.createOutboundTask({
      name: outboundForm.name,
      leadIds,
      concurrency: Number(outboundForm.concurrency),
      scriptId: activeScript?.id ?? null,
      scheduledAt: outboundForm.scheduledAt || null,
    });
    setTasks((current) => [created, ...current.filter((task) => task.id !== created.id)]);
    setActiveModule("outbound");
    setActiveOutboundTab("任务列表");
  }

  async function startOutboundTask(taskId: string) {
    const updated = await api.startOutboundTask(taskId);
    setTasks((current) => current.map((task) => (task.id === updated.id ? updated : task)));
    const [overviewData, recordData, liveData, leadData] = await Promise.all([
      api.outboundOverview(),
      api.callRecords(),
      api.liveCalls(),
      api.leads(),
    ]);
    setOverview(overviewData);
    setCallRecords(recordData);
    setLiveCalls(liveData);
    setLeads(leadData);
    setActiveOutboundTab("实时监听");
  }

  async function refreshTelephonyStatus() {
    setIsCheckingTelephony(true);
    setTelephonyMessage("正在预检 UC100/Asterisk 线路...");
    try {
      const [config, preflight] = await Promise.all([api.telephonyConfig(), api.telephonyPreflight(telephonyTestForm.phone)]);
      setTelephonyConfig(config);
      setTelephonyHealth(preflight.health);
      setTelephonyPreflight(preflight);
      setTelephonyMessage(preflight.nextStep || telephonyReadinessDetail(config, preflight.health));
    } catch (error) {
      setTelephonyMessage(error instanceof Error ? error.message : "线路预检失败");
    } finally {
      setIsCheckingTelephony(false);
    }
  }

  async function submitTelephonyTestCall(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!telephonyTestForm.phone.trim()) return;
    setIsTestingTelephony(true);
    setTelephonyTestResult(null);
    setTelephonyMessage("正在提交单号试拨请求...");
    try {
      const result = await api.createTelephonyTestCall({
        phone: telephonyTestForm.phone.trim(),
        callerId: telephonyTestForm.callerId.trim() || null,
      });
      setTelephonyTestResult(result);
      setTelephonyMessage(result.accepted ? "已提交到 UC100/Asterisk，请观察被叫手机和线路事件。" : result.message);
      try {
        const preflight = await api.telephonyPreflight(telephonyTestForm.phone);
        setTelephonyHealth(preflight.health);
        setTelephonyPreflight(preflight);
      } catch {
        // 试拨结果已经返回，预检刷新失败不覆盖当前提示。
      }
    } catch (error) {
      setTelephonyMessage(error instanceof Error ? error.message : "测试拨号失败");
    } finally {
      setIsTestingTelephony(false);
    }
  }

  async function submitDmTask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const supportedLeadIds = new Set(dmReachableLeads.map((lead) => lead.id));
    const selectedSupportedLeadIds = selectedDmLeadIds.filter((leadId) => supportedLeadIds.has(leadId));
    const leadIds = selectedSupportedLeadIds.length > 0 ? selectedSupportedLeadIds : dmReachableLeads.slice(0, 20).map((lead) => lead.id);
    if (!dmForm.name.trim() || leadIds.length === 0) return;

    const created = await api.createDmTask({
      name: dmForm.name,
      leadIds,
      accountId: dmForm.accountId || null,
      templateId: activeDmTemplate?.id ?? null,
      scheduledAt: dmForm.scheduledAt || null,
    });
    setTasks((current) => [created, ...current.filter((task) => task.id !== created.id)]);
    setActiveModule("dm");
    setActiveDmTab("任务列表");
  }

  async function startDmTask(taskId: string) {
    const updated = await api.startDmTask(taskId);
    setTasks((current) => current.map((task) => (task.id === updated.id ? updated : task)));
    const [overviewData, conversationData, messageData, leadData, accountData] = await Promise.all([
      api.dmOverview(),
      api.dmConversations(),
      api.dmMessages(),
      api.leads(),
      api.dmAccounts(),
    ]);
    setDmOverview(overviewData);
    setDmConversations(conversationData);
    setDmMessages(messageData);
    setLeads(leadData);
    setDmAccounts(accountData);
    setActiveDmTab("回复监听");
  }

  async function submitDmAccount(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dmAccountForm.accountName.trim() || !isSupportedDmPlatform(dmAccountForm.platform)) return;

    const created = await api.createDmAccount({
      ...dmAccountForm,
      dailyLimit: Number(dmAccountForm.dailyLimit),
      minSendIntervalSeconds: Number(dmAccountForm.minSendIntervalSeconds),
    });
    setDmAccounts((current) => [created, ...current]);
    setDmForm((current) => ({ ...current, accountId: "" }));
    setDmAccountForm({
      platform: "美团",
      accountName: "",
      loginLabel: "待绑定个人号",
      status: "待登录",
      browserProfileKey: "",
      sessionStatus: "未登录",
      riskStatus: "正常",
      dailyLimit: 200,
      minSendIntervalSeconds: 45,
    });
  }

  function prepareNewDmAccount(platform: string, source?: DmAccount) {
    if (!isSupportedDmPlatform(platform)) return;

    const nextIndex = (dmAccountCountByPlatform[platform] ?? 0) + 1;
    setDmAccountForm({
      platform,
      accountName: source ? `${source.platform}个人号-${nextIndex}` : `${platform}个人号-${nextIndex}`,
      loginLabel: "待绑定个人号",
      status: "待登录",
      browserProfileKey: "",
      sessionStatus: "未登录",
      riskStatus: "正常",
      dailyLimit: source?.dailyLimit ?? 200,
      minSendIntervalSeconds: source?.minSendIntervalSeconds ?? 45,
    });
    window.setTimeout(() => {
      document.querySelector<HTMLInputElement>('[data-dm-account-name="true"]')?.focus();
    }, 80);
  }

  function dmRuleDraft(account: DmAccount) {
    return (
      dmRuleDrafts[account.id] ?? {
        dailyLimit: account.dailyLimit,
        minSendIntervalSeconds: account.minSendIntervalSeconds ?? 0,
      }
    );
  }

  function updateDmRuleDraft(account: DmAccount, patch: Partial<{ dailyLimit: number; minSendIntervalSeconds: number }>) {
    setDmRuleDrafts((current) => ({
      ...current,
      [account.id]: {
        ...dmRuleDraft(account),
        ...patch,
      },
    }));
  }

  async function saveDmAccountRule(account: DmAccount) {
    const draft = dmRuleDraft(account);
    const updated = await api.updateDmAccount(account.id, {
      dailyLimit: Math.max(1, Number(draft.dailyLimit) || account.dailyLimit),
      minSendIntervalSeconds: Math.max(0, Number(draft.minSendIntervalSeconds) || 0),
    });
    setDmAccounts((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    setDmRuleDrafts((current) => ({
      ...current,
      [updated.id]: {
        dailyLimit: updated.dailyLimit,
        minSendIntervalSeconds: updated.minSendIntervalSeconds ?? 0,
      },
    }));
    setDmRotationMessage(`${updated.accountName} 的轮换规则已保存。`);
  }

  async function submitDmTemplate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dmTemplateForm.name.trim() || !dmTemplateForm.content.trim()) return;

    const created = await api.createDmTemplate(dmTemplateForm);
    setDmTemplates((current) => [created, ...current]);
    setDmForm((current) => ({ ...current, templateId: created.id }));
  }

  function revealDmLoginWorkbench() {
    window.setTimeout(() => {
      loginWorkbenchRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);
  }

  function selectDmLoginAccount(accountId: string) {
    setSelectedDmLoginAccountId(accountId);
    if (dmLoginSession?.accountId !== accountId) {
      setDmLoginEntryReady(false);
      setDmLoginSession(null);
    }
    const account = dmAccounts.find((item) => item.id === accountId);
    setDmLoginMessage(
      account && isDmLoginReadyStatus(account.sessionStatus)
        ? "该个人号已经检测到真实平台登录态，可以继续检测或重新加载内置登录页。"
        : isDesktopClient
          ? "请选择下方“在内置页登录”，在当前区域完成登录后再点击“登录后检测”。"
          : "当前是网页预览，普通浏览器不能内嵌第三方平台登录页；请用桌面客户端打开后在此区域登录。",
    );
    revealDmLoginWorkbench();
  }

  async function openRealDmLogin(accountId: string) {
    setSelectedDmLoginAccountId(accountId);
    if (!isDesktopClient) {
      setDmLoginMessage("这里是网页预览，不能登录。请打开桌面客户端；登录入口会出现在同一个内置登录工作台区域。");
      revealDmLoginWorkbench();
      return;
    }
    setIsPreparingDmLogin(true);
    setDmLoginMessage("正在加载客户端内置登录页...");
    revealDmLoginWorkbench();
    try {
      const session = await api.createDmLoginSession(accountId);
      setDmLoginSession(session);
      setDmLoginEntryReady(true);
      setDmLoginMessage("已在客户端内置登录区加载平台页面，请在当前区域完成登录后点击“登录后检测”。");
      setDmAccounts((current) =>
        current.map((account) =>
          account.id === accountId
            ? {
                ...account,
                status: isDmLoginReadyStatus(session.sessionStatus) ? account.status : "待登录",
                sessionStatus: session.sessionStatus,
                riskStatus: session.riskStatus,
                browserProfileKey: session.profileKey,
                browserProfilePath: session.profilePath,
                lastError: isDmLoginReadyStatus(session.sessionStatus) ? account.lastError : "请在客户端内置登录区完成登录后点击检测",
              }
            : account,
        ),
      );
    } catch (error) {
      setDmLoginMessage(error instanceof Error ? error.message : "加载客户端内置登录页失败");
    } finally {
      setIsPreparingDmLogin(false);
    }
  }

  async function preflightDmAccount(accountId: string) {
    const account = dmAccounts.find((item) => item.id === accountId);
    setSelectedDmLoginAccountId(accountId);
    setIsCheckingDmLogin(true);
    setCheckingDmAccountId(accountId);
    setDmLoginMessage(`正在检测${account ? `「${account.accountName}」` : "当前个人号"}的真实登录态，请稍等...`);
    revealDmLoginWorkbench();
    try {
      let updated: DmAccount;
      const webview = nativeLoginWebviewRef.current;
      const webContentsId = webview?.getWebContentsId?.();
      if (isDesktopClient && account && activeLoginAccount?.id === accountId && webContentsId) {
        setDmLoginMessage("正在检测当前内置登录页的 Cookie、localStorage 和页面登录标识...");
        const evidence: DmDesktopLoginEvidence = await window.aiAcqDesktop!.inspectDmLogin({
          webContentsId,
          platform: account.platform,
        });
        updated = await api.completeDmDesktopLoginCheck(accountId, evidence);
      } else {
        updated = await api.preflightDmAccount(accountId);
      }
      setDmAccounts((current) => current.map((account) => (account.id === updated.id ? updated : account)));
      setDmLoginMessage(
        isDmLoginReadyStatus(updated.sessionStatus)
          ? `检测通过，${updated.accountName} 已加入已登录个人号列表，可用于同平台商家私信任务。`
          : updated.lastError || "还未检测到真实平台登录态，请先在客户端内置登录区完成登录。",
      );
    } catch (error) {
      setDmLoginMessage(error instanceof Error ? error.message : "登录检测失败");
    } finally {
      setIsCheckingDmLogin(false);
      setCheckingDmAccountId(null);
    }
  }

  async function syncDmReplies() {
    const result = await api.syncDmReplies();
    setDmSyncResult(result);
    const [overviewData, conversationData, messageData, leadData] = await Promise.all([
      api.dmOverview(),
      api.dmConversations(),
      api.dmMessages(),
      api.leads(),
    ]);
    setDmOverview(overviewData);
    setDmConversations(conversationData);
    setDmMessages(messageData);
    setLeads(leadData);
  }

  async function submitDmPlatformConfig(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = {
      ...dmPlatformForm,
      enabled: Boolean(dmPlatformForm.enabled),
    };
    const saved = editingDmPlatformConfigId
      ? await api.updateDmPlatformConfig(editingDmPlatformConfigId, payload)
      : await api.createDmPlatformConfig(payload);
    setDmPlatformConfigs((current) => {
      if (!editingDmPlatformConfigId) return [saved, ...current];
      return current.map((config) => (config.id === saved.id ? saved : config));
    });
    setEditingDmPlatformConfigId(null);
    setDmPlatformForm(defaultDmPlatformForm);
  }

  function editDmPlatformConfig(config: DmPlatformConfig) {
    setEditingDmPlatformConfigId(config.id);
    setDmPlatformForm({
      platform: config.platform,
      homeUrl: isLegacyBusinessBackendUrl(config.platform, config.homeUrl) ? "" : config.homeUrl,
      inboxUrl: config.inboxUrl,
      merchantSearchUrl: config.merchantSearchUrl,
      loginCheckSelector: config.loginCheckSelector,
      riskCheckSelector: config.riskCheckSelector,
      merchantLinkSelector: config.merchantLinkSelector,
      messageButtonSelector: config.messageButtonSelector,
      inputSelector: config.inputSelector,
      sendButtonSelector: config.sendButtonSelector,
      sentSuccessSelector: config.sentSuccessSelector,
      unreadSelector: config.unreadSelector,
      conversationItemSelector: config.conversationItemSelector,
      conversationTitleSelector: config.conversationTitleSelector,
      messageTextSelector: config.messageTextSelector,
      enabled: config.enabled,
    });
  }

  function selectSystemVoice(voice: SystemVoice) {
    setSelectedSystemVoiceId(voice.id);
    setVoiceProfileForm((current) => ({ ...current, fallbackVoice: voice.name }));
  }

  async function previewSystemVoice(voice: SystemVoice) {
    const existing = systemVoicePreviewState[voice.id];
    if (existing?.audioUrl) {
      const audio = new Audio(apiAssetUrl(existing.audioUrl));
      void audio.play().catch(() => undefined);
      return;
    }

    setSystemVoicePreviewState((current) => ({
      ...current,
      [voice.id]: { ...current[voice.id], loading: true, error: "", message: "" },
    }));
    try {
      const preview = await api.systemVoicePreview(voice.id);
      const audioUrl = apiAssetUrl(preview.audioUrl);
      setSystemVoicePreviewState((current) => ({
        ...current,
        [voice.id]: { audioUrl, loading: false, message: preview.message },
      }));
      const audio = new Audio(audioUrl);
      void audio.play().catch(() => undefined);
    } catch (error) {
      setSystemVoicePreviewState((current) => ({
        ...current,
        [voice.id]: {
          ...current[voice.id],
          loading: false,
          error: error instanceof Error ? error.message : "试听生成失败",
        },
      }));
    }
  }

  function previewCloneVoice(record: VoiceCloneRecord) {
    if (!record.previewAudioUrl) {
      setVoiceSampleMessage("这个复刻音色还没有试听音频。");
      return;
    }
    const audio = new Audio(apiAssetUrl(record.previewAudioUrl));
    void audio.play().catch(() => {
      setVoiceSampleMessage("试听播放失败，请刷新后重试。");
    });
  }

  function voiceLabelForUsage(profileId?: string | null) {
    const profile = voiceProfiles.find((item) => item.id === profileId);
    if (profile && profile.authorizationStatus !== "系统内置" && profile.ownerName !== "系统") return profile.name;
    return activeSystemVoice?.name ?? defaultSystemVoice?.name ?? "系统内置音色";
  }

  function voiceSamplesForProfile(profileId: string) {
    return customerVoiceSamples.filter((sample) => sample.profileId === profileId);
  }

  function usableVoiceSampleCount(profileId: string) {
    return voiceSamplesForProfile(profileId).filter((sample) => sample.qualityStatus === "可用").length;
  }

  function voiceTrainingBlockReason(profile: VoiceProfile) {
    if (profile.authorizationStatus !== "授权通过") return "需先通过授权审核";
    if (usableVoiceSampleCount(profile.id) <= 0) return "需先上传可用录音样本";
    if (!voiceOverview.cloneTrainingEnabled) return voiceOverview.cloneEngineMessage || "真实声音克隆服务未接入";
    if (voiceProviderStatus.configured && !voiceProviderStatus.ready) return voiceProviderStatus.message;
    return "";
  }

  function formatBytes(bytes: number) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 102.4) / 10} KB`;
    return `${Math.round(bytes / 1024 / 102.4) / 10} MB`;
  }

  async function readAudioDurationSeconds(file: File): Promise<number> {
    const AudioContextCtor =
      window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (AudioContextCtor) {
      try {
        const context = new AudioContextCtor();
        const buffer = await context.decodeAudioData(await file.arrayBuffer());
        await context.close();
        return Math.max(0, Math.round(buffer.duration));
      } catch {
        // Some browser/codec combinations cannot decode every upload format; fall back to metadata loading.
      }
    }

    return new Promise((resolve) => {
      const audio = document.createElement("audio");
      const objectUrl = URL.createObjectURL(file);
      const cleanup = () => {
        audio.removeAttribute("src");
        audio.load();
        URL.revokeObjectURL(objectUrl);
      };
      audio.preload = "metadata";
      audio.onloadedmetadata = () => {
        const duration = Number.isFinite(audio.duration) ? Math.max(0, Math.round(audio.duration)) : 0;
        cleanup();
        resolve(duration);
      };
      audio.onerror = () => {
        cleanup();
        resolve(0);
      };
      audio.src = objectUrl;
    });
  }

  async function checkVoiceProviderStatus() {
    setIsCheckingVoiceProvider(true);
    try {
      const status = await api.voiceProviderStatus(true);
      setVoiceProviderStatus(status);
      setVoiceSampleMessage(`${status.engineName}：${status.message}`);
    } catch (error) {
      setVoiceSampleMessage(error instanceof Error ? error.message : "检测真实复刻服务失败");
    } finally {
      setIsCheckingVoiceProvider(false);
    }
  }

  async function submitVoiceProfile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!voiceProfileForm.name.trim() || !voiceProfileForm.ownerName.trim()) {
      setVoiceSampleMessage("请填写档案名称和授权人。");
      return;
    }
    if (!voiceSampleFile) {
      setVoiceSampleMessage("请先上传客户或员工本人授权录音样本。");
      return;
    }

    setIsUploadingVoiceSample(true);
    try {
      const durationSeconds = await readAudioDurationSeconds(voiceSampleFile);
      const created = await api.createVoiceProfile({
        ...voiceProfileForm,
        status: "待授权",
        sampleCount: 0,
        fallbackVoice: voiceProfileForm.fallbackVoice || activeSystemVoice?.name || defaultSystemVoice?.name || "晨煦（Ethan）",
      });
      await api.uploadVoiceSample(created.id, voiceSampleFile, {
        uploadedBy: voiceProfileForm.ownerName,
        durationSeconds,
        transcript: voiceProfileForm.consentMaterial,
      });
      const [overviewData, profileData, sampleData] = await Promise.all([
        api.voiceOverview(),
        api.voiceProfiles(),
        api.voiceSamples(),
      ]);
      setVoiceProfiles(profileData);
      setVoiceSamples(sampleData);
      setVoiceOverview(overviewData);
      setSelectedVoiceProfileId(created.id);
      setActiveVoiceTab("授权审核");
      setVoiceSampleFile(null);
      setVoiceSampleMessage("克隆档案已创建，录音样本已上传，等待授权审核。");
      setVoiceProfileForm({
        name: "",
        ownerName: "",
        scenario: "外呼",
        authorizationStatus: "待提交",
        sampleCount: 0,
        fallbackVoice: activeSystemVoice?.name ?? defaultSystemVoice?.name ?? "晨煦（Ethan）",
        consentMaterial: "",
        riskNote: "未授权前不可复刻、不可被任务选择。",
      });
    } catch (error) {
      setVoiceSampleMessage(error instanceof Error ? error.message : "新增克隆档案失败");
    } finally {
      setIsUploadingVoiceSample(false);
    }
  }

  async function updateVoiceAuthorization(profile: VoiceProfile, authorizationStatus: string) {
    const updated = await api.updateVoiceProfile(profile.id, {
      authorizationStatus,
      status: authorizationStatus === "授权通过" ? "可复刻" : "已停用",
      riskNote: authorizationStatus === "授权通过" ? "授权已通过，可生成复刻音色。" : "授权已撤回，任务只能使用回退音色。",
    });
    setVoiceProfiles((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    const overviewData = await api.voiceOverview();
    setVoiceOverview(overviewData);
  }

  async function uploadSampleForActiveProfile() {
    if (!activeVoiceProfile) return;
    if (!voiceSampleFile) {
      setVoiceSampleMessage("请先选择录音文件。");
      return;
    }
    setIsUploadingVoiceSample(true);
    try {
      const durationSeconds = await readAudioDurationSeconds(voiceSampleFile);
      await api.uploadVoiceSample(activeVoiceProfile.id, voiceSampleFile, {
        uploadedBy: activeVoiceProfile.ownerName,
        durationSeconds,
      });
      const [overviewData, profileData, sampleData] = await Promise.all([
        api.voiceOverview(),
        api.voiceProfiles(),
        api.voiceSamples(),
      ]);
      setVoiceOverview(overviewData);
      setVoiceProfiles(profileData);
      setVoiceSamples(sampleData);
      setVoiceSampleFile(null);
      setVoiceSampleMessage("录音样本已上传，可继续授权审核或生成复刻音色。");
    } catch (error) {
      setVoiceSampleMessage(error instanceof Error ? error.message : "上传录音样本失败");
    } finally {
      setIsUploadingVoiceSample(false);
    }
  }

  async function createVoiceTrainingJob(profile: VoiceProfile) {
    const blockReason = voiceTrainingBlockReason(profile);
    if (blockReason) {
      setVoiceSampleMessage(blockReason);
      return;
    }
    setCreatingVoiceCloneProfileId(profile.id);
    setVoiceSampleMessage(`正在提交「${profile.name}」到 DashScope/CosyVoice 生成复刻音色，请稍等...`);
    try {
      const usableSamples = usableVoiceSampleCount(profile.id);
      const job = await api.createVoiceTrainingJob(profile.id, {
        engine: voiceOverview.cloneEngineName || "真实声音克隆服务",
        sampleMinutes: Math.max(usableSamples, 1),
        message: "提交 DashScope/CosyVoice 音色复刻生成。",
      });
      setVoiceTrainingJobs((current) => [job, ...current]);
      const [overviewData, profileData, cloneRecordData] = await Promise.all([
        api.voiceOverview(),
        api.voiceProfiles(),
        api.voiceCloneRecords(),
      ]);
      setVoiceOverview(overviewData);
      setVoiceProfiles(profileData);
      setVoiceCloneRecords(cloneRecordData);
      setVoiceSampleMessage("已生成复刻音色，并写入克隆语音记录。");
    } catch (error) {
      const [overviewResult, providerResult, profileResult, jobResult, cloneRecordResult] = await Promise.allSettled([
        api.voiceOverview(),
        api.voiceProviderStatus(true),
        api.voiceProfiles(),
        api.voiceTrainingJobs(),
        api.voiceCloneRecords(),
      ]);
      if (overviewResult.status === "fulfilled") setVoiceOverview(overviewResult.value);
      if (providerResult.status === "fulfilled") setVoiceProviderStatus(providerResult.value);
      if (profileResult.status === "fulfilled") setVoiceProfiles(profileResult.value);
      if (jobResult.status === "fulfilled") setVoiceTrainingJobs(jobResult.value);
      if (cloneRecordResult.status === "fulfilled") setVoiceCloneRecords(cloneRecordResult.value);
      setVoiceSampleMessage(error instanceof Error ? `复刻生成失败：${error.message}` : "复刻生成失败");
    } finally {
      setCreatingVoiceCloneProfileId(null);
    }
  }

  async function createReportExport(reportType?: string) {
    const nextType =
      reportType ||
      (activeReportsTab === "渠道分析" || activeReportsTab === "销售绩效" ? activeReportsTab : "经营总览");
    const created = await api.createReportExport({
      reportType: nextType,
      dateRange: "近30天",
      fileFormat: "xlsx",
      requester: "运营管理员",
      includeSensitiveFields: false,
    });
    setReportExports((current) => [created, ...current]);
    setSelectedReportExportId(created.id);
    setActiveReportsTab("导出中心");
    const overviewData = await api.reportsOverview();
    setReportOverview(overviewData);
  }

  function selectSystemSetting(setting: SystemSetting) {
    setSelectedSystemSettingId(setting.id);
    setSettingDraft(setting.value);
    setActiveSettingsTab(clientSettingGroupLabels[setting.groupKey] ?? "设置总览");
    setSettingsMessage(`已选中「${setting.label}」，右侧可以调整并保存。`);
    setTimeout(() => settingsEditorRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 0);
  }

  async function saveSelectedSetting(event?: React.FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!activeSystemSetting) {
      setSettingsMessage("请先选择一个配置项。");
      return;
    }
    setIsSavingSetting(true);
    try {
      const updated = await api.updateSystemSetting(activeSystemSetting.id, {
        value: settingDraft,
        actor: "运营管理员",
      });
      setSystemSettings((current) => current.map((setting) => (setting.id === updated.id ? updated : setting)));
      setSelectedSystemSettingId(updated.id);
      setSettingDraft(updated.value);
      const overviewData = await api.settingsOverview();
      setSettingsOverview(overviewData);
      setSettingsMessage(`已保存「${updated.label}」：${formatSettingValue(updated)}。`);
    } catch (error) {
      setSettingsMessage(error instanceof Error ? error.message : "保存设置失败，请稍后重试。");
    } finally {
      setIsSavingSetting(false);
    }
  }

  function toggleLead(leadId: string) {
    setSelectedLeadIds((current) =>
      current.includes(leadId) ? current.filter((id) => id !== leadId) : [...current, leadId],
    );
  }

  function toggleDmLead(leadId: string) {
    setSelectedDmLeadIds((current) =>
      current.includes(leadId) ? current.filter((id) => id !== leadId) : [...current, leadId],
    );
  }

  function renderReportsWorkspace() {
    const showOverview = activeReportsTab === "报表总览";
    const showChannels = activeReportsTab === "渠道分析";
    const showSales = activeReportsTab === "销售绩效";
    const showExports = activeReportsTab === "导出中心";

    return (
      <>
        <section className="outbound-tabs" aria-label="数据报表模块页面">
          {reportsTabs.map((tab) => (
            <button className={tab === activeReportsTab ? "is-active" : ""} key={tab} onClick={() => setActiveReportsTab(tab)} type="button">
              {tab}
            </button>
          ))}
        </section>

        <section className="metrics outbound-metrics">
          <MetricCard icon={<Database size={20} />} label="商家线索" value={reportOverview.totalLeads} detail="纳入经营报表" tone="blue" />
          <MetricCard icon={<Activity size={20} />} label="电话/私信触达" value={reportOverview.totalTouches} detail={`${reportOverview.connected} 个有效接通/回复`} tone="green" />
          <MetricCard icon={<Zap size={20} />} label="A/B 意向" value={reportOverview.highIntent} detail={`${reportOverview.conversionRate}% 线索转化`} tone="amber" />
          <MetricCard icon={<Upload size={20} />} label="导出任务" value={reportOverview.exportJobs} detail="导出中心可追踪" tone="rose" />
        </section>

        {showOverview && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Funnel</p>
                  <h2>获客转化漏斗</h2>
                </div>
                <BarChart3 size={22} />
              </div>
              <div className="funnel-list">
                {reportOverview.funnel.map((step) => (
                  <button className="funnel-step clickable-card" key={step.key} onClick={() => setActiveReportsTab("渠道分析")} type="button">
                    <span>{step.label}</span>
                    <strong>{step.value}</strong>
                    <small>{step.rate}%</small>
                  </button>
                ))}
              </div>
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Export</p>
                  <h2>经营快照</h2>
                </div>
                <Upload size={22} />
              </div>
              <div className="profile-grid">
                <div>
                  <span>待处理工单</span>
                  <strong>{reportOverview.pendingWorkOrders}</strong>
                </div>
                <div>
                  <span>更新时间</span>
                  <strong>{new Date(reportOverview.updatedAt).toLocaleString()}</strong>
                </div>
                <div className="wide">
                  <span>当前建议</span>
                  <strong>{reportOverview.pendingWorkOrders > 0 ? "优先处理 A/B 意向客户和人工接管任务。" : "当前漏斗稳定，可继续观察渠道效率。"}</strong>
                </div>
              </div>
              <div className="card-actions">
                <button className="primary-button" onClick={() => void createReportExport("经营总览")} type="button">
                  <Upload size={16} />
                  导出经营总览
                </button>
              </div>
            </article>
          </section>
        )}

        {(showOverview || showChannels) && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Channels</p>
                  <h2>渠道分析</h2>
                </div>
                <Database size={22} />
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>渠道</th>
                      <th>线索</th>
                      <th>触达</th>
                      <th>有效</th>
                      <th>意向</th>
                      <th>转化</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {channelReports.map((channel) => (
                      <tr
                        className={channel.id === activeChannelReport?.id ? "clickable-row is-selected" : "clickable-row"}
                        key={channel.id}
                        onClick={() => {
                          setSelectedChannelReportId(channel.id);
                          setActiveReportsTab("渠道分析");
                        }}
                      >
                        <td>
                          <strong>{channel.channel}</strong>
                          <small>{channel.insight}</small>
                        </td>
                        <td>{channel.leads}</td>
                        <td>{channel.touches}</td>
                        <td>{channel.connected}</td>
                        <td>{channel.intent}</td>
                        <td>{channel.conversionRate}%</td>
                        <td>{channel.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Insight</p>
                  <h2>渠道详情</h2>
                </div>
                <Activity size={22} />
              </div>
              {activeChannelReport && (
                <div className="profile-grid">
                  <div>
                    <span>渠道</span>
                    <strong>{activeChannelReport.channel}</strong>
                  </div>
                  <div>
                    <span>人工接管</span>
                    <strong>{activeChannelReport.handoff}</strong>
                  </div>
                  <div>
                    <span>意向转化</span>
                    <strong>{activeChannelReport.conversionRate}%</strong>
                  </div>
                  <div>
                    <span>状态</span>
                    <strong>{activeChannelReport.status}</strong>
                  </div>
                  <div className="wide">
                    <span>分析</span>
                    <strong>{activeChannelReport.insight}</strong>
                  </div>
                </div>
              )}
              <div className="card-actions">
                <button className="secondary-button" onClick={() => void createReportExport("渠道分析")} type="button">
                  <Upload size={16} />
                  导出渠道报表
                </button>
              </div>
            </article>
          </section>
        )}

        {showSales && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Sales</p>
                  <h2>销售绩效</h2>
                </div>
                <Users size={22} />
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>负责人</th>
                      <th>客户</th>
                      <th>待处理</th>
                      <th>已关闭</th>
                      <th>A/B意向</th>
                      <th>转化</th>
                      <th>最近活动</th>
                    </tr>
                  </thead>
                  <tbody>
                    {salesReports.map((report) => (
                      <tr
                        className={report.id === activeSalesReport?.id ? "clickable-row is-selected" : "clickable-row"}
                        key={report.id}
                        onClick={() => setSelectedSalesReportId(report.id)}
                      >
                        <td>
                          <strong>{report.ownerName}</strong>
                          <small>{report.handoff} 个需人工接管</small>
                        </td>
                        <td>{report.assignedCustomers}</td>
                        <td>{report.pendingWorkOrders}</td>
                        <td>{report.closedWorkOrders}</td>
                        <td>{report.highIntent}</td>
                        <td>{report.conversionRate}%</td>
                        <td>{report.lastActivityAt ? new Date(report.lastActivityAt).toLocaleString() : "暂无"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Owner</p>
                  <h2>绩效详情</h2>
                </div>
                <ClipboardList size={22} />
              </div>
              {activeSalesReport && (
                <div className="profile-grid">
                  <div>
                    <span>负责人</span>
                    <strong>{activeSalesReport.ownerName}</strong>
                  </div>
                  <div>
                    <span>客户数</span>
                    <strong>{activeSalesReport.assignedCustomers}</strong>
                  </div>
                  <div>
                    <span>待处理</span>
                    <strong>{activeSalesReport.pendingWorkOrders}</strong>
                  </div>
                  <div>
                    <span>转化率</span>
                    <strong>{activeSalesReport.conversionRate}%</strong>
                  </div>
                  <div className="wide">
                    <span>动作建议</span>
                    <strong>{activeSalesReport.pendingWorkOrders > 0 ? "先处理 SLA 内的 A/B 意向工单。" : "保持复盘，继续沉淀高转化话术。"}</strong>
                  </div>
                </div>
              )}
              <div className="card-actions">
                <button className="secondary-button" onClick={() => void createReportExport("销售绩效")} type="button">
                  <Upload size={16} />
                  导出销售报表
                </button>
              </div>
            </article>
          </section>
        )}

        {showExports && (
          <section className="content-grid lower">
            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Create</p>
                  <h2>创建导出</h2>
                </div>
                <Upload size={22} />
              </div>
              <div className="record-grid single">
                {["经营总览", "渠道分析", "销售绩效"].map((type) => (
                  <button className="record-card clickable-card" key={type} onClick={() => void createReportExport(type)} type="button">
                    <div>
                      <strong>{type}</strong>
                      <span>xlsx</span>
                    </div>
                    <p>近30天数据，不包含敏感字段。</p>
                    <small>点击创建导出任务</small>
                  </button>
                ))}
              </div>
            </article>

            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Exports</p>
                  <h2>导出中心</h2>
                </div>
                <ExternalLink size={22} />
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>报表</th>
                      <th>范围</th>
                      <th>格式</th>
                      <th>行数</th>
                      <th>状态</th>
                      <th>申请人</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reportExports.map((job) => (
                      <tr
                        className={job.id === activeReportExport?.id ? "clickable-row is-selected" : "clickable-row"}
                        key={job.id}
                        onClick={() => setSelectedReportExportId(job.id)}
                      >
                        <td>
                          <strong>{job.reportType}</strong>
                          <small>{new Date(job.createdAt).toLocaleString()}</small>
                        </td>
                        <td>{job.dateRange}</td>
                        <td>{job.fileFormat}</td>
                        <td>{job.rowCount}</td>
                        <td>{job.status}</td>
                        <td>{job.requester}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {activeReportExport && (
                <p className="panel-note">
                  当前选中：{activeReportExport.reportType} · {activeReportExport.status} · {activeReportExport.rowCount} 行
                </p>
              )}
            </article>
          </section>
        )}
      </>
    );
  }

  function renderSettingControl(setting: SystemSetting) {
    const updateSettingDraft = (value: string) => {
      setSettingDraft(value);
      setSettingsMessage(`已修改为「${formatSettingValue(setting, value)}」，点击保存设置后生效。`);
    };

    if (setting.valueType === "boolean") {
      return (
        <select value={settingDraft} onChange={(event) => updateSettingDraft(event.target.value)}>
          <option value="true">开启</option>
          <option value="false">关闭</option>
        </select>
      );
    }
    if (setting.valueType.startsWith("select:")) {
      return (
        <select value={settingDraft} onChange={(event) => updateSettingDraft(event.target.value)}>
          {setting.valueType
            .replace("select:", "")
            .split(",")
            .map((option) => (
              <option value={option} key={option}>
                {formatSettingOption(setting, option)}
              </option>
            ))}
        </select>
      );
    }
    if (setting.valueType === "number") {
      return <input type="number" value={settingDraft} onChange={(event) => updateSettingDraft(event.target.value)} />;
    }
    return <textarea value={settingDraft} onChange={(event) => updateSettingDraft(event.target.value)} rows={4} />;
  }

  function renderSettingsWorkspace() {
    const tabToGroup: Record<SettingsTab, string | null> = {
      设置总览: null,
      电话线路: "telephony",
      平台账号: "dm",
      合规保护: "compliance",
    };
    const activeGroup = tabToGroup[activeSettingsTab];
    const visibleSettings = activeGroup ? settingGroups[activeGroup] ?? [] : clientSettings;
    const groupDescriptions: Record<string, string> = {
      telephony: "外呼线路、队列和主备切换",
      dm: "平台个人号发送模式和安全开关",
      compliance: "勿扰、拒绝即停和触达保护",
    };
    const clientSettingGroups = Object.entries(clientSettingGroupLabels).map(([groupKey, label]) => {
      const items = settingGroups[groupKey] ?? [];
      const enabled = items.filter(isClientEnabledSetting).length;
      return {
        groupKey,
        label,
        total: items.length,
        enabled,
        warning: Math.max(items.length - enabled, 0),
      };
    });
    const enabledSettings = clientSettings.filter(isClientEnabledSetting).length;
    const warningSettings = Math.max(clientSettings.length - enabledSettings, 0);

    return (
      <>
        <section className="outbound-tabs" aria-label="系统设置模块页面">
          {settingsTabs.map((tab) => (
            <button
              className={tab === activeSettingsTab ? "is-active" : ""}
              key={tab}
              onClick={() => {
                setActiveSettingsTab(tab);
                setSettingsMessage(tab === "设置总览" ? "已切换到设置总览，请选择要调整的业务配置。" : `已切换到「${tab}」，请选择下方配置项。`);
              }}
              type="button"
            >
              {tab}
            </button>
          ))}
        </section>

        <section className="metrics outbound-metrics">
          <MetricCard icon={<Settings size={20} />} label="运营配置" value={clientSettings.length} detail={`${enabledSettings} 个已启用/受控`} tone="blue" />
          <MetricCard icon={<ShieldAlert size={20} />} label="需确认" value={warningSettings} detail="待配置或未启用" tone="amber" />
          <MetricCard icon={<PhoneCall size={20} />} label="电话线路" value={settingGroups.telephony?.length ?? 0} detail="外呼线路和队列" tone="green" />
          <MetricCard icon={<MessageSquareText size={20} />} label="平台账号" value={settingGroups.dm?.length ?? 0} detail="个人号和发送保护" tone="rose" />
        </section>

        {activeSettingsTab === "设置总览" && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Groups</p>
                  <h2>设置总览</h2>
                </div>
                <Settings size={22} />
              </div>
              <div className="record-grid">
                {clientSettingGroups.map((group) => (
                  <button
                    className="record-card clickable-card"
                    key={group.groupKey}
                    onClick={() => {
                      const firstSetting = settingGroups[group.groupKey]?.[0];
                      setActiveSettingsTab(clientSettingGroupLabels[group.groupKey] ?? "设置总览");
                      if (firstSetting) selectSystemSetting(firstSetting);
                      setSettingsMessage(`已进入「${group.label}」，右侧已选中第一个可调整配置。`);
                    }}
                    type="button"
                  >
                    <div>
                      <strong>{group.label}</strong>
                      <span>{group.enabled}/{group.total}</span>
                    </div>
                    <p>{groupDescriptions[group.groupKey]}</p>
                    <small>{group.warning > 0 ? `${group.warning} 个配置需要确认` : "配置状态正常"}</small>
                  </button>
                ))}
              </div>
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Guardrails</p>
                  <h2>关键保护</h2>
                </div>
                <ShieldAlert size={22} />
              </div>
              <div className="profile-grid">
                <div>
                  <span>真实私信发送</span>
                  <strong>{clientSettings.find((setting) => setting.itemKey === "live_send_enabled")?.value === "true" ? "已开启" : "受控关闭"}</strong>
                </div>
                <div>
                  <span>勿扰保护</span>
                  <strong>{clientSettings.find((setting) => setting.itemKey === "dnc_enabled")?.value === "true" ? "已启用" : "未启用"}</strong>
                </div>
                <div className="wide">
                  <span>模型和权限</span>
                  <strong>后台维护</strong>
                </div>
              </div>
            </article>
          </section>
        )}

        <section className="content-grid lower">
          <article className="panel span-2">
            <div className="panel-title">
              <div>
                <p>Operations</p>
                <h2>{activeSettingsTab === "设置总览" ? "运营配置项" : activeSettingsTab}</h2>
              </div>
              <Code2 size={22} />
            </div>
            <div className="setting-list">
              {visibleSettings.map((setting) => (
                <button
                  className={setting.id === activeSystemSetting?.id ? "account-row clickable-card is-selected" : "account-row clickable-card"}
                  key={setting.id}
                  onClick={() => selectSystemSetting(setting)}
                  type="button"
                >
                  <div>
                    <strong>{setting.label}</strong>
                    <span>{setting.status}</span>
                  </div>
                  <p>{setting.description}</p>
                  <small>{clientSettingGroupLabels[setting.groupKey]} · 当前 {formatSettingValue(setting)}</small>
                </button>
              ))}
            </div>
          </article>

          <article className="panel" ref={settingsEditorRef}>
            <div className="panel-title">
              <div>
                <p>Change</p>
                <h2>调整运营设置</h2>
              </div>
              <CheckCircle2 size={22} />
            </div>
            {activeSystemSetting ? (
              <form className="form-grid single" onSubmit={(event) => void saveSelectedSetting(event)}>
                <label>
                  配置项
                  <input value={activeSystemSetting.label} readOnly />
                </label>
                <label>
                  当前值
                  <input value={formatSettingValue(activeSystemSetting)} readOnly />
                </label>
                <label>
                  调整为
                  {renderSettingControl(activeSystemSetting)}
                </label>
                <label>
                  状态
                  <input value={activeSystemSetting.status} readOnly />
                </label>
                <label>
                  更新人
                  <input value={activeSystemSetting.updatedBy} readOnly />
                </label>
                <div className="form-result">{settingsMessage}</div>
                <button className="primary-button" disabled={isSavingSetting} type="submit">
                  <CheckCircle2 size={16} />
                  {isSavingSetting ? "保存中..." : "保存设置"}
                </button>
              </form>
            ) : (
              <>
                <p className="empty-state">请选择一个配置项。</p>
                <div className="form-result">{settingsMessage}</div>
              </>
            )}
          </article>
        </section>

      </>
    );
  }

  function renderIntentWorkspace() {
    const showPool = activeIntentTab === "客户池";
    const showWorkOrders = activeIntentTab === "跟进工单";
    const showDetails = activeIntentTab === "客户详情";
    const showRules = activeIntentTab === "分配规则";

    return (
      <>
        <section className="outbound-tabs" aria-label="意向客户模块页面">
          {intentTabs.map((tab) => (
            <button className={tab === activeIntentTab ? "is-active" : ""} key={tab} onClick={() => setActiveIntentTab(tab)} type="button">
              {tab}
            </button>
          ))}
        </section>

        <section className="metrics outbound-metrics">
          <MetricCard icon={<Users size={20} />} label="意向客户" value={intentOverview.totalCustomers} detail="统一客户池" tone="blue" />
          <MetricCard icon={<Zap size={20} />} label="A/B 意向" value={intentOverview.highIntent} detail="优先跟进" tone="green" />
          <MetricCard icon={<Headphones size={20} />} label="需接管" value={intentOverview.needsHandoff} detail="外呼或私信触发" tone="amber" />
          <MetricCard icon={<ShieldAlert size={20} />} label="勿扰保护" value={intentOverview.dncBlocked} detail="阻断触达" tone="rose" />
        </section>

        {showPool && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Customer Pool</p>
                  <h2>电话和私信统一意向客户池</h2>
                </div>
                <Users size={22} />
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>商家</th>
                      <th>来源</th>
                      <th>意向</th>
                      <th>负责人</th>
                      <th>跟进</th>
                      <th>最近信号</th>
                    </tr>
                  </thead>
                  <tbody>
                    {intentCustomers.length === 0 && (
                      <tr>
                        <td colSpan={6}>
                          <span className="empty-state">暂无意向客户，模拟外呼或私信后会自动沉淀。</span>
                        </td>
                      </tr>
                    )}
                    {intentCustomers.map((customer) => (
                      <tr
                        className={customer.id === activeIntentCustomer?.id ? "clickable-row is-selected" : "clickable-row"}
                        key={customer.id}
                        onClick={() => {
                          setSelectedIntentCustomerId(customer.id);
                          setActiveIntentTab("客户详情");
                        }}
                      >
                        <td>
                          <strong>{customer.merchantName}</strong>
                          <small>
                            {customer.city || "未知城市"} · {customer.category || "未知品类"}
                          </small>
                        </td>
                        <td>{customer.sourceChannels}</td>
                        <td>
                          <span className={`intent-pill intent-${customer.intentLevel.toLowerCase()}`}>
                            {customer.intentLevel} · {customer.intentScore}
                          </span>
                        </td>
                        <td>{customer.ownerName}</td>
                        <td>{customer.dncStatus ? "勿扰" : customer.followStatus}</td>
                        <td>{customer.latestSignal}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          </section>
        )}

        {showWorkOrders && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Work Orders</p>
                  <h2>销售跟进工单</h2>
                </div>
                <ClipboardList size={22} />
              </div>
              <div className="record-grid">
                {followUpWorkOrders.length === 0 && <div className="empty-state">暂无跟进工单。</div>}
                {followUpWorkOrders.map((order) => {
                  const customer = intentCustomers.find((item) => item.id === order.customerId);
                  return (
                    <article
                      className="record-card clickable-card"
                      key={order.id}
                      onClick={() => {
                        if (customer) setSelectedIntentCustomerId(customer.id);
                        setActiveIntentTab("客户详情");
                      }}
                    >
                      <div>
                        <strong>{order.title}</strong>
                        <span>{order.priority}</span>
                      </div>
                      <p>{order.lastNote || customer?.latestSignal || "等待销售接手"}</p>
                      <small>
                        {order.ownerName} · {order.status} · SLA {order.slaDueAt ? new Date(order.slaDueAt).toLocaleString() : "未设置"}
                      </small>
                    </article>
                  );
                })}
              </div>
            </article>
          </section>
        )}

        {showDetails && (
          <section className="content-grid lower">
            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Customer Detail</p>
                  <h2>{activeIntentCustomer?.merchantName ?? "客户详情"}</h2>
                </div>
                <button className="secondary-button" onClick={() => setActiveIntentTab("客户池")} type="button">
                  <Users size={16} />
                  返回客户池
                </button>
              </div>
              {activeIntentCustomer ? (
                <div className="profile-grid">
                  <div>
                    <span>平台</span>
                    <strong>{activeIntentCustomer.platform}</strong>
                  </div>
                  <div>
                    <span>联系人</span>
                    <strong>{activeIntentCustomer.contactName ?? "未填写"}</strong>
                  </div>
                  <div>
                    <span>电话</span>
                    <strong>{activeIntentCustomer.phone ?? "未填写"}</strong>
                  </div>
                  <div>
                    <span>状态</span>
                    <strong>{activeIntentCustomer.followStatus}</strong>
                  </div>
                  <div className="wide">
                    <span>AI 判断依据</span>
                    <strong>{activeIntentCustomer.evidenceSummary || activeIntentCustomer.latestSignal}</strong>
                  </div>
                </div>
              ) : (
                <div className="empty-state">暂无客户详情。</div>
              )}
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Evidence</p>
                  <h2>来源证据</h2>
                </div>
                <Database size={22} />
              </div>
              <div className="timeline-list">
                {activeIntentCustomerEvents.length === 0 && <div className="empty-state">暂无来源事件。</div>}
                {activeIntentCustomerEvents.map((event) => (
                  <article className="timeline-item" key={event.id}>
                    <span>{event.channel}</span>
                    <strong>
                      {event.intentLevel} · {event.summary}
                    </strong>
                    <p>{event.evidenceText}</p>
                    <small>{new Date(event.createdAt).toLocaleString()}</small>
                  </article>
                ))}
              </div>
            </article>
          </section>
        )}

        {showRules && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Assignment</p>
                  <h2>分配规则和保护边界</h2>
                </div>
                <ShieldAlert size={22} />
              </div>
              <div className="rule-detail-grid">
                <div>
                  <strong>A级客户</strong>
                  <span>4 小时内分配销售，电话和私信证据合并，不重复派单。</span>
                </div>
                <div>
                  <strong>B级客户</strong>
                  <span>24 小时内跟进，优先发送资料和案例，再安排人工沟通。</span>
                </div>
                <div>
                  <strong>人工接管</strong>
                  <span>客户追问价格、合作细节或要求资料时自动生成工单。</span>
                </div>
                <div>
                  <strong>勿扰保护</strong>
                  <span>拒绝、投诉、无效号码或撤回授权后阻断后续触达。</span>
                </div>
              </div>
            </article>
          </section>
        )}
      </>
    );
  }

  function renderVoiceWorkspace() {
    const showProfiles = activeVoiceTab === "声音档案";
    const showAuth = activeVoiceTab === "授权审核";
    const showTraining = activeVoiceTab === "音色复刻";
    const showUsage = activeVoiceTab === "使用记录";

    return (
      <>
        <section className="outbound-tabs" aria-label="声音档案模块页面">
          {voiceTabs.map((tab) => (
            <button
              className={tab === activeVoiceTab ? "is-active" : ""}
              key={tab}
              onClick={() => {
                setActiveVoiceTab(tab);
                if (tab !== "声音档案") setIsSystemVoiceLibraryOpen(false);
              }}
              type="button"
            >
              {tab}
            </button>
          ))}
        </section>

        <section className="metrics outbound-metrics">
          <MetricCard icon={<Headphones size={20} />} label="克隆档案" value={voiceOverview.profiles} detail="客户/员工授权" tone="blue" />
          <MetricCard icon={<Radio size={20} />} label="系统音色" value={systemVoices.length || voiceOverview.systemVoices} detail={activeSystemVoice?.name ?? voiceOverview.defaultVoice} tone="green" />
          <MetricCard icon={<ShieldAlert size={20} />} label="克隆服务" value={voiceProviderStatus.status || voiceOverview.cloneEngineStatus} detail={voiceProviderStatus.engineName || voiceOverview.cloneEngineName || "未配置真实引擎"} tone="amber" />
          <MetricCard icon={<Activity size={20} />} label="使用记录" value={voiceOverview.usageRecords} detail="审计留痕" tone="rose" />
        </section>

        {showProfiles && isSystemVoiceLibraryOpen && (
          <section className="content-grid lower">
            <article className="panel span-2 voice-library-panel">
              <div className="panel-title voice-library-header">
                <div>
                  <p>Voice Library</p>
                  <h2>声音库</h2>
                </div>
                <div className="button-row">
                  <button className="row-action" onClick={() => setIsSystemVoiceLibraryOpen(false)} type="button">
                    返回
                  </button>
                  <button className="row-action is-primary" onClick={() => activeSystemVoice && void previewSystemVoice(activeSystemVoice)} type="button">
                    试听当前默认
                  </button>
                </div>
              </div>
              <div className="voice-library-toolbar">
                <label className="search-box voice-search-box">
                  <Search size={18} />
                  <input
                    onChange={(event) => setSystemVoiceSearch(event.target.value)}
                    placeholder="搜索复刻音色、系统音色、voice 参数或场景"
                    value={systemVoiceSearch}
                  />
                </label>
                <div className="voice-library-stats">
                  <strong>{filteredCloneVoiceRecords.length + filteredSystemVoices.length}</strong>
                  <span>/ {availableCloneVoiceRecords.length + systemVoices.length} 个可选音色</span>
                </div>
              </div>
              <section className="voice-library-section">
                <div className="voice-library-section-head">
                  <div>
                    <p>Cloned Voices</p>
                    <h3>已复刻音色</h3>
                  </div>
                  <span>{filteredCloneVoiceRecords.length} 个可用</span>
                </div>
                {availableCloneVoiceRecords.length === 0 ? (
                  <div className="empty-state compact">暂无可用复刻音色。生成复刻成功后会出现在这里。</div>
                ) : filteredCloneVoiceRecords.length === 0 ? (
                  <div className="empty-state compact">没有匹配的复刻音色。</div>
                ) : (
                  <div className="voice-library-grid cloned-voice-grid">
                    {filteredCloneVoiceRecords.map((record) => (
                      <article className="voice-option-card clone-voice-card" key={record.id}>
                        <div className="voice-option-top">
                          <div>
                            <strong>{record.clonedVoiceName}</strong>
                            <small>{record.engine}</small>
                          </div>
                          <span>{record.status}</span>
                        </div>
                        <p>
                          <span>voice_id</span>
                          <strong>{record.externalVoiceId}</strong>
                        </p>
                        <div className="voice-tags">
                          <span>{record.sampleCount} 条样本</span>
                          <span>{record.sampleMinutes} 分钟</span>
                          <span>客户/员工授权</span>
                        </div>
                        <div className="voice-preview-actions">
                          <button
                            className="row-action"
                            disabled={!record.previewAudioUrl}
                            onClick={() => previewCloneVoice(record)}
                            type="button"
                          >
                            试听
                          </button>
                          <span className="voice-id-chip">复刻音色</span>
                        </div>
                        {record.previewAudioUrl ? (
                          <audio controls preload="none" src={apiAssetUrl(record.previewAudioUrl)} />
                        ) : (
                          <div className="voice-preview-message is-error">暂无试听音频</div>
                        )}
                      </article>
                    ))}
                  </div>
                )}
              </section>
              <section className="voice-library-section">
                <div className="voice-library-section-head">
                  <div>
                    <p>Built-in Voices</p>
                    <h3>系统内置音色</h3>
                  </div>
                  <span>{filteredSystemVoices.length} 个可选</span>
                </div>
              <div className="voice-library-grid">
                {filteredSystemVoices.map((voice) => {
                  const preview = systemVoicePreviewState[voice.id] ?? {};
                  return (
                    <article
                      className={voice.id === activeSystemVoice?.id ? "voice-option-card is-selected" : "voice-option-card"}
                      key={voice.id}
                      onClick={() => selectSystemVoice(voice)}
                    >
                      <div className="voice-option-top">
                        <div>
                          <strong>{voice.name}</strong>
                          <small>{voice.provider} · {voice.voiceParam}</small>
                        </div>
                        <span>{voice.id === activeSystemVoice?.id ? "默认" : voice.status}</span>
                      </div>
                      <p>{voice.sampleText}</p>
                      <div className="voice-tags">
                        {[voice.gender, voice.style, voice.scenario].map((item) => (
                          <span key={item}>{item}</span>
                        ))}
                      </div>
                      <div className="voice-preview-actions">
                        <button
                          className="row-action"
                          disabled={Boolean(preview.loading)}
                          onClick={(event) => {
                            event.stopPropagation();
                            void previewSystemVoice(voice);
                          }}
                          type="button"
                        >
                          {preview.loading ? "生成中" : preview.audioUrl ? "重新试听" : "试听"}
                        </button>
                        <button
                          className={voice.id === activeSystemVoice?.id ? "row-action is-primary" : "row-action"}
                          onClick={(event) => {
                            event.stopPropagation();
                            selectSystemVoice(voice);
                          }}
                          type="button"
                        >
                          {voice.id === activeSystemVoice?.id ? "当前默认" : "设为默认"}
                        </button>
                      </div>
                      {preview.audioUrl && <audio controls src={preview.audioUrl} />}
                      {preview.error && <div className="voice-preview-message is-error">{preview.error}</div>}
                      {!preview.error && preview.message && <div className="voice-preview-message">{preview.message}</div>}
                    </article>
                  );
                })}
              </div>
              </section>
            </article>
          </section>
        )}

        {showProfiles && !isSystemVoiceLibraryOpen && (
          <section className="content-grid lower">
            <article className="panel span-2 voice-default-panel">
              <div className="panel-title">
                <div>
                  <p>Default Voice</p>
                  <h2>当前系统默认音色</h2>
                </div>
                <Radio size={22} />
              </div>
              <div className="voice-default-summary">
                <div className="voice-default-icon">
                  <Radio size={24} />
                </div>
                <div className="voice-default-copy">
                  <strong>{activeSystemVoice?.name ?? voiceOverview.defaultVoice}</strong>
                  <p>{activeSystemVoice?.sampleText ?? "用于系统内置 TTS 回退和默认外呼试听。"}</p>
                  <small>
                    {activeSystemVoice
                      ? `${activeSystemVoice.provider} · ${activeSystemVoice.voiceParam} · ${activeSystemVoice.gender} · ${activeSystemVoice.style} · ${activeSystemVoice.scenario}`
                      : `${systemVoices.length || voiceOverview.systemVoices} 个系统音色可用`}
                  </small>
                </div>
                <div className="voice-default-actions">
                  <button className="row-action" onClick={() => activeSystemVoice && void previewSystemVoice(activeSystemVoice)} type="button">
                    试听
                  </button>
                  <button className="row-action is-primary" onClick={() => setIsSystemVoiceLibraryOpen(true)} type="button">
                    进入音色库
                  </button>
                </div>
              </div>
              {activeSystemVoice && systemVoicePreviewState[activeSystemVoice.id]?.audioUrl && (
                <audio controls src={systemVoicePreviewState[activeSystemVoice.id].audioUrl} />
              )}
              {activeSystemVoice && systemVoicePreviewState[activeSystemVoice.id]?.error && (
                <div className="voice-preview-message is-error">{systemVoicePreviewState[activeSystemVoice.id].error}</div>
              )}
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Clone Profile</p>
                  <h2>新增授权克隆档案</h2>
                </div>
                <Headphones size={22} />
              </div>
              <form className="form-grid" onSubmit={submitVoiceProfile}>
                <label>
                  档案名称
                  <input value={voiceProfileForm.name} onChange={(event) => setVoiceProfileForm({ ...voiceProfileForm, name: event.target.value })} />
                </label>
                <label>
                  授权人
                  <input
                    value={voiceProfileForm.ownerName}
                    onChange={(event) => setVoiceProfileForm({ ...voiceProfileForm, ownerName: event.target.value })}
                  />
                </label>
                <label>
                  使用场景
                  <select value={voiceProfileForm.scenario} onChange={(event) => setVoiceProfileForm({ ...voiceProfileForm, scenario: event.target.value })}>
                    <option>外呼</option>
                    <option>试听</option>
                    <option>客服回访</option>
                  </select>
                </label>
                <label>
                  回退系统音色
                  <select value={voiceProfileForm.fallbackVoice} onChange={(event) => setVoiceProfileForm({ ...voiceProfileForm, fallbackVoice: event.target.value })}>
                    {systemVoices.map((voice) => (
                      <option key={voice.id} value={voice.name}>
                        {voice.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="wide">
                  授权录音样本
                  <input
                    accept="audio/*,.wav,.mp3,.m4a,.aac,.ogg,.flac,.webm"
                    onChange={(event) => setVoiceSampleFile(event.target.files?.[0] ?? null)}
                    type="file"
                  />
                  <small>{voiceSampleFile ? `${voiceSampleFile.name} · ${formatBytes(voiceSampleFile.size)}` : "请上传客户/员工本人授权录音，作为音色复刻样本。"}</small>
                </label>
                <label className="wide">
                  授权材料 / 说明
                  <textarea
                    placeholder="填写授权证明、适用范围、录音来源说明。"
                    value={voiceProfileForm.consentMaterial}
                    onChange={(event) => setVoiceProfileForm({ ...voiceProfileForm, consentMaterial: event.target.value })}
                  />
                </label>
                {voiceSampleMessage && <div className="form-result wide">{voiceSampleMessage}</div>}
                <button className="primary-button" disabled={isUploadingVoiceSample} type="submit">
                  <Plus size={16} />
                  {isUploadingVoiceSample ? "上传中..." : "新增克隆档案"}
                </button>
              </form>
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Clone Assets</p>
                  <h2>授权克隆档案</h2>
                </div>
                <ClipboardList size={22} />
              </div>
              <div className="account-list">
                {customerVoiceProfiles.length === 0 && <div className="empty-state">暂无客户或员工授权克隆档案。</div>}
                {customerVoiceProfiles.map((profile) => (
                  <article
                    className={profile.id === activeVoiceProfile?.id ? "account-row clickable-card is-selected" : "account-row clickable-card"}
                    key={profile.id}
                    onClick={() => {
                      setSelectedVoiceProfileId(profile.id);
                      setActiveVoiceTab("授权审核");
                    }}
                  >
                    <div className="account-row-head">
                      <div>
                        <strong>{profile.name}</strong>
                        <small>{profile.ownerName} · {profile.scenario} · 回退 {profile.fallbackVoice}</small>
                        <small>{profile.riskNote}</small>
                      </div>
                      <em>{usableVoiceSampleCount(profile.id)} 样本</em>
                    </div>
                    <div className="account-row-meta">
                      <span>{profile.status}</span>
                      <span>{profile.authorizationStatus}</span>
                    </div>
                  </article>
                ))}
              </div>
              {activeVoiceProfile && (
                <div className="form-grid single">
                  <label>
                    为选中档案补充录音
                    <input
                      accept="audio/*,.wav,.mp3,.m4a,.aac,.ogg,.flac,.webm"
                      onChange={(event) => setVoiceSampleFile(event.target.files?.[0] ?? null)}
                      type="file"
                    />
                  </label>
                  <button className="secondary-button" disabled={isUploadingVoiceSample} onClick={() => void uploadSampleForActiveProfile()} type="button">
                    <Upload size={16} />
                    上传到 {activeVoiceProfile.name}
                  </button>
                  <div className="profile-grid">
                    <div>
                      <span>可用样本</span>
                      <strong>{activeVoiceProfileSamples.filter((sample) => sample.qualityStatus === "可用").length}</strong>
                    </div>
                    <div>
                      <span>最近样本</span>
                      <strong>{activeVoiceProfileSamples[0]?.fileName ?? "未上传"}</strong>
                    </div>
                  </div>
                </div>
              )}
            </article>
          </section>
        )}

        {showAuth && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Authorization</p>
                  <h2>授权审核</h2>
                </div>
                <ShieldAlert size={22} />
              </div>
              <div className="record-grid">
                {customerVoiceProfiles.length === 0 && <div className="empty-state">暂无待审核的授权克隆档案。</div>}
                {customerVoiceProfiles.map((profile) => (
                  <article
                    className={profile.id === activeVoiceProfile?.id ? "record-card clickable-card is-selected" : "record-card clickable-card"}
                    key={profile.id}
                    onClick={() => setSelectedVoiceProfileId(profile.id)}
                  >
                    <div>
                      <strong>{profile.name}</strong>
                      <span>{profile.authorizationStatus}</span>
                    </div>
                    <p>{profile.consentMaterial || "等待授权材料。"}</p>
                    <small>{usableVoiceSampleCount(profile.id)} 条可用录音样本 · {profile.riskNote}</small>
                    <div className="button-row card-actions">
                      <button
                        className="row-action is-primary"
                        onClick={(event) => {
                          event.stopPropagation();
                          void updateVoiceAuthorization(profile, "授权通过");
                        }}
                        type="button"
                      >
                        通过授权
                      </button>
                      <button
                        className="row-action"
                        onClick={(event) => {
                          event.stopPropagation();
                          void updateVoiceAuthorization(profile, "授权撤回");
                        }}
                        type="button"
                      >
                        撤回授权
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </article>
          </section>
        )}

        {showTraining && (
          <section className="content-grid lower">
            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Training</p>
                  <h2>复刻生成入口</h2>
                </div>
                <Activity size={22} />
              </div>
              <div className="account-list">
                <div className="form-result">
                  {voiceProviderStatus.engineName} · {voiceProviderStatus.message}
                  {!voiceProviderStatus.samplePublicBaseUrlConfigured && " 请配置公网样本地址后再提交。"}
                </div>
                <div className="button-row">
                  <button className="secondary-button" disabled={isCheckingVoiceProvider} onClick={() => void checkVoiceProviderStatus()} type="button">
                    <RefreshCw size={16} />
                    {isCheckingVoiceProvider ? "检测中..." : "检测真实服务"}
                  </button>
                </div>
                {customerVoiceProfiles.length === 0 && <div className="empty-state">暂无可复刻的授权克隆档案。</div>}
                {customerVoiceProfiles.map((profile) => {
                  const blockReason = voiceTrainingBlockReason(profile);
                  const usableSamples = usableVoiceSampleCount(profile.id);
                  const isCreatingClone = creatingVoiceCloneProfileId === profile.id;
                  return (
                    <article
                      className={profile.id === activeVoiceProfile?.id ? "account-row clickable-card is-selected" : "account-row clickable-card"}
                      key={profile.id}
                      onClick={() => setSelectedVoiceProfileId(profile.id)}
                    >
                      <div className="account-row-head">
                        <div>
                          <strong>{profile.name}</strong>
                          <small>{profile.authorizationStatus} · {profile.status} · {usableSamples} 条可用录音样本</small>
                          <small>{blockReason || "授权、录音样本和 DashScope/CosyVoice 均已满足，可生成复刻音色。"}</small>
                        </div>
                        <button
                          className="row-action is-primary"
                          disabled={Boolean(blockReason) || Boolean(creatingVoiceCloneProfileId)}
                          onClick={(event) => {
                            event.stopPropagation();
                            void createVoiceTrainingJob(profile);
                          }}
                          type="button"
                        >
                          {isCreatingClone ? "生成中..." : "生成复刻"}
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>
              {voiceSampleMessage && <div className="form-result">{voiceSampleMessage}</div>}
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Jobs</p>
                  <h2>复刻任务</h2>
                </div>
                <Clock3 size={22} />
              </div>
              <div className="task-list">
                {customerVoiceTrainingJobs.length === 0 && (
                  <div className="empty-state">
                    {voiceOverview.cloneTrainingEnabled ? "暂无复刻生成任务。" : "真实克隆服务未接入，暂不会产生复刻任务。"}
                  </div>
                )}
                {customerVoiceTrainingJobs.map((job) => (
                  <div className="task-row" key={job.id}>
                    <span>{job.progress}%</span>
                    <div>
                      <strong>{customerVoiceProfiles.find((profile) => profile.id === job.profileId)?.name ?? "授权克隆档案"}</strong>
                      <small>{job.engine} · {job.message}</small>
                    </div>
                    <em>{job.status}</em>
                  </div>
                ))}
              </div>
            </article>
          </section>
        )}

        {showUsage && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Clone Audit</p>
                  <h2>克隆语音记录</h2>
                </div>
                <Activity size={22} />
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>克隆音色</th>
                      <th>外部音色ID</th>
                      <th>样本</th>
                      <th>引擎</th>
                      <th>状态</th>
                      <th>试听</th>
                      <th>结果</th>
                      <th>时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {customerVoiceCloneRecords.map((record) => (
                      <tr key={record.id}>
                        <td>{record.clonedVoiceName}</td>
                        <td>{record.externalVoiceId || "未生成"}</td>
                        <td>{record.sampleCount} 条 / {record.sampleMinutes} 分钟</td>
                        <td>{record.engine}</td>
                        <td>{record.status}</td>
                        <td>
                          {record.previewAudioUrl ? (
                            <audio controls preload="none" src={apiAssetUrl(record.previewAudioUrl)} />
                          ) : (
                            "暂无"
                          )}
                        </td>
                        <td>{record.result}</td>
                        <td>{new Date(record.createdAt).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {customerVoiceCloneRecords.length === 0 && <div className="empty-state">暂无克隆语音记录，上传样本并生成复刻音色后会自动写入。</div>}
              </div>
            </article>

            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Audit</p>
                  <h2>声音使用记录</h2>
                </div>
                <Database size={22} />
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>档案</th>
                      <th>商家</th>
                      <th>场景</th>
                      <th>结果</th>
                      <th>回退</th>
                      <th>时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {voiceUsageRecords.map((record) => (
                      <tr key={record.id}>
                        <td>{voiceLabelForUsage(record.profileId)}</td>
                        <td>{record.merchantName}</td>
                        <td>{record.scenario}</td>
                        <td>{record.result}</td>
                        <td>{record.fallbackUsed ? "是" : "否"}</td>
                        <td>{new Date(record.createdAt).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          </section>
        )}
      </>
    );
  }

  function renderDefaultWorkspace() {
    return (
      <>
        <section className="content-grid">
          <article className="panel">
            <div className="panel-title">
              <div>
                <p>线索库</p>
                <h2>新增商家线索</h2>
              </div>
              <Upload size={22} />
            </div>
            <form className="form-grid" onSubmit={submitLead}>
              <label>
                商家名称
                <input value={leadForm.name} onChange={(event) => setLeadForm({ ...leadForm, name: event.target.value })} />
              </label>
              <label>
                平台
                <select value={leadForm.platform} onChange={(event) => setLeadForm({ ...leadForm, platform: event.target.value })}>
                  <option>视频号</option>
                  <option>抖音</option>
                  <option>小红书</option>
                  <option>美团</option>
                </select>
              </label>
              <label>
                城市
                <input value={leadForm.city} onChange={(event) => setLeadForm({ ...leadForm, city: event.target.value })} />
              </label>
              <label>
                品类
                <input
                  value={leadForm.category}
                  onChange={(event) => setLeadForm({ ...leadForm, category: event.target.value })}
                />
              </label>
              <label>
                联系人
                <input
                  value={leadForm.contactName}
                  onChange={(event) => setLeadForm({ ...leadForm, contactName: event.target.value })}
                />
              </label>
              <label>
                电话
                <input value={leadForm.phone} onChange={(event) => setLeadForm({ ...leadForm, phone: event.target.value })} />
              </label>
              <label className="wide">
                平台店铺 URL
                <input
                  placeholder="用于真实平台私信定位商家，可先留空"
                  value={leadForm.platformUrl}
                  onChange={(event) => setLeadForm({ ...leadForm, platformUrl: event.target.value })}
                />
              </label>
              <button className="primary-button" type="submit">
                <CheckCircle2 size={16} />
                保存线索
              </button>
            </form>
          </article>

          <article className="panel">
            <div className="panel-title">
              <div>
                <p>任务中心</p>
                <h2>创建触达任务</h2>
              </div>
              <PhoneCall size={22} />
            </div>
            <form className="form-grid" onSubmit={submitTask}>
              <label className="wide">
                任务名称
                <input value={taskForm.name} onChange={(event) => setTaskForm({ ...taskForm, name: event.target.value })} />
              </label>
              <label>
                触达方式
                <select
                  value={taskForm.channel}
                  onChange={(event) => setTaskForm({ ...taskForm, channel: event.target.value as OutreachTask["channel"] })}
                >
                  <option value="call">AI外呼</option>
                  <option value="dm">平台私信</option>
                  <option value="collector">线索采集</option>
                </select>
              </label>
              <label>
                目标数量
                <input
                  min={1}
                  type="number"
                  value={taskForm.targetCount}
                  onChange={(event) => setTaskForm({ ...taskForm, targetCount: Number(event.target.value) })}
                />
              </label>
              <label className="wide">
                预约时间
                <input
                  type="datetime-local"
                  value={taskForm.scheduledAt}
                  onChange={(event) => setTaskForm({ ...taskForm, scheduledAt: event.target.value })}
                />
              </label>
              <button className="primary-button" type="submit">
                <CheckCircle2 size={16} />
                创建任务
              </button>
            </form>
          </article>
        </section>

        <section className="content-grid lower">
          <article className="panel">
            <div className="panel-title">
              <div>
                <p>最近线索</p>
                <h2>商家跟进列表</h2>
              </div>
              <Users size={22} />
            </div>
            <LeadTable leads={leads} selectable={false} selectedLeadIds={selectedLeadIds} onToggleLead={toggleLead} />
          </article>

          <article className="panel">
            <div className="panel-title">
              <div>
                <p>任务队列</p>
                <h2>触达执行状态</h2>
              </div>
              <MessageSquareText size={22} />
            </div>
            <TaskList tasks={tasks} onStart={startOutboundTask} />
          </article>
        </section>
      </>
    );
  }

  function renderOutboundWorkspace() {
    const showOverview = activeOutboundTab === "外呼总览";
    const showTasks = showOverview || activeOutboundTab === "任务列表";
    const showScript = showOverview || activeOutboundTab === "话术流程";
    const showRecords = showOverview || activeOutboundTab === "通话记录";
    const showRules = showOverview || activeOutboundTab === "重拨规则";
    const showRealtime = showOverview || activeOutboundTab === "实时监听";

    return (
      <>
        <section className="outbound-tabs" aria-label="外呼模块页面">
          {outboundTabs.map((tab) => (
            <button
              className={tab === activeOutboundTab ? "is-active" : ""}
              key={tab}
              onClick={() => setActiveOutboundTab(tab)}
              type="button"
            >
              {tab}
            </button>
          ))}
        </section>

        <section className="metrics outbound-metrics">
          <MetricCard icon={<Radio size={20} />} label="在线坐席" value={`${overview.aiSeats} AI`} detail="并发中" tone="green" />
          <MetricCard icon={<Activity size={20} />} label="进行中通话" value={overview.activeCalls} detail="实时转写" tone="blue" />
          <MetricCard icon={<Headphones size={20} />} label="需接管" value={overview.needsHandoff} detail="客户追问" tone="amber" />
          <MetricCard icon={<ShieldAlert size={20} />} label="异常静默" value={overview.silentAlerts} detail="待排查" tone="rose" />
        </section>

        {showRealtime && (
          <section className="content-grid outbound-main">
            <article className="panel span-2 line-health-panel">
              <div className="panel-title">
                <div>
                  <p>UC100 / Asterisk</p>
                  <h2>真实线路接入</h2>
                </div>
                <button className="secondary-button" disabled={isCheckingTelephony} onClick={refreshTelephonyStatus} type="button">
                  <RefreshCw size={16} className={isCheckingTelephony ? "spin" : ""} />
                  {isCheckingTelephony ? "预检中" : "预检线路"}
                </button>
              </div>
              <div className="line-health-grid">
                <div>
                  <span>线路模式</span>
                  <strong>{telephonyConfig.gatewayMode === "asterisk" ? "真实线路" : "模拟线路"}</strong>
                </div>
                <div>
                  <span>线路状态</span>
                  <strong>{telephonyReadinessLabel(telephonyHealth, telephonyPreflight)}</strong>
                </div>
                <div>
                  <span>AMI</span>
                  <strong>{telephonyHealth.authenticated ? "已登录" : telephonyHealth.amiReachable ? "已连接" : "未连接"}</strong>
                </div>
                <div>
                  <span>Trunk</span>
                  <strong>{telephonyConfig.asteriskTrunkName || "待配置"}</strong>
                </div>
                <div>
                  <span>通道上限</span>
                  <strong>{telephonyHealth.maxChannels || telephonyConfig.asteriskMaxChannels} 路</strong>
                </div>
                <div>
                  <span>拨号开关</span>
                  <strong>{telephonyConfig.asteriskLiveCallEnabled ? "单号试拨" : "未开启"}</strong>
                </div>
              </div>
              <div className="line-preflight">
                <div className="line-preflight-header">
                  <div>
                    <span>预检结论</span>
                    <strong>{telephonyPreflightSummary(telephonyPreflight)}</strong>
                  </div>
                  <small>{new Date(telephonyPreflight.checkedAt).toLocaleString("zh-CN", { hour12: false })}</small>
                </div>
                <p>{telephonyPreflight.nextStep}</p>
                <div className="line-preflight-steps">
                  {telephonyPreflight.steps.map((step) => (
                    <div className="line-preflight-step" key={step.key}>
                      <span className={`line-preflight-badge is-${step.status}`}>{telephonyPreflightStatusText(step.status)}</span>
                      <div>
                        <strong>{step.label}</strong>
                        <small>{step.detail}</small>
                        {step.action && <em>{step.action}</em>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="line-test-row">
                <form className="line-test-form" onSubmit={submitTelephonyTestCall}>
                  <label>
                    测试号码
                    <input
                      placeholder="输入自己的手机号"
                      value={telephonyTestForm.phone}
                      onChange={(event) => setTelephonyTestForm({ ...telephonyTestForm, phone: event.target.value })}
                    />
                  </label>
                  <label>
                    主叫显示
                    <input
                      placeholder="默认 AI获客"
                      value={telephonyTestForm.callerId}
                      onChange={(event) => setTelephonyTestForm({ ...telephonyTestForm, callerId: event.target.value })}
                    />
                  </label>
                  <button className="primary-button" disabled={isTestingTelephony || !telephonyTestForm.phone.trim()} type="submit">
                    <PhoneCall size={16} />
                    {isTestingTelephony ? "提交中" : "单号试拨"}
                  </button>
                </form>
                <div className="line-test-result">
                  <strong>{telephonyMessage}</strong>
                  <span>{telephonyHealth.errors[0] ?? telephonyHealth.trunkStatus}</span>
                  {telephonyTestResult && (
                    <small>
                      {telephonyTestResult.gatewayStatus} · {telephonyTestResult.actionId} · {telephonyTestResult.channel}
                    </small>
                  )}
                </div>
              </div>
            </article>

            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Table</p>
                  <h2>实时通话</h2>
                </div>
                <button className="secondary-button" onClick={loadData} type="button">
                  <RefreshCw size={16} className={isLoading ? "spin" : ""} />
                  刷新
                </button>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>商家</th>
                      <th>AI</th>
                      <th>通话时长</th>
                      <th>实时意向</th>
                      <th>当前节点</th>
                      <th>动作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {liveCalls.length === 0 && (
                      <tr>
                        <td colSpan={6}>
                          <span className="empty-state">暂无实时通话，创建外呼任务后点击启动。</span>
                        </td>
                      </tr>
                    )}
                    {liveCalls.map((record) => (
                      <tr key={record.id}>
                        <td>
                          <strong>{record.merchantName}</strong>
                          <small>{record.phone ?? "无电话"}</small>
                        </td>
                        <td>{record.aiSeat}</td>
                        <td>{formatDuration(record.durationSeconds)}</td>
                        <td>
                          <span className={`intent-pill intent-${record.intentLevel.toLowerCase()}`}>{record.intentLevel}</span>
                        </td>
                        <td>{record.currentNode}</td>
                        <td>{record.needHandoff ? "接管" : record.recallAt ? "重拨" : "监听"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>

            <article className="panel ops-card">
              <div className="panel-title">
                <div>
                  <p>Ops Notes</p>
                  <h2>流程和提示</h2>
                </div>
                <Zap size={22} />
              </div>
              <ol className="ops-steps">
                <li>筛选对象</li>
                <li>确认配置</li>
                <li>执行动作</li>
                <li>记录结果</li>
                <li>进入下一步</li>
              </ol>
              <div className="notice-list">
                <span>实时回复客户依赖低延迟模型和线路。</span>
                <span>客户追问时要能人工无缝接管。</span>
                <span>未接和忙线客户进入重拨规则。</span>
              </div>
            </article>
          </section>
        )}

        {showTasks && (
          <section className="content-grid lower">
            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Form</p>
                  <h2>外呼任务操作表单</h2>
                </div>
                <PhoneCall size={22} />
              </div>
              <form className="form-grid" onSubmit={submitOutboundTask}>
                <label className="wide">
                  任务名称
                  <input
                    value={outboundForm.name}
                    onChange={(event) => setOutboundForm({ ...outboundForm, name: event.target.value })}
                  />
                </label>
                <label>
                  并发坐席
                  <input
                    min={1}
                    max={50}
                    type="number"
                    value={outboundForm.concurrency}
                    onChange={(event) => setOutboundForm({ ...outboundForm, concurrency: Number(event.target.value) })}
                  />
                </label>
                <label>
                  预约时间
                  <input
                    type="datetime-local"
                    value={outboundForm.scheduledAt}
                    onChange={(event) => setOutboundForm({ ...outboundForm, scheduledAt: event.target.value })}
                  />
                </label>
                <button className="primary-button" type="submit">
                  <Plus size={16} />
                  创建外呼任务
                </button>
              </form>

              <div className="lead-picker">
                <div className="section-caption">
                  <strong>筛选外呼对象</strong>
                  <small>{selectedLeadIds.length} 个已选</small>
                </div>
                <LeadTable leads={callableLeads} selectable selectedLeadIds={selectedLeadIds} onToggleLead={toggleLead} />
              </div>
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Queue</p>
                  <h2>外呼任务列表</h2>
                </div>
                <Clock3 size={22} />
              </div>
              <TaskList tasks={outboundTasks} onStart={startOutboundTask} />
            </article>
          </section>
        )}

        {showScript && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Script Flow</p>
                  <h2>话术流程</h2>
                </div>
                <Bot size={22} />
              </div>
              <div className="script-card compact">
                <div className="section-caption">
                  <strong>{activeScript?.name ?? "暂无话术"}</strong>
                  <small>{activeScript?.isActive ? "启用中" : "未启用"}</small>
                </div>
                <div className="flow-node-grid">
                  <article>
                    <span>开场白</span>
                    <p>{activeScript?.opening}</p>
                  </article>
                  <article>
                    <span>需求确认</span>
                    <p>{activeScript?.qualification}</p>
                  </article>
                  <article>
                    <span>异议处理</span>
                    <p>{activeScript?.objection}</p>
                  </article>
                  <article>
                    <span>收口动作</span>
                    <p>{activeScript?.closing}</p>
                  </article>
                </div>
              </div>
            </article>
          </section>
        )}

        {showRules && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Recall Rules</p>
                  <h2>重拨规则</h2>
                </div>
                <Clock3 size={22} />
              </div>
              <div className="rule-detail-grid">
                <div>
                  <strong>未接重拨</strong>
                  <span>{activeRule?.noAnswerIntervalMinutes ?? 0} 分钟后再次拨打</span>
                </div>
                <div>
                  <strong>忙线重拨</strong>
                  <span>{activeRule?.busyIntervalMinutes ?? 0} 分钟后再次拨打</span>
                </div>
                <div>
                  <strong>次数上限</strong>
                  <span>最多 {activeRule?.maxAttempts ?? 0} 次</span>
                </div>
                <div>
                  <strong>静默时段</strong>
                  <span>{activeRule?.quietStart} - {activeRule?.quietEnd}</span>
                </div>
              </div>
            </article>
          </section>
        )}

        {showRecords && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Records</p>
                  <h2>通话明细和转写</h2>
                </div>
                <ClipboardList size={22} />
              </div>
              <div className="record-grid">
                {callRecords.length === 0 && <div className="empty-state">暂无通话记录。</div>}
                {callRecords.slice(0, 6).map((record) => (
                  <article className="record-card" key={record.id}>
                    <div>
                      <strong>{record.merchantName}</strong>
                      <span>{record.outcome}</span>
                    </div>
                    <p>{record.transcript}</p>
                    <small>
                      {record.aiSeat} · {formatDuration(record.durationSeconds)} · {record.currentNode}
                    </small>
                  </article>
                ))}
              </div>
            </article>
          </section>
        )}
      </>
    );
  }

  function renderDmWorkspace() {
    const showOverview = activeDmTab === "私信总览";
    const showTasks = showOverview || activeDmTab === "任务列表";
    const showAccounts = showOverview || activeDmTab === "账号管理";
    const showRotation = showOverview || activeDmTab === "轮换规则";
    const showTemplates = showOverview || activeDmTab === "消息模板";
    const showConversations = showOverview || activeDmTab === "会话记录";
    const showRealtime = showOverview || activeDmTab === "回复监听";

    return (
      <>
        <section className="outbound-tabs" aria-label="平台私信模块页面">
          {dmTabs.map((tab) => (
            <button className={tab === activeDmTab ? "is-active" : ""} key={tab} onClick={() => setActiveDmTab(tab)} type="button">
              {tab}
            </button>
          ))}
        </section>

        <section className="metrics outbound-metrics">
          <MetricCard icon={<MessageSquareText size={20} />} label="平台个人号" value={dmOverview.activeAccounts} detail={`共 ${dmOverview.accounts} 个`} tone="blue" />
          <MetricCard icon={<Zap size={20} />} label="今日发送" value={dmOverview.todaySent} detail="平台私信" tone="green" />
          <MetricCard icon={<Activity size={20} />} label="商家回复" value={dmOverview.replies} detail="今日回复" tone="amber" />
          <MetricCard icon={<Headphones size={20} />} label="需接管" value={dmOverview.needsHandoff} detail="人工跟进" tone="rose" />
        </section>

        {showRealtime && (
          <section className="content-grid outbound-main">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Live Inbox</p>
                  <h2>平台私信回复监听</h2>
                </div>
                <div className="button-row">
                  <button className="secondary-button" onClick={syncDmReplies} type="button">
                    <MessageSquareText size={16} />
                    同步回复
                  </button>
                  <button className="secondary-button" onClick={loadData} type="button">
                    <RefreshCw size={16} className={isLoading ? "spin" : ""} />
                    刷新
                  </button>
                </div>
              </div>
              <div className="sync-summary">
                上次同步：检查 {dmSyncResult.checked} 条，会话新增回复 {dmSyncResult.newReplies} 条，需接管 {dmSyncResult.needsHandoff} 条。
              </div>
              <div className="dm-inbox-grid">
                <div className="conversation-list">
                  {dmConversations.length === 0 && <div className="empty-state">暂无私信会话，创建任务后点击启动。</div>}
                  {dmConversations.slice(0, 8).map((conversation) => (
                    <article className={conversation.needHandoff ? "dm-conversation is-hot" : "dm-conversation"} key={conversation.id}>
                      <div>
                        <strong>{conversation.merchantName}</strong>
                        <span>{conversation.platform}</span>
                      </div>
                      <p>{conversation.lastMessage}</p>
                      <small>
                        {conversation.status} · 意向 {conversation.intentLevel} · {conversation.needHandoff ? "需接管" : "自动跟进"}
                      </small>
                    </article>
                  ))}
                </div>
                <div className="message-list">
                  {dmMessages.length === 0 && <div className="empty-state">暂无消息内容。</div>}
                  {dmMessages.slice(0, 8).map((message) => (
                    <article className={`message-bubble ${message.direction === "inbound" ? "is-inbound" : "is-outbound"}`} key={message.id}>
                      <span>{message.direction === "inbound" ? "商家回复" : "系统私信"}</span>
                      <p>{message.content}</p>
                      <small>{message.status}</small>
                    </article>
                  ))}
                </div>
              </div>
            </article>
          </section>
        )}

        {showTasks && (
          <section className="content-grid lower">
            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Form</p>
                  <h2>创建平台私信任务</h2>
                </div>
                <MessageSquareText size={22} />
              </div>
              <form className="form-grid" onSubmit={submitDmTask}>
                <label className="wide">
                  任务名称
                  <input value={dmForm.name} onChange={(event) => setDmForm({ ...dmForm, name: event.target.value })} />
                </label>
                <label>
                  发送账号规则
                  <select value={dmForm.accountId} onChange={(event) => setDmForm({ ...dmForm, accountId: event.target.value })}>
                    <option value="">按商家平台自动轮换（推荐）</option>
                    {dmSupportedAccounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        指定 {account.platform} · {account.accountName}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  消息模板
                  <select value={dmForm.templateId} onChange={(event) => setDmForm({ ...dmForm, templateId: event.target.value })}>
                    {dmTemplates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="wide">
                  预约时间
                  <input
                    type="datetime-local"
                    value={dmForm.scheduledAt}
                    onChange={(event) => setDmForm({ ...dmForm, scheduledAt: event.target.value })}
                  />
                </label>
                <button className="primary-button" type="submit">
                  <Plus size={16} />
                  创建私信任务
                </button>
              </form>

              <div className="lead-picker">
                <div className="section-caption">
                  <strong>筛选私信对象</strong>
                  <small>{selectedDmLeadIds.filter((leadId) => dmReachableLeads.some((lead) => lead.id === leadId)).length} 个已选</small>
                </div>
                <div className="rotation-hint">
                  <CheckCircle2 size={16} />
                  <span>按线索平台自动分配同平台个人号：美团商家用美团号池，饿了么商家用饿了么号池，抖音商家用抖音号池。</span>
                </div>
                {dmUnsupportedLeads.length > 0 && (
                  <div className="rotation-hint is-warning">
                    <ShieldAlert size={16} />
                    <span>
                      已排除 {dmUnsupportedLeads.length} 条暂不支持私信的平台线索；
                      {unsupportedDmPlatformTips[dmUnsupportedLeads[0]?.platform] ?? "可改用外呼或其他触达方式。"}
                    </span>
                  </div>
                )}
                <LeadTable leads={dmReachableLeads} selectable selectedLeadIds={selectedDmLeadIds} onToggleLead={toggleDmLead} />
              </div>
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Queue</p>
                  <h2>私信任务列表</h2>
                </div>
                <Clock3 size={22} />
              </div>
              <TaskList tasks={dmTasks} onStart={startDmTask} startableChannel="dm" />
            </article>
          </section>
        )}

        {showAccounts && (
          <section className="content-grid lower">
            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Accounts</p>
                  <h2>平台个人号管理</h2>
                </div>
                <Users size={22} />
              </div>
              <div className="account-isolation-summary">
                <div>
                  <strong>{dmSupportedAccounts.length}</strong>
                  <span>已配置个人号</span>
                </div>
                <div>
                  <strong>{isolatedDmAccountCount}</strong>
                  <span>独立登录环境</span>
                </div>
                <p>每个个人号独立登录、独立额度、独立风控状态，可按平台添加多个账号轮流触达。</p>
              </div>
              <div className="platform-account-strip" aria-label="按平台添加个人号">
                {dmAccountPlatforms.map((platform) => (
                  <button key={platform} onClick={() => prepareNewDmAccount(platform)} type="button">
                    <span>{platform}</span>
                    <strong>{dmAccountCountByPlatform[platform] ?? 0} 个号</strong>
                    <small>添加个人号</small>
                  </button>
                ))}
              </div>
              <form className="form-grid" onSubmit={submitDmAccount}>
                <label>
                  平台
                  <select value={dmAccountForm.platform} onChange={(event) => setDmAccountForm({ ...dmAccountForm, platform: event.target.value })}>
                    {dmAccountPlatforms.map((platform) => (
                      <option key={platform}>{platform}</option>
                    ))}
                  </select>
                </label>
                <label>
                  个人号名称
                  <input
                    data-dm-account-name="true"
                    placeholder="例如：美团个人号-南昌1号"
                    value={dmAccountForm.accountName}
                    onChange={(event) => setDmAccountForm({ ...dmAccountForm, accountName: event.target.value })}
                  />
                </label>
                <label>
                  账号备注
                  <input
                    placeholder="例如：南昌本地生活一组"
                    value={dmAccountForm.loginLabel}
                    onChange={(event) => setDmAccountForm({ ...dmAccountForm, loginLabel: event.target.value })}
                  />
                </label>
                <label>
                  日发送上限
                  <input
                    min={1}
                    type="number"
                    value={dmAccountForm.dailyLimit}
                    onChange={(event) => setDmAccountForm({ ...dmAccountForm, dailyLimit: Number(event.target.value) })}
                  />
                </label>
                <label>
                  发送间隔秒
                  <input
                    min={0}
                    type="number"
                    value={dmAccountForm.minSendIntervalSeconds}
                    onChange={(event) => setDmAccountForm({ ...dmAccountForm, minSendIntervalSeconds: Number(event.target.value) })}
                  />
                </label>
                <button className="primary-button" type="submit">
                  <CheckCircle2 size={16} />
                  保存账号
                </button>
              </form>
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Logged In</p>
                  <h2>登录账号列表</h2>
                </div>
                <ShieldAlert size={22} />
              </div>
              <div className="logged-account-panel">
                <div className="logged-account-summary">
                  <strong>{dmLoggedInAccounts.length}</strong>
                  <span>个已登录个人号</span>
                  <small>剩余额度 {dmLoggedInRemainingQuota} · 自动按同平台轮换</small>
                </div>
                {dmLoggedInAccounts.length === 0 ? (
                  <div className="empty-state compact">暂无已登录账号。请在下方登录工作台完成真实平台登录，再点击“登录后检测”。</div>
                ) : (
                  <div className="logged-account-list">
                    {dmLoggedInAccounts.map((account) => (
                      <button
                        className={`logged-account-item ${account.id === activeLoginAccount?.id ? "is-selected" : ""}`}
                        key={account.id}
                        onClick={() => selectDmLoginAccount(account.id)}
                        type="button"
                      >
                        <div>
                          <span>{account.platform}</span>
                          <strong>{account.accountName}</strong>
                          <small>{accountLoginLabel(account)} · {account.riskStatus ?? "正常"}</small>
                        </div>
                        <em>
                          {Math.max(0, account.dailyLimit - account.sentToday)} 条可发 · {account.minSendIntervalSeconds ?? 0} 秒/条
                        </em>
                        <small className="logged-account-view">查看账号</small>
                      </button>
                    ))}
                  </div>
                )}
                <div className="logged-account-footnote">
                  这里只展示已通过检测的个人号；待登录账号在下方登录工作台处理。
                </div>
              </div>
            </article>

            <article className="panel span-2 login-workbench" ref={loginWorkbenchRef}>
              <div className="panel-title">
                <div>
                  <p>Login</p>
                  <h2>客户端内置个人号登录工作台</h2>
                </div>
                <KeyRound size={22} />
              </div>

              <div className="login-shell">
                <aside className="login-account-rail">
                  {dmSupportedAccounts.length === 0 && <div className="empty-state">暂无可登录的平台个人号。</div>}
                  {dmSupportedAccounts.map((account) => (
                    <button
                      className={`login-account-chip ${account.id === activeLoginAccount?.id ? "is-selected" : ""}`}
                      disabled={isPreparingDmLogin}
                      key={account.id}
                      onClick={() => selectDmLoginAccount(account.id)}
                      type="button"
                    >
                      <span>{account.platform}</span>
                      <strong>{account.accountName}</strong>
                      <small>{displayDmLoginStatus(account.sessionStatus)} · {account.riskStatus ?? "正常"}</small>
                    </button>
                  ))}
                </aside>

                <section className="embedded-login-frame">
                  <div className="embedded-browser-bar">
                    <span className="status-dot" />
                    <strong>{activeLoginAccount ? `${activeLoginAccount.platform} 个人号登录页` : "选择平台个人号"}</strong>
                    <em>{activeLoginEntryText}</em>
                  </div>
                  <div className={`embedded-login-body ${dmLoginEntryReady ? "is-open" : ""}`}>
                    <div className={`login-preview has-real-login ${isDesktopClient ? "is-desktop-client" : "is-browser-preview"}`}>
                      <div className={`real-login-panel ${isDesktopClient && dmLoginEntryReady ? "has-native-webview" : ""}`}>
                        <div
                          className={`native-login-viewport ${isDesktopClient && dmLoginEntryReady ? "is-visible" : ""}`}
                          ref={nativeLoginViewportRef}
                        />
                        {(!isDesktopClient || !dmLoginEntryReady) && (
                          <div className="real-login-placeholder">
                            <div className="real-login-mark">
                              <KeyRound size={30} />
                            </div>
                            <span>{activeLoginAccount?.platform ?? "平台"}</span>
                            <strong>{activeLoginAccount ? `${activeLoginAccount.platform} 内置个人号登录` : "选择平台个人号"}</strong>
                            <p>
                              {isDesktopClient
                                ? dmLoginStatusHint(activeLoginAccount?.sessionStatus)
                                : "当前是网页预览，第三方平台登录页不能嵌入普通浏览器。请用桌面客户端打开后在这里登录。"}
                            </p>
                            <div className="real-login-url">
                              <small>内置入口</small>
                              <b>{loginEntryHost(activeLoginUrl)}</b>
                            </div>
                            <div className="real-login-steps">
                              <div>
                                <em>1</em>
                                <span>在内置区加载平台</span>
                              </div>
                              <div>
                                <em>2</em>
                                <span>独立 Profile 隔离</span>
                              </div>
                              <div>
                                <em>3</em>
                                <span>登录后检测</span>
                              </div>
                            </div>
                            <div className={`login-mode-alert ${isDesktopClient ? "is-desktop" : "is-preview"}`}>
                              {isDesktopClient
                                ? "会在当前区域加载平台页面，不会跳到外部浏览器。"
                                : "你现在看的不是桌面客户端，所以这里不能登录；请打开桌面客户端窗口。"}
                            </div>
                            {!isDesktopClient && (
                              <div className="desktop-login-command">
                                <small>本地启动命令</small>
                                <code>cd frontend &amp;&amp; npm run desktop</code>
                              </div>
                            )}
                            <button
                              className="primary-button real-login-button"
                              disabled={!activeLoginAccount || isPreparingDmLogin || !isDesktopClient}
                              onClick={() => activeLoginAccount && openRealDmLogin(activeLoginAccount.id)}
                              type="button"
                            >
                              <KeyRound size={16} />
                              {isPreparingDmLogin ? "加载中" : isDesktopClient ? "在内置页登录" : "网页预览不能登录"}
                            </button>
                          </div>
                        )}
                      </div>
                      <div className={`real-login-note ${dmLoginFeedbackTone}`}>
                        <strong>{activeLoginAccount ? activeLoginAccount.accountName : "平台个人号"}</strong>
                        <span>
                          {dmLoginMessage ||
                            "系统会为这个个人号使用独立 Profile。登录完成后不会立即标记成功，必须检测到 Cookie、localStorage 或页面登录标识后才显示已登录。"}
                        </span>
                      </div>
                    </div>
                    <div className="profile-inspector">
                      <div>
                        <span>平台</span>
                        <strong>{activeLoginAccount?.platform ?? "-"}</strong>
                      </div>
                      <div>
                        <span>登录状态</span>
                        <strong>{displayDmLoginStatus(activeLoginAccount?.sessionStatus)}</strong>
                      </div>
                      <div>
                        <span>今日额度</span>
                        <strong>
                          {activeLoginAccount ? `${activeLoginAccount.sentToday}/${activeLoginAccount.dailyLimit}` : "-"}
                        </strong>
                      </div>
                      <div>
                        <span>风险状态</span>
                        <strong>{activeLoginAccount?.riskStatus ?? "正常"}</strong>
                      </div>
                      <div>
                        <span>发送规则</span>
                        <strong>只给同平台商家发送</strong>
                      </div>
                    </div>
                  </div>
                  <div className="button-row login-actions">
                    <button
                      className="secondary-button"
                      disabled={!activeLoginAccount || isCheckingDmLogin}
                      onClick={() => activeLoginAccount && preflightDmAccount(activeLoginAccount.id)}
                      type="button"
                    >
                      <RefreshCw size={16} />
                      {isCheckingDmLogin && checkingDmAccountId === activeLoginAccount?.id ? "检测中..." : "登录后检测"}
                    </button>
                  </div>
                </section>
              </div>
            </article>

          </section>
        )}

        {showRotation && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Rotation</p>
                  <h2>个人号轮换规则</h2>
                </div>
                <RefreshCw size={22} />
              </div>
              <div className="rotation-rule-grid">
                <div>
                  <span>规则一</span>
                  <strong>按商家平台匹配</strong>
                  <p>美团商家只进入美团个人号池，饿了么和抖音同理，避免跨平台错发。</p>
                </div>
                <div>
                  <span>规则二</span>
                  <strong>同平台账号轮换</strong>
                  <p>优先选择同平台里发送量更低、间隔已满足、风险正常的个人号。</p>
                </div>
                <div>
                  <span>规则三</span>
                  <strong>额度和间隔保护</strong>
                  <p>每个个人号独立计算日发送上限、今日已发和最小发送间隔。</p>
                </div>
                <div>
                  <span>规则四</span>
                  <strong>异常账号自动跳过</strong>
                  <p>未登录、需验证、风控暂停或达到额度的账号不会参与本轮发送。</p>
                </div>
              </div>
              <div className="rotation-hint is-warning">
                <ShieldAlert size={16} />
                <span>视频号助手当前不支持主动私信商家，视频号线索会从平台私信任务里排除，可走外呼或其他合规触达方式。</span>
              </div>
            </article>

            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Pools</p>
                  <h2>轮换参数设置</h2>
                </div>
                <Settings size={22} />
              </div>
              <div className="rotation-hint">
                <CheckCircle2 size={16} />
                <span>这里设置每个个人号每天最多发多少条、多久发一次。创建私信任务时选择“按商家平台自动轮换”，系统就会按这些规则分配账号。</span>
              </div>
              {dmRotationMessage && <div className="form-result">{dmRotationMessage}</div>}
              <div className="rotation-settings-list">
                {dmSupportedAccounts.length === 0 && <div className="empty-state">暂无可配置账号，请先添加平台个人号。</div>}
                {dmAccountPlatforms.map((platformName) => {
                  const accountsForPlatform = dmSupportedAccounts.filter((account) => account.platform === platformName);
                  return (
                    <section className="rotation-platform-group" key={platformName}>
                      <div className="section-caption">
                        <strong>{platformName}账号池</strong>
                        <small>{accountsForPlatform.length} 个号</small>
                      </div>
                      {accountsForPlatform.length === 0 ? (
                        <div className="empty-state compact">暂无 {platformName} 个人号。</div>
                      ) : (
                        accountsForPlatform.map((account) => {
                          const draft = dmRuleDraft(account);
                          return (
                            <article className="rotation-setting-row" key={account.id}>
                              <div className="rotation-setting-account">
                                <span>{displayDmLoginStatus(account.sessionStatus)}</span>
                                <strong>{account.accountName}</strong>
                                <small>
                                  今日已发 {account.sentToday} 条 · 风险 {account.riskStatus ?? "正常"}
                                </small>
                              </div>
                              <label>
                                每天最多发送
                                <input
                                  min={1}
                                  type="number"
                                  value={draft.dailyLimit}
                                  onChange={(event) => updateDmRuleDraft(account, { dailyLimit: Number(event.target.value) })}
                                />
                              </label>
                              <label>
                                每条间隔秒
                                <input
                                  min={0}
                                  type="number"
                                  value={draft.minSendIntervalSeconds}
                                  onChange={(event) =>
                                    updateDmRuleDraft(account, { minSendIntervalSeconds: Number(event.target.value) })
                                  }
                                />
                              </label>
                              <button className="row-action is-primary" onClick={() => saveDmAccountRule(account)} type="button">
                                保存规则
                              </button>
                            </article>
                          );
                        })
                      )}
                    </section>
                  );
                })}
              </div>
            </article>

            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Pools</p>
                  <h2>各平台账号池状态</h2>
                </div>
                <Users size={22} />
              </div>
              <div className="rotation-pool-list">
                {dmRotationRows.map((row) => (
                  <article className="rotation-pool-row" key={row.platform}>
                    <div>
                      <span>{row.platform}</span>
                      <strong>{row.accounts.length} 个个人号</strong>
                    </div>
                    <div>
                      <span>可用账号</span>
                      <strong>{row.availableAccounts.length}</strong>
                    </div>
                    <div>
                      <span>剩余额度</span>
                      <strong>{row.totalRemaining}</strong>
                    </div>
                    <div className="wide">
                      <span>下一轮优先</span>
                      <strong>{row.nextAccount?.accountName ?? "暂无可用账号"}</strong>
                    </div>
                  </article>
                ))}
              </div>
            </article>
          </section>
        )}

        {showTemplates && (
          <section className="content-grid lower">
            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Template</p>
                  <h2>私信模板表单</h2>
                </div>
                <Bot size={22} />
              </div>
              <form className="form-grid" onSubmit={submitDmTemplate}>
                <label>
                  模板名称
                  <input value={dmTemplateForm.name} onChange={(event) => setDmTemplateForm({ ...dmTemplateForm, name: event.target.value })} />
                </label>
                <label>
                  适用平台
                  <select value={dmTemplateForm.platform} onChange={(event) => setDmTemplateForm({ ...dmTemplateForm, platform: event.target.value })}>
                    <option>通用</option>
                    <option>美团</option>
                    <option>饿了么</option>
                    <option>抖音</option>
                  </select>
                </label>
                <label className="wide">
                  私信内容
                  <textarea
                    value={dmTemplateForm.content}
                    onChange={(event) => setDmTemplateForm({ ...dmTemplateForm, content: event.target.value })}
                  />
                </label>
                <button className="primary-button" type="submit">
                  <CheckCircle2 size={16} />
                  保存模板
                </button>
              </form>
            </article>

            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Library</p>
                  <h2>模板库</h2>
                </div>
                <ClipboardList size={22} />
              </div>
              <div className="template-list">
                {dmTemplates.map((template) => (
                  <article className="template-card" key={template.id}>
                    <div>
                      <strong>{template.name}</strong>
                      <span>{template.platform}</span>
                    </div>
                    <p>{template.content}</p>
                    <small>{template.isActive ? "启用中" : "停用"}</small>
                  </article>
                ))}
              </div>
            </article>
          </section>
        )}

        {showConversations && (
          <section className="content-grid lower">
            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Records</p>
                  <h2>私信会话记录</h2>
                </div>
                <ClipboardList size={22} />
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>商家</th>
                      <th>平台</th>
                      <th>状态</th>
                      <th>意向</th>
                      <th>最后消息</th>
                      <th>动作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dmConversations.length === 0 && (
                      <tr>
                        <td colSpan={6}>
                          <span className="empty-state">暂无私信会话。</span>
                        </td>
                      </tr>
                    )}
                    {dmConversations.map((conversation) => (
                      <tr key={conversation.id}>
                        <td>
                          <strong>{conversation.merchantName}</strong>
                          <small>{conversation.lastMessageAt ? new Date(conversation.lastMessageAt).toLocaleString() : "未回复"}</small>
                        </td>
                        <td>{conversation.platform}</td>
                        <td>{conversation.status}</td>
                        <td>
                          <span className={`intent-pill intent-${conversation.intentLevel.toLowerCase()}`}>{conversation.intentLevel}</span>
                        </td>
                        <td>{conversation.lastMessage}</td>
                        <td>{conversation.needHandoff ? "人工接管" : "自动跟进"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          </section>
        )}
      </>
    );
  }

  const primaryActionLabel =
    activeModule === "intent"
      ? "分配销售"
      : activeModule === "voice"
        ? "新增档案"
        : activeModule === "dm"
          ? "新建私信"
          : activeModule === "reports"
            ? "导出数据"
            : activeModule === "settings"
              ? "保存配置"
              : "新建任务";

  function runPrimaryAction() {
    if (activeModule === "dm") {
      setActiveDmTab("任务列表");
      return;
    }
    if (activeModule === "intent") {
      setActiveIntentTab("跟进工单");
      return;
    }
    if (activeModule === "voice") {
      setActiveVoiceTab("声音档案");
      return;
    }
    if (activeModule === "reports") {
      void createReportExport();
      return;
    }
    if (activeModule === "settings") {
      settingsEditorRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      void saveSelectedSetting();
      return;
    }
    setActiveModule("outbound");
    setActiveOutboundTab("任务列表");
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Sparkles size={20} />
          </span>
          <div>
            <strong>商家AI获客</strong>
            <small>视频号团购客户端</small>
          </div>
        </div>

        <nav className="nav-list" aria-label="功能模块">
          {modules.map((module, index) => {
            const Icon = icons[index] ?? ClipboardList;
            return (
              <button
                className={module.key === activeModule ? "nav-item is-active" : "nav-item"}
                key={module.key}
                onClick={() => setActiveModule(module.key)}
                type="button"
              >
                <Icon size={18} />
                <span>
                  <strong>{module.name}</strong>
                  <small>{module.description.split("，")[0]}</small>
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p>当前租户：南昌本地生活招商 · {apiStatus}</p>
            <h1>{active?.name ?? "实时工作台"}</h1>
          </div>
          <div className="topbar-actions">
            <label className="search-box">
              <Search size={17} />
              <input placeholder="搜索商家、任务或客户" />
            </label>
            <button className="secondary-button icon-only" onClick={loadData} type="button" title="刷新数据">
              <RefreshCw size={18} className={isLoading ? "spin" : ""} />
            </button>
            <button
              className="primary-button"
              onClick={runPrimaryAction}
              type="button"
            >
              <Plus size={16} />
              {primaryActionLabel}
            </button>
          </div>
        </header>

        {activeModule === "outbound" ? (
          renderOutboundWorkspace()
        ) : activeModule === "dm" ? (
          renderDmWorkspace()
        ) : activeModule === "intent" ? (
          renderIntentWorkspace()
        ) : activeModule === "voice" ? (
          renderVoiceWorkspace()
        ) : activeModule === "reports" ? (
          renderReportsWorkspace()
        ) : activeModule === "settings" ? (
          renderSettingsWorkspace()
        ) : (
          <>
            <section className="metrics">
              <MetricCard label="模块页面" value={modules.reduce((sum, module) => sum + module.pageCount, 0)} detail="UI 原型覆盖范围" />
              <MetricCard label="商家线索" value={leads.length} detail="可接入采集、导入、去重" />
              <MetricCard label="触达任务" value={tasks.length} detail="外呼、私信、采集任务" />
              <MetricCard label="当前模块" value={active?.pageCount ?? 0} detail={active?.description} />
            </section>
            {renderDefaultWorkspace()}
          </>
        )}
      </section>
    </main>
  );
}

function MetricCard({
  icon,
  label,
  value,
  detail,
  tone = "blue",
}: {
  icon?: React.ReactNode;
  label: string;
  value: string | number;
  detail?: string;
  tone?: "blue" | "green" | "amber" | "rose";
}) {
  return (
    <article className="metric-card">
      {icon && <span className={`metric-icon tone-${tone}`}>{icon}</span>}
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        {detail && <small>{detail}</small>}
      </div>
    </article>
  );
}

function LeadTable({
  leads,
  selectable,
  selectedLeadIds,
  onToggleLead,
}: {
  leads: Lead[];
  selectable: boolean;
  selectedLeadIds: string[];
  onToggleLead: (leadId: string) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {selectable && <th>选择</th>}
            <th>商家</th>
            <th>城市</th>
            <th>平台</th>
            <th>意向</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {leads.length === 0 && (
            <tr>
              <td colSpan={selectable ? 6 : 5}>
                <span className="empty-state">暂无线索，先新增一条商家线索。</span>
              </td>
            </tr>
          )}
          {leads.map((lead) => (
            <tr key={lead.id}>
              {selectable && (
                <td>
                  <input
                    checked={selectedLeadIds.includes(lead.id)}
                    onChange={() => onToggleLead(lead.id)}
                    type="checkbox"
                  />
                </td>
              )}
              <td>
                <strong>{lead.name}</strong>
                <small>{lead.category}</small>
              </td>
              <td>{lead.city}</td>
              <td>{lead.platform}</td>
              <td>{lead.intentScore}</td>
              <td>
                <span className="badge">{lead.status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TaskList({
  tasks,
  onStart,
  startableChannel = "call",
}: {
  tasks: OutreachTask[];
  onStart: (taskId: string) => void;
  startableChannel?: OutreachTask["channel"];
}) {
  return (
    <div className="task-list">
      {tasks.length === 0 && <div className="empty-state">暂无任务，先创建一个外呼或私信任务。</div>}
      {tasks.map((task) => (
        <div className="task-row" key={task.id}>
          <span>{task.channel === "call" ? "外呼" : task.channel === "dm" ? "私信" : "采集"}</span>
          <div>
            <strong>{task.name}</strong>
            <small>
              {task.completedCount}/{task.targetCount} · 接通 {task.connectedCount} · 意向 {task.intentCount}
            </small>
          </div>
          <em>{task.status}</em>
          {task.channel === startableChannel && (
            <button className="row-action" onClick={() => onStart(task.id)} type="button">
              启动
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

export default App;
