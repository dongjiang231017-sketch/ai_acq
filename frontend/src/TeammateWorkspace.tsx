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
  AuthUser,
  CallRecord,
  CallScript,
  ChannelReport,
  BrowserDmAction,
  BrowserCapturedComment,
  CommentAutomationQueueItem,
  CommentAutomationQueueOverview,
  CommentConvertResult,
  CommentInterceptOverview,
  CommentInterceptSource,
  CommentSyncResult,
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
  LeadCollectionRun,
  LeadCollectionTask,
  ModuleSummary,
  OutboundOverview,
  OutreachTask,
  RawLeadRecord,
  RecallRule,
  ReportExport,
  ReportOverview,
  RealtimeLiveEvents,
  RealtimePipeline,
  RealtimeSession,
  RealtimeVoiceSelection,
  SalesPerformanceReport,
  SocialComment,
  SystemVoice,
  TelephonyConfig,
  TelephonyHealth,
  TelephonyLineRecovery,
  TelephonyPreflight,
  TelephonyTestCallResult,
  VoiceGatewayProfile,
  VoiceCloneRecord,
  VoiceOverview,
  VoiceProfile,
  VoiceProviderStatus,
  VoiceSample,
  VoiceTrainingJob,
  VoiceUsageRecord,
  SettingsOverview,
  SystemSetting,
  API_BASE_URL,
  api,
  apiAssetUrl,
  clearStoredAuth,
  readStoredAuth,
  storeAuth,
} from "./lib/api";

const icons = [BarChart3, Search, Database, PhoneCall, MessageSquareText, Users, Headphones, ClipboardList, Settings];
const customerHiddenModuleKeys = new Set(["learning"]);
const customerVisibleModules = (items: ModuleSummary[]) => items.filter((module) => !customerHiddenModuleKeys.has(module.key));

const fallbackModules: ModuleSummary[] = [
  { key: "dashboard", name: "实时工作台", description: "监控今日获客、外呼、私信和预警。", pageCount: 4, status: "ready" },
  { key: "collector", name: "线索采集", description: "采集任务、来源配置、清洗规则。", pageCount: 5, status: "ready" },
  { key: "leads", name: "商家线索库", description: "商家资料、电话库、主页和去重审核。", pageCount: 5, status: "ready" },
  { key: "outbound", name: "AI外呼系统", description: "外呼任务、话术流程、通话记录。", pageCount: 6, status: "ready" },
  { key: "dm", name: "平台私信系统", description: "平台个人号、评论截流、私信任务和会话。", pageCount: 8, status: "ready" },
  { key: "intent", name: "意向客户池", description: "客户分级、工单跟进和分配规则。", pageCount: 4, status: "ready" },
  { key: "voice", name: "声音档案", description: "授权、音色复刻和使用记录。", pageCount: 4, status: "ready" },
  { key: "reports", name: "数据报表", description: "渠道、绩效和导出中心。", pageCount: 4, status: "ready" },
  { key: "settings", name: "系统设置", description: "线路、账号和合规保护。", pageCount: 4, status: "ready" },
];

function mergeCustomerModules(items: ModuleSummary[]) {
  const merged = new Map<string, ModuleSummary>();
  fallbackModules.forEach((module) => merged.set(module.key, module));
  customerVisibleModules(items).forEach((module) => merged.set(module.key, module));
  const preferredOrder = fallbackModules.map((module) => module.key);
  const ordered = preferredOrder
    .map((key) => merged.get(key))
    .filter((module): module is ModuleSummary => Boolean(module));
  merged.forEach((module) => {
    if (!ordered.some((item) => item.key === module.key)) {
      ordered.push(module);
    }
  });
  return ordered;
}

type DmLoginWebviewElement = HTMLElement & {
  getWebContentsId?: () => number;
  isLoading?: () => boolean;
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

const fallbackCollectionTasks: LeadCollectionTask[] = [];
const fallbackCollectionRuns: LeadCollectionRun[] = [];
const fallbackRawLeadRecords: RawLeadRecord[] = [];

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

const fallbackVoiceGatewayProfile: VoiceGatewayProfile = {
  key: "uc100_sip_volte",
  label: "语音网关（UC100 测试档案）",
  vendor: "ZHY",
  model: "UC100",
  category: "sip_volte_gateway",
  transport: "sip_udp_server_registered",
  host: "",
  sipPort: 5060,
  trunkName: "uc100",
  maxChannels: 1,
  lineType: "sim_volte",
  adminUrl: "",
  discoveryMode: "gateway_registers_to_server",
  tested: false,
  capabilities: ["sip_registration_to_server", "single_sim", "asterisk_audiosocket"],
  notes: ["让 UC100 主动注册到云端 Asterisk；客户电脑不需要本机 Asterisk。"],
};

const fallbackTelephonyConfig: TelephonyConfig = {
  gatewayMode: "simulator",
  asteriskDeploymentMode: "server",
  voiceGatewayProfile: fallbackVoiceGatewayProfile,
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
  asteriskDeploymentMode: "server",
  voiceGatewayProfile: fallbackVoiceGatewayProfile,
  configured: false,
  liveCallEnabled: false,
  bulkCallEnabled: false,
  amiReachable: false,
  authenticated: false,
  pingOk: false,
  trunkConfigured: false,
  trunkReachable: null,
  trunkStatus: "待配置",
  maxChannels: 8,
  readyForTestCall: false,
  errors: ["Asterisk AMI 账号或密码未配置"],
};

const fallbackTelephonyPreflight: TelephonyPreflight = {
  checkedAt: fallbackTelephonyHealth.checkedAt,
  voiceGatewayProfile: fallbackVoiceGatewayProfile,
  readyForDeviceTest: false,
  readyForSingleNumberTest: false,
  readyForBulkTasks: false,
  nextStep: "先配置 AMI 账号、语音网关 trunk，并切到 Asterisk 真实线路模式。",
  health: fallbackTelephonyHealth,
  steps: [
    {
      key: "gateway_mode",
      label: "网关模式",
      status: "warn",
      detail: "当前仍是模拟线路，代码不会访问语音网关。",
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

const fallbackRealtimePipeline: RealtimePipeline = {
  mode: "half_duplex_interruptible",
  bridgeMode: "mock_media",
  targetLatencyMs: 1500,
  estimatedLatencyMs: 1380,
  estimatedAiCostPerMinute: 0.04,
  readyForMockCall: true,
  readyForAsteriskMedia: false,
  nextStep: "先用模拟通话验证 ASR/意图/LLM/TTS/打断；设备识卡后再接 Asterisk 媒体桥。",
  routeOptions: [
    {
      key: "omni",
      label: "极速人声 Omni",
      mode: "omni_realtime_interruptible",
      summary: "端到端实时语音，适合追求自然衔接和低延迟。",
      estimatedLatencyMs: 720,
      estimatedAiCostPerMinute: 0.09,
      readyForAsteriskMedia: false,
      isActive: false,
    },
    {
      key: "pipeline",
      label: "低成本分段 Pipeline",
      mode: "half_duplex_interruptible",
      summary: "ASR、语义路由/LLM、流式 TTS 分段执行，适合成本敏感场景。",
      estimatedLatencyMs: 1055,
      estimatedAiCostPerMinute: 0.04,
      readyForAsteriskMedia: false,
      isActive: true,
    },
  ],
  steps: [
    {
      key: "media_bridge",
      label: "语音网关/Asterisk 媒体桥",
      status: "warn",
      provider: "mock_media",
      latencyMs: 120,
      detail: "当前使用模拟媒体入口。",
    },
    {
      key: "asr",
      label: "流式 ASR",
      status: "pass",
      provider: "Paraformer realtime adapter",
      latencyMs: 380,
      detail: "按 WebSocket 流式输入设计。",
    },
    {
      key: "router",
      label: "快速意图路由",
      status: "pass",
      provider: "local intent rules",
      latencyMs: 50,
      detail: "高频意图先走规则。",
    },
    {
      key: "llm",
      label: "LLM 生成",
      status: "pass",
      provider: "DeepSeek-V4-Flash adapter",
      latencyMs: 320,
      detail: "短句优先，复杂问题再调用 LLM。",
    },
    {
      key: "tts",
      label: "流式 TTS",
      status: "pass",
      provider: "声音档案 voice router",
      latencyMs: 430,
      detail: "音色由客户在声音档案选择，按首个可播放音频块估算。",
    },
    {
      key: "barge_in",
      label: "打断处理",
      status: "pass",
      provider: "VAD + playback queue cancel",
      latencyMs: 80,
      detail: "客户插话时停止当前播放。",
    },
  ],
};

const fallbackRealtimeLiveEvents: RealtimeLiveEvents = {
  logPath: "/tmp/ai-acq-realtime-call-events.jsonl",
  hasEvents: false,
  latestAt: null,
  score: null,
  events: [],
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

type CallScriptDraft = Omit<CallScript, "id" | "createdAt">;
type RecallRuleDraft = Omit<RecallRule, "id">;
type MonitorMessage = {
  speaker: "ai" | "customer" | "system";
  label: string;
  text: string;
};

function scriptDraftFrom(script?: CallScript | null): CallScriptDraft {
  return {
    name: script?.name ?? "视频号团购商家邀约话术",
    opening: script?.opening ?? "",
    qualification: script?.qualification ?? "",
    objection: script?.objection ?? "",
    closing: script?.closing ?? "",
    isActive: script?.isActive ?? true,
  };
}

function persistedScriptId(script?: CallScript | null) {
  if (!script?.id || script.id.startsWith("script_")) return null;
  return script.id;
}

function recallRuleDraftFrom(rule?: RecallRule | null): RecallRuleDraft {
  return {
    name: rule?.name ?? "默认重拨规则",
    noAnswerIntervalMinutes: rule?.noAnswerIntervalMinutes ?? 240,
    busyIntervalMinutes: rule?.busyIntervalMinutes ?? 120,
    maxAttempts: rule?.maxAttempts ?? 3,
    quietStart: rule?.quietStart ?? "21:00",
    quietEnd: rule?.quietEnd ?? "09:00",
    enabled: rule?.enabled ?? true,
  };
}

function transcriptToMonitorMessages(record?: CallRecord | null): MonitorMessage[] {
  if (!record) return [];
  const lines = record.transcript
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  const messages = lines.map((line, index) => {
    const customerMatch = /^(客户|商家|用户|Customer|User)[:：]\s*(.+)$/i.exec(line);
    if (customerMatch) return { speaker: "customer" as const, label: "客户", text: customerMatch[2] };
    const aiMatch = /^(AI|坐席|系统|Agent)[:：]\s*(.+)$/i.exec(line);
    if (aiMatch) return { speaker: "ai" as const, label: "AI", text: aiMatch[2] };
    return {
      speaker: index % 2 === 0 ? ("ai" as const) : ("customer" as const),
      label: index % 2 === 0 ? "AI" : "客户",
      text: line,
    };
  });
  if (messages.length > 0) return messages;
  return [
    {
      speaker: "system",
      label: "监听",
      text: record.outcome ? `${record.outcome}，等待实时转写同步。` : "等待实时通话开始。",
    },
  ];
}

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

const fallbackCommentInterceptOverview: CommentInterceptOverview = {
  sources: 0,
  comments: 0,
  highIntentComments: 0,
  convertedLeads: 0,
};

const fallbackCommentAutomationQueue: CommentAutomationQueueOverview = {
  items: [],
  dueCount: 0,
  readyCount: 0,
  pausedCount: 0,
  blockedCount: 0,
  message: "自动化队列尚未加载。",
};

const fallbackCommentSources: CommentInterceptSource[] = [];
const fallbackSocialComments: SocialComment[] = [];

const platformLoginUrls: Record<string, string> = {
  美团: "https://passport.meituan.com/account/unitivelogin",
  饿了么: "https://h5.ele.me/login/",
  抖音: "https://www.douyin.com/",
  视频号: "https://channels.weixin.qq.com/",
};

const supportedDmPlatforms = ["美团", "饿了么", "抖音"] as const;
const loginCapablePlatforms = ["美团", "饿了么", "抖音", "视频号"] as const;
const commentCapturePlatforms = ["抖音", "视频号"] as const;
const unsupportedDmPlatformTips: Record<string, string> = {
  视频号: "视频号助手当前不支持主动私信商家，可改用外呼或其他合规触达方式。",
};

const defaultCommentSelectorDraft = {
  riskCheckSelector: "",
  messageButtonSelector: "",
  inputSelector: "",
  sendButtonSelector: "",
  sentSuccessSelector: "",
};

function isSupportedDmPlatform(platform: string) {
  return supportedDmPlatforms.includes(platform as (typeof supportedDmPlatforms)[number]);
}

function isLoginCapablePlatform(platform: string) {
  return loginCapablePlatforms.includes(platform as (typeof loginCapablePlatforms)[number]);
}

function isCommentCapturePlatform(platform: string) {
  return commentCapturePlatforms.includes(platform as (typeof commentCapturePlatforms)[number]);
}

function isSupportedDmAccount(account: DmAccount) {
  return isSupportedDmPlatform(account.platform) && account.status !== "不支持私信";
}

function isLoginCapableAccount(account: DmAccount) {
  return isLoginCapablePlatform(account.platform);
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

function selectorDraftFromConfig(config?: DmPlatformConfig | null) {
  return {
    riskCheckSelector: config?.riskCheckSelector ?? "",
    messageButtonSelector: config?.messageButtonSelector ?? "",
    inputSelector: config?.inputSelector ?? "",
    sendButtonSelector: config?.sendButtonSelector ?? "",
    sentSuccessSelector: config?.sentSuccessSelector ?? "",
  };
}

function commentAutomationStatusText(status: string) {
  if (status === "ready") return "可执行";
  if (status === "waiting") return "等待";
  if (status === "paused") return "已暂停";
  if (status === "blocked") return "阻塞";
  return status || "未知";
}

function compactDateTime(value?: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "现在";
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
const dmTabs = ["私信总览", "评论截流", "任务列表", "账号管理", "轮换规则", "消息模板", "会话记录", "回复监听"] as const;
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
  if (setting.groupKey === "telephony" && setting.itemKey === "asterisk_deployment_mode") {
    return value === "server" ? "服务器托管" : "客户端内置";
  }
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
  if (health.trunkReachable === false) return "语音网关未注册";
  if (health.amiReachable && health.authenticated) return "AMI 已连接";
  return "待配置";
}

function apiServerHostLabel() {
  try {
    const url = new URL(API_BASE_URL);
    if (["127.0.0.1", "localhost", "0.0.0.0"].includes(url.hostname)) return "服务器公网IP";
    return url.hostname;
  } catch {
    return "服务器公网IP";
  }
}

function serverSipRegistrationTarget(config: TelephonyConfig) {
  const sipPort = config.voiceGatewayProfile.sipPort || 5060;
  return `${apiServerHostLabel()}:${sipPort}`;
}

function serverAmiDisplay(config: TelephonyConfig) {
  const host = config.asteriskHost || "127.0.0.1";
  const port = config.asteriskAmiPort || 5038;
  if (["127.0.0.1", "localhost", "0.0.0.0"].includes(host)) return `后端本机:${port}`;
  return `${host}:${port}`;
}

function telephonyReadinessDetail(config: TelephonyConfig, health: TelephonyHealth) {
  if (config.gatewayMode !== "asterisk") return "当前仍为模拟线路";
  if (!health.configured) return "请先配置 AMI 账号和密码";
  if (!health.amiReachable) return "后端还连不上 Asterisk AMI";
  if (!health.pingOk) return "AMI Ping 未通过";
  if (health.trunkReachable === false) return "服务器已连上 Asterisk，但没有收到 UC100 SIP 注册";
  if (!health.liveCallEnabled) return "单号试拨开关未开启";
  return health.trunkStatus || "语音网关线路待测试";
}

function routeHealthSummary(health: TelephonyHealth, preflight: TelephonyPreflight) {
  const isReady = preflight.readyForSingleNumberTest || preflight.readyForBulkTasks || health.readyForTestCall;
  const isLinked = Boolean(health.authenticated && health.trunkReachable);
  const isPartial = Boolean(health.amiReachable || health.authenticated || preflight.readyForDeviceTest);
  const status = isReady || isLinked ? "pass" : isPartial ? "warn" : "fail";
  const trunkMissing = health.trunkReachable === false;
  const title = status === "pass" ? "线路通畅" : trunkMissing ? "语音网关未注册" : status === "warn" ? "线路待联通" : "线路不可用";
  const detail =
    status === "pass"
      ? "后台线路检测通过，可以按配置执行外呼任务。"
      : trunkMissing
        ? "服务器 Asterisk/AMI 正常，但公网 SIP 注册还没有到达服务器。"
      : status === "warn"
        ? "后台正在接入线路，完成后会自动更新状态。"
        : "后台线路未接入，请等待管理员处理。";
  const action = status === "pass" ? "可以创建任务" : trunkMissing ? "等待设备注册" : status === "warn" ? "后台验收中" : "等待后台接入";
  return { status, title, detail, action };
}

function asteriskSidecarStatusText(status?: AiAcqDesktopAsteriskStatus | null) {
  if (!status) return "待检测";
  if (status.running && status.status === "running") return "已运行";
  if (status.status === "starting") return "启动中";
  if (status.runtimeFound) return "可启动";
  return "缺少运行时";
}

function asteriskSidecarBadgeStatus(status?: AiAcqDesktopAsteriskStatus | null) {
  if (!status) return "warn";
  if (status.running && status.status === "running") return "pass";
  if (!status.runtimeFound) return "fail";
  return "warn";
}

function asteriskCustomerDeliveryStatus(status?: AiAcqDesktopAsteriskStatus | null) {
  const deliveryStatus = status?.customerDelivery?.status;
  if (deliveryStatus === "pass" || deliveryStatus === "warn" || deliveryStatus === "fail") return deliveryStatus;
  return asteriskSidecarBadgeStatus(status);
}

function telephonyPreflightStatusText(status: string) {
  if (status === "pass") return "PASS";
  if (status === "fail") return "FAIL";
  return "WARN";
}

function telephonyDiagnosticStatusText(status: string) {
  if (status === "pass") return "通过";
  if (status === "fail") return "故障";
  return "待确认";
}

function telephonyPreflightSummary(preflight: TelephonyPreflight) {
  if (preflight.readyForBulkTasks) return "真实批量外呼已开放";
  if (preflight.readyForSingleNumberTest) return "可做单号试拨";
  if (preflight.readyForDeviceTest) return "设备链路可联调";
  return "等待配置";
}

function voiceGatewayDiscoveryLabel(status?: AiAcqDesktopAsteriskStatus | null) {
  const discovery = status?.voiceGatewayDiscovery;
  if (!status) return "等待检测";
  if (discovery?.status === "current") return "已发现当前设备";
  if (discovery?.status === "updated") return "已自动切换设备";
  if (discovery?.status === "not_found") return "未发现设备";
  if (discovery?.status === "disabled") return "自动检测已关闭";
  return "检测中";
}

function voiceGatewayDiscoveryDetail(status?: AiAcqDesktopAsteriskStatus | null) {
  const discovery = status?.voiceGatewayDiscovery;
  if (discovery?.message) return discovery.message;
  if (!status) return "打开桌面客户端后会检测客户现场局域网里的语音网关。";
  return status.nextStep || "请确认设备已通电、插卡、接入网络。";
}

function telephonyTestPayloadSummary(result: TelephonyTestCallResult | null) {
  if (!result?.rawPayload) return "";
  try {
    const payload = JSON.parse(result.rawPayload) as { events?: Array<Record<string, string>> };
    const events = Array.isArray(payload.events) ? payload.events : [];
    const compact = events
      .map((event) => [event.Event, event.DialStatus, event.Cause, event["Cause-txt"], event.TechCause, event.Reason].filter(Boolean).join("/"))
      .filter(Boolean)
      .slice(-4);
    return compact.length ? compact.join(" -> ") : "";
  } catch {
    return "";
  }
}

function telephonyVerificationStageText(result: TelephonyTestCallResult) {
  if (result.verificationStage === "realtime_conversation_confirmed") return "真人实时对话已验收";
  if (result.verificationStage === "realtime_media_confirmed") return "线路与实时媒体已验收";
  if (result.verificationStage === "gateway_signaling_only") return "网关侧响应，未证明手机响铃";
  if (result.verificationStage === "cellular_answered_no_media_proof") return "线路接通，待媒体链路验收";
  if (result.verificationStage === "originate_submitted") return "已提交拨号，待线路证据";
  return "未达到真实通话验收";
}

function telephonyVerificationSummary(result: TelephonyTestCallResult) {
  if (result.conversationConfirmed) return "已达到真人实时对话验收";
  if (result.callScreeningDetected && !result.humanSpeechConfirmed) return "检测到电话助理/秘书，还未确认真人接听。";
  if (result.mediaLoopConfirmed && !result.humanSpeechConfirmed) return "媒体桥已接通，但还没识别到真人客户语音。";
  if (result.humanSpeechConfirmed && !result.aiSpeechConfirmed) return "已识别真人语音，AI 首句还未确认播出。";
  return result.acceptanceNote || "还需要语音网关线路侧、手机接听和实时媒体日志共同确认。";
}

function realtimePipelineStatusText(status: string) {
  if (status === "pass") return "PASS";
  if (status === "fail") return "FAIL";
  return "WARN";
}

function realtimeSessionStatusText(status: string) {
  if (status === "speaking") return "AI 播放中";
  if (status === "thinking") return "生成回复中";
  if (status === "listening") return "监听客户";
  return status;
}

function realtimeLiveEventTitle(type: string) {
  if (type === "call_connected") return "电话接通";
  if (type === "remote_speech_started") return "听到对端声音";
  if (type === "human_speech_confirmed") return "真人已说话";
  if (type === "call_screening_detected") return "电话助理";
  if (type === "system_prompt_ignored") return "系统提示已忽略";
  if (type === "audio_capture_started") return "开始录音证据";
  if (type === "audio_capture_saved") return "录音证据已保存";
  if (type === "asr_final") return "客户语音";
  if (type === "llm_reply") return "AI 回复";
  if (type === "tts_start") return "开始播放";
  if (type === "tts_interrupted") return "播放打断";
  if (type === "tts_done") return "播放完成";
  if (type === "barge_in") return "客户插话";
  if (type === "barge_recovery_ready") return "恢复监听";
  if (type === "barge_turn_committed") return "打断兜底回复";
  if (type === "barge_transcription_replaces_forced_response") return "转写接管回复";
  if (type === "barge_transcription_after_forced_response") return "打断转写已记录";
  if (type === "omni_input_buffer_event") return "语音缓冲";
  if (type === "omni_no_audio_response") return "无音频兜底";
  if (type === "omni_unavailable") return "实时模型断开";
  if (type === "call_disconnected") return "电话结束";
  return type;
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

function TeammateWorkspace() {
  const [auth, setAuth] = useState(() => readStoredAuth());
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(auth?.user ?? null);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authMessage, setAuthMessage] = useState("");
  const [isSubmittingAuth, setIsSubmittingAuth] = useState(false);
  const [loginForm, setLoginForm] = useState({ identifier: "", password: "" });
  const [registrationForm, setRegistrationForm] = useState({
    projectName: "",
    companyName: "",
    contactName: "",
    contactPhone: "",
    contactEmail: "",
    desiredUsername: "",
    note: "",
  });
  const [modules, setModules] = useState<ModuleSummary[]>(fallbackModules);
  const [leads, setLeads] = useState<Lead[]>(fallbackLeads);
  const [collectionTasks, setCollectionTasks] = useState<LeadCollectionTask[]>(fallbackCollectionTasks);
  const [collectionRuns, setCollectionRuns] = useState<LeadCollectionRun[]>(fallbackCollectionRuns);
  const [rawLeadRecords, setRawLeadRecords] = useState<RawLeadRecord[]>(fallbackRawLeadRecords);
  const [tasks, setTasks] = useState<OutreachTask[]>(fallbackTasks);
  const [overview, setOverview] = useState<OutboundOverview>(fallbackOverview);
  const [telephonyConfig, setTelephonyConfig] = useState<TelephonyConfig>(fallbackTelephonyConfig);
  const [telephonyHealth, setTelephonyHealth] = useState<TelephonyHealth>(fallbackTelephonyHealth);
  const [telephonyPreflight, setTelephonyPreflight] = useState<TelephonyPreflight>(fallbackTelephonyPreflight);
  const [realtimePipeline, setRealtimePipeline] = useState<RealtimePipeline>(fallbackRealtimePipeline);
  const [realtimeLiveEvents, setRealtimeLiveEvents] = useState<RealtimeLiveEvents>(fallbackRealtimeLiveEvents);
  const [realtimeSession, setRealtimeSession] = useState<RealtimeSession | null>(null);
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
  const [commentInterceptOverview, setCommentInterceptOverview] =
    useState<CommentInterceptOverview>(fallbackCommentInterceptOverview);
  const [commentSources, setCommentSources] = useState<CommentInterceptSource[]>(fallbackCommentSources);
  const [socialComments, setSocialComments] = useState<SocialComment[]>(fallbackSocialComments);
  const [selectedCommentIds, setSelectedCommentIds] = useState<string[]>(
    fallbackSocialComments.filter((comment) => ["A", "B"].includes(comment.intentLevel)).map((comment) => comment.id),
  );
  const [commentInterceptMessage, setCommentInterceptMessage] = useState(
    "在桌面客户端打开抖音/视频号内置登录页，进入目标视频或主页后采集当前页评论；不会生成模拟评论。",
  );
  const [isSyncingComments, setIsSyncingComments] = useState(false);
  const [isCapturingBrowserComments, setIsCapturingBrowserComments] = useState(false);
  const [isRunningCommentAutomation, setIsRunningCommentAutomation] = useState(false);
  const [lastCommentAutomationResult, setLastCommentAutomationResult] = useState<AiAcqDesktopCommentAutomationResult | null>(null);
  const [commentAutomationQueue, setCommentAutomationQueue] =
    useState<CommentAutomationQueueOverview>(fallbackCommentAutomationQueue);
  const [isLoadingCommentAutomationQueue, setIsLoadingCommentAutomationQueue] = useState(false);
  const [isDispatchingCommentQueue, setIsDispatchingCommentQueue] = useState(false);
  const [isCommentSchedulerEnabled, setIsCommentSchedulerEnabled] = useState(false);
  const [commentSchedulerIntervalMinutes, setCommentSchedulerIntervalMinutes] = useState(10);
  const [commentSelectorDraft, setCommentSelectorDraft] = useState(defaultCommentSelectorDraft);
  const [isSavingCommentSelectors, setIsSavingCommentSelectors] = useState(false);
  const [isConvertingComments, setIsConvertingComments] = useState(false);
  const [lastCommentConvertResult, setLastCommentConvertResult] = useState<CommentConvertResult | null>(null);
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
  const [activeOutboundTab, setActiveOutboundTab] = useState<OutboundTab>("外呼总览");
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
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([]);
  const [selectedDmLeadIds, setSelectedDmLeadIds] = useState<string[]>([]);
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
  const [collectionForm, setCollectionForm] = useState({
    name: "本地商家地图采集",
    provider: "amap",
    cities: "南昌",
    categories: "餐饮",
    keywords: "团购",
    targetPerKeyword: 10,
    remark: "",
  });
  const [collectionMessage, setCollectionMessage] = useState("地图采集密钥由服务端配置，客户端只发起任务和查看结果。");
  const [isCreatingCollectionTask, setIsCreatingCollectionTask] = useState(false);
  const [runningCollectionTaskId, setRunningCollectionTaskId] = useState<string | null>(null);
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
  const [outboundTaskMessage, setOutboundTaskMessage] = useState("选择线索后创建任务，再从任务列表启动。");
  const [scriptDraft, setScriptDraft] = useState<CallScriptDraft>(() => scriptDraftFrom(fallbackScripts[0]));
  const [scriptMessage, setScriptMessage] = useState("客户可直接改话术，保存后新外呼任务会使用当前启用话术。");
  const [isSavingScript, setIsSavingScript] = useState(false);
  const [isGeneratingScript, setIsGeneratingScript] = useState(false);
  const [ruleDraft, setRuleDraft] = useState<RecallRuleDraft>(() => recallRuleDraftFrom(fallbackRules[0]));
  const [ruleMessage, setRuleMessage] = useState("未接、忙线和静默时段由客户自行调整。");
  const [isSavingRule, setIsSavingRule] = useState(false);
  const [selectedLiveCallId, setSelectedLiveCallId] = useState(fallbackRecords[0]?.id ?? "");
  const [telephonyTestForm, setTelephonyTestForm] = useState({
    phone: "",
    callerId: "",
  });
  const [telephonyTestResult, setTelephonyTestResult] = useState<TelephonyTestCallResult | null>(null);
  const [telephonyLineRecovery, setTelephonyLineRecovery] = useState<TelephonyLineRecovery | null>(null);
  const [telephonyMessage, setTelephonyMessage] = useState("先检查线路，确认语音网关/Asterisk 可用后再做单号试拨。");
  const [isCheckingTelephony, setIsCheckingTelephony] = useState(false);
  const [isTestingTelephony, setIsTestingTelephony] = useState(false);
  const [isRecoveringTelephony, setIsRecoveringTelephony] = useState(false);
  const [realtimeForm, setRealtimeForm] = useState({
    merchantName: "模拟火锅店",
    phone: "",
    conversationRoute: "omni" as "pipeline" | "omni",
    voiceChoice: `system:${fallbackSystemVoices[0]?.id ?? "qwen_tts_ethan"}`,
    customerText: "你们这个怎么收费？",
  });
  const [realtimeMessage, setRealtimeMessage] = useState("先用模拟通话验证实时 ASR、意图、TTS 和打断。");
  const [realtimeLastReply, setRealtimeLastReply] = useState("");
  const [isStartingRealtimeSession, setIsStartingRealtimeSession] = useState(false);
  const [isSendingRealtimeUtterance, setIsSendingRealtimeUtterance] = useState(false);
  const [isRefreshingRealtimeEvents, setIsRefreshingRealtimeEvents] = useState(false);
  const [dmForm, setDmForm] = useState({
    name: "美团高意向商家首轮私信",
    platform: "美团",
    templateId: "",
    scheduledAt: "",
  });
  const [dmTaskMessage, setDmTaskMessage] = useState("");
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
  const [commentSourceForm, setCommentSourceForm] = useState({
    platform: "抖音",
    sourceType: "视频链接",
    name: "抖音高意向评论截流",
    keyword: "南昌 团购 入驻",
    videoUrl: "",
    videoTitle: "",
    syncFrequencyMinutes: 120,
    keywordRules: "合作,价格,报名,入驻,求资料,想了解,加我",
  });
  const [commentAutomationForm, setCommentAutomationForm] = useState({
    scrollRounds: 6,
    maxAuthors: 3,
    sendIntervalSeconds: 45,
    dmMessage: "您好，看到您在评论区关注本地生活团购获客，想和您沟通一个本地商家增长方案，可以交流一下吗？",
    allowLiveSend: false,
  });
  const [dmLoginSession, setDmLoginSession] = useState<DmLoginSession | null>(null);
  const [dmLoginMessage, setDmLoginMessage] = useState("");
  const [dmLoginEntryReady, setDmLoginEntryReady] = useState(false);
  const [isPreparingDmLogin, setIsPreparingDmLogin] = useState(false);
  const [isCheckingDmLogin, setIsCheckingDmLogin] = useState(false);
  const [checkingDmAccountId, setCheckingDmAccountId] = useState<string | null>(null);
  const [isDesktopClient, setIsDesktopClient] = useState(false);
  const [asteriskSidecarStatus, setAsteriskSidecarStatus] = useState<AiAcqDesktopAsteriskStatus | null>(null);
  const [isStartingAsteriskSidecar, setIsStartingAsteriskSidecar] = useState(false);
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
  const callableLeadIds = useMemo(() => callableLeads.map((lead) => lead.id), [callableLeads]);
  const selectedCallableLeadIds = useMemo(
    () => selectedLeadIds.filter((leadId) => callableLeadIds.includes(leadId)),
    [callableLeadIds, selectedLeadIds],
  );
  const allCallableSelected = callableLeadIds.length > 0 && selectedCallableLeadIds.length === callableLeadIds.length;
  const selectedLiveCall =
    liveCalls.find((record) => record.id === selectedLiveCallId) ?? liveCalls[0] ?? callRecords[0] ?? null;
  const selectedLiveCallMessages = useMemo(() => transcriptToMonitorMessages(selectedLiveCall), [selectedLiveCall]);
  const activeDmTemplate = dmTemplates.find((template) => template.id === dmForm.templateId) ?? dmTemplates[0];
  const dmSupportedAccounts = useMemo(() => dmAccounts.filter(isSupportedDmAccount), [dmAccounts]);
  const dmLoginAccounts = useMemo(() => dmAccounts.filter(isLoginCapableAccount), [dmAccounts]);
  const commentCaptureAccounts = useMemo(
    () => dmLoginAccounts.filter((account) => isCommentCapturePlatform(account.platform)),
    [dmLoginAccounts],
  );
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
  const dmTaskPlatform = isSupportedDmPlatform(dmForm.platform) ? dmForm.platform : dmAccountPlatforms[0];
  const dmPlatformLeads = useMemo(
    () => dmReachableLeads.filter((lead) => lead.platform === dmTaskPlatform),
    [dmReachableLeads, dmTaskPlatform],
  );
  const dmPlatformLeadIds = useMemo(() => new Set(dmPlatformLeads.map((lead) => lead.id)), [dmPlatformLeads]);
  const selectedDmPlatformLeadIds = useMemo(
    () => selectedDmLeadIds.filter((leadId) => dmPlatformLeadIds.has(leadId)),
    [selectedDmLeadIds, dmPlatformLeadIds],
  );
  const dmPlatformLoggedInAccounts = useMemo(
    () => dmLoggedInAccounts.filter((account) => account.platform === dmTaskPlatform),
    [dmLoggedInAccounts, dmTaskPlatform],
  );
  const dmPlatformRemainingQuota = useMemo(
    () =>
      dmPlatformLoggedInAccounts.reduce(
        (sum, account) => sum + Math.max(0, account.dailyLimit - account.sentToday),
        0,
      ),
    [dmPlatformLoggedInAccounts],
  );
  const dmAccountCountByPlatform = useMemo(
    () =>
      dmLoginAccounts.reduce<Record<string, number>>((counts, account) => {
        counts[account.platform] = (counts[account.platform] ?? 0) + 1;
        return counts;
      }, {}),
    [dmLoginAccounts],
  );
  const isolatedDmAccountCount = useMemo(
    () => dmLoginAccounts.filter((account) => Boolean(account.browserProfileKey || account.browserProfilePath)).length,
    [dmLoginAccounts],
  );
  const activeLoginAccount = useMemo(() => {
    return (
      dmLoginAccounts.find((account) => account.id === selectedDmLoginAccountId) ??
      dmLoginAccounts.find((account) => account.id === dmLoginSession?.accountId) ??
      dmLoginAccounts[0]
    );
  }, [dmLoginAccounts, dmLoginSession, selectedDmLoginAccountId]);
  const activeCommentCaptureAccount = useMemo(() => {
    if (activeLoginAccount && isCommentCapturePlatform(activeLoginAccount.platform)) return activeLoginAccount;
    return commentCaptureAccounts.find((account) => account.platform === commentSourceForm.platform) ?? commentCaptureAccounts[0];
  }, [activeLoginAccount, commentCaptureAccounts, commentSourceForm.platform]);
  const activeBrowserCaptureSource = useMemo(() => {
    const platform = activeCommentCaptureAccount?.platform ?? commentSourceForm.platform;
    return commentSources.find((source) => source.platform === platform) ?? commentSources[0];
  }, [activeCommentCaptureAccount, commentSourceForm.platform, commentSources]);
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
  const activeCommentCaptureConfig = activeCommentCaptureAccount
    ? dmPlatformConfigs.find((config) => config.platform === activeCommentCaptureAccount.platform)
    : null;
  const activeCommentCaptureSession =
    dmLoginSession?.accountId === activeCommentCaptureAccount?.id ? dmLoginSession : null;
  const activeCommentCaptureUrl =
    personalLoginUrl(activeCommentCaptureAccount?.platform ?? "", activeCommentCaptureSession?.loginUrl) ||
    personalLoginUrl(activeCommentCaptureAccount?.platform ?? "", activeCommentCaptureConfig?.homeUrl) ||
    personalLoginUrl(activeCommentCaptureAccount?.platform ?? "", activeCommentCaptureAccount ? platformLoginUrls[activeCommentCaptureAccount.platform] : "") ||
    "";
  const activeCommentQueueItem = activeBrowserCaptureSource
    ? commentAutomationQueue.items.find((item) => item.sourceId === activeBrowserCaptureSource.id)
    : undefined;
  const nextReadyCommentQueueItem =
    commentAutomationQueue.items.find((item) => item.status === "ready" && item.due) ??
    commentAutomationQueue.items.find((item) => item.status === "ready");
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
  const highIntentComments = useMemo(
    () => socialComments.filter((comment) => ["A", "B"].includes(comment.intentLevel)),
    [socialComments],
  );
  const selectedSocialComments = useMemo(
    () => socialComments.filter((comment) => selectedCommentIds.includes(comment.id)),
    [selectedCommentIds, socialComments],
  );
  const selectedPendingComments = useMemo(
    () => selectedSocialComments.filter((comment) => comment.status !== "已转线索"),
    [selectedSocialComments],
  );
  const selectedCommentPlatforms = useMemo(
    () => Array.from(new Set(selectedSocialComments.map((comment) => comment.platform))),
    [selectedSocialComments],
  );
  const selectedSendableCommentCount = useMemo(
    () => selectedSocialComments.filter((comment) => isSupportedDmPlatform(comment.platform)).length,
    [selectedSocialComments],
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
  const realtimeVoiceOptions = useMemo(
    () => [
      ...systemVoices.map((voice) => ({
        key: `system:${voice.id}`,
        label: voice.name,
        detail: `${voice.provider} · ${voice.voiceParam}`,
        selection: {
          voiceId: voice.id,
          voiceName: voice.name,
          voiceType: "system",
          provider: voice.provider,
          externalVoiceId: voice.voiceParam,
        } satisfies RealtimeVoiceSelection,
      })),
      ...availableCloneVoiceRecords.map((record) => ({
        key: `clone:${record.id}`,
        label: record.clonedVoiceName,
        detail: `${record.engine} · ${record.externalVoiceId}`,
        selection: {
          voiceId: record.id,
          voiceName: record.clonedVoiceName,
          voiceType: "clone",
          provider: record.engine,
          externalVoiceId: record.externalVoiceId,
        } satisfies RealtimeVoiceSelection,
      })),
    ],
    [availableCloneVoiceRecords, systemVoices],
  );
  const activeRealtimeVoiceOption = realtimeVoiceOptions.find((option) => option.key === realtimeForm.voiceChoice) ?? realtimeVoiceOptions[0];
  const backendActiveRealtimeRoute = realtimePipeline.routeOptions.find((option) => option.isActive);
  const activeRealtimeRoute =
    backendActiveRealtimeRoute ??
    realtimePipeline.routeOptions.find((option) => option.key === realtimeForm.conversationRoute) ??
    fallbackRealtimePipeline.routeOptions[0];
  useEffect(() => {
    if (!backendActiveRealtimeRoute || realtimeSession) return;
    if (backendActiveRealtimeRoute.key === realtimeForm.conversationRoute) return;
    setRealtimeForm((current) => ({ ...current, conversationRoute: backendActiveRealtimeRoute.key }));
  }, [backendActiveRealtimeRoute, realtimeForm.conversationRoute, realtimeSession]);
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
    setScriptDraft(scriptDraftFrom(activeScript));
  }, [activeScript?.id]);

  useEffect(() => {
    setRuleDraft(recallRuleDraftFrom(activeRule));
  }, [activeRule?.id]);

  useEffect(() => {
    if (selectedLiveCallId && liveCalls.some((record) => record.id === selectedLiveCallId)) return;
    const nextRecord = liveCalls[0] ?? callRecords[0];
    if (nextRecord) setSelectedLiveCallId(nextRecord.id);
  }, [callRecords, liveCalls, selectedLiveCallId]);

  useEffect(() => {
    setIsDesktopClient(Boolean(window.aiAcqDesktop?.isDesktopClient));
  }, []);

  useEffect(() => {
    if (!isDesktopClient || !window.aiAcqDesktop?.getAsteriskSidecarStatus) return;
    void refreshAsteriskSidecarStatus();
  }, [isDesktopClient]);

  useEffect(() => {
    if (activeModule !== "outbound" || activeOutboundTab !== "实时监听") return;
    void refreshRealtimeLiveEvents();
  }, [activeModule, activeOutboundTab]);

  useEffect(() => {
    if (activeModule !== "outbound" || activeOutboundTab !== "实时监听" || !isTestingTelephony) return;
    const timer = window.setInterval(() => {
      void refreshRealtimeLiveEvents(false);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [activeModule, activeOutboundTab, isTestingTelephony]);

  useEffect(() => {
    if (activeModule !== "dm" || activeDmTab !== "评论截流") return;
    void refreshCommentAutomationQueue();
  }, [activeDmTab, activeModule]);

  useEffect(() => {
    setCommentSelectorDraft(selectorDraftFromConfig(activeCommentCaptureConfig));
  }, [activeCommentCaptureConfig?.id, activeCommentCaptureAccount?.platform]);

  useEffect(() => {
    if (!isCommentSchedulerEnabled || activeModule !== "dm" || activeDmTab !== "评论截流") return;
    const intervalMs = Math.max(1, Number(commentSchedulerIntervalMinutes) || 1) * 60 * 1000;
    const timer = window.setInterval(() => {
      if (!isRunningCommentAutomation && !isDispatchingCommentQueue) {
        void dispatchNextCommentAutomation("scheduled");
      }
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [
    activeDmTab,
    activeModule,
    commentSchedulerIntervalMinutes,
    isCommentSchedulerEnabled,
    isDispatchingCommentQueue,
    isRunningCommentAutomation,
  ]);

  useEffect(() => {
    if (activeModule !== "dm" || activeDmTab !== "评论截流") return;
    if (!activeCommentCaptureAccount || activeLoginAccount?.id === activeCommentCaptureAccount.id) return;
    if (activeLoginAccount && isCommentCapturePlatform(activeLoginAccount.platform)) return;
    setSelectedDmLoginAccountId(activeCommentCaptureAccount.id);
    if (dmLoginSession?.accountId !== activeCommentCaptureAccount.id) {
      setDmLoginEntryReady(false);
      setDmLoginSession(null);
    }
  }, [activeCommentCaptureAccount, activeDmTab, activeLoginAccount, activeModule, dmLoginSession]);

  useEffect(() => {
    const viewport = nativeLoginViewportRef.current;
    nativeLoginWebviewRef.current = null;
    if (!viewport) return;

    viewport.replaceChildren();
    if (activeModule !== "dm" || !["私信总览", "账号管理", "评论截流"].includes(activeDmTab)) return;
    if (activeDmTab === "评论截流" && activeLoginAccount && !isCommentCapturePlatform(activeLoginAccount.platform)) return;
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
      api.realtimePipeline(),
      api.commentInterceptOverview(),
      api.commentInterceptSources(),
      api.socialComments(),
      api.collectionTasks(),
      api.collectionRuns(),
      api.rawLeadRecords(),
    ]);

    if (results[0].status === "fulfilled") {
      setApiStatus(results[0].value.status === "ok" ? "后端已连接" : results[0].value.status);
    } else {
      setApiStatus("使用前端示例数据");
    }
    if (results[1].status === "fulfilled") setModules(mergeCustomerModules(results[1].value));
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
        platform: isSupportedDmPlatform(current.platform) ? current.platform : supportedDmPlatforms[0],
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
      setRealtimeForm((current) => {
        const defaultVoice = nextSystemVoices.find((voice) => voice.isDefault) ?? nextSystemVoices[0];
        return defaultVoice && current.voiceChoice.startsWith("system:")
          ? { ...current, voiceChoice: `system:${defaultVoice.id}` }
          : current;
      });
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
    if (results[36].status === "fulfilled") setRealtimePipeline(results[36].value);
    if (results[37].status === "fulfilled") setCommentInterceptOverview(results[37].value);
    if (results[38].status === "fulfilled") setCommentSources(results[38].value);
    if (results[39].status === "fulfilled") {
      const nextComments = results[39].value;
      setSocialComments(nextComments);
      setSelectedCommentIds((current) => current.filter((id) => nextComments.some((comment) => comment.id === id)));
    }
    if (results[40].status === "fulfilled") setCollectionTasks(results[40].value);
    if (results[41].status === "fulfilled") setCollectionRuns(results[41].value);
    if (results[42].status === "fulfilled") setRawLeadRecords(results[42].value);
    setIsLoading(false);
  }

  useEffect(() => {
    if (!auth?.accessToken) return;
    setLeads([]);
    setTasks([]);
    setCollectionTasks([]);
    setCollectionRuns([]);
    setRawLeadRecords([]);
    setSelectedLeadIds([]);
    setSelectedDmLeadIds([]);
    void loadData();
  }, [auth?.accessToken]);

  async function submitLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!loginForm.identifier.trim() || !loginForm.password) return;
    setIsSubmittingAuth(true);
    setAuthMessage("正在登录客户工作台...");
    try {
      const result = await api.login({
        identifier: loginForm.identifier.trim(),
        password: loginForm.password,
      });
      storeAuth(result);
      setAuth(result);
      setCurrentUser(result.user);
      setAuthMessage("");
      setLoginForm((current) => ({ ...current, password: "" }));
    } catch (error) {
      setAuthMessage(error instanceof Error ? error.message : "登录失败，请稍后再试。");
    } finally {
      setIsSubmittingAuth(false);
    }
  }

  async function submitRegistrationRequest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!registrationForm.companyName.trim() || !registrationForm.contactPhone.trim()) return;
    setIsSubmittingAuth(true);
    setAuthMessage("正在提交开通申请...");
    try {
      await api.createRegistrationRequest({
        projectName: registrationForm.projectName.trim() || registrationForm.companyName.trim(),
        companyName: registrationForm.companyName.trim(),
        contactName: registrationForm.contactName.trim() || null,
        contactPhone: registrationForm.contactPhone.trim(),
        contactEmail: registrationForm.contactEmail.trim() || null,
        desiredUsername: registrationForm.desiredUsername.trim() || null,
        note: registrationForm.note.trim() || null,
      });
      setAuthMessage("申请已提交，管理员审核并开通账号后即可登录。");
      setAuthMode("login");
    } catch (error) {
      setAuthMessage(error instanceof Error ? error.message : "提交失败，请稍后再试。");
    } finally {
      setIsSubmittingAuth(false);
    }
  }

  function logout() {
    clearStoredAuth();
    setAuth(null);
    setCurrentUser(null);
    setApiStatus("未登录");
    setAuthMessage("已退出登录。");
  }

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

  function splitCollectionItems(value: string) {
    return value
      .split(/[\n,，、;；]+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  async function submitCollectionTask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cities = splitCollectionItems(collectionForm.cities);
    const categories = splitCollectionItems(collectionForm.categories);
    const keywords = splitCollectionItems(collectionForm.keywords);
    if (!collectionForm.name.trim() || cities.length === 0 || categories.length === 0) return;

    setIsCreatingCollectionTask(true);
    setCollectionMessage("正在创建采集任务...");
    try {
      const created = await api.createCollectionTask({
        name: collectionForm.name.trim(),
        provider: collectionForm.provider,
        cities,
        categories,
        keywords,
        targetPerKeyword: Number(collectionForm.targetPerKeyword) || 10,
        remark: collectionForm.remark.trim() || null,
      });
      setCollectionTasks((current) => [created, ...current]);
      setCollectionMessage("采集任务已创建，可以从前端点击运行。");
    } catch (error) {
      setCollectionMessage(error instanceof Error ? error.message : "采集任务创建失败。");
    } finally {
      setIsCreatingCollectionTask(false);
    }
  }

  async function runCollectionTask(taskId: string) {
    setRunningCollectionTaskId(taskId);
    setCollectionMessage("正在通过服务端采集商家点位...");
    try {
      const run = await api.runCollectionTask(taskId);
      const [taskData, runData, rawData, leadData] = await Promise.all([
        api.collectionTasks(),
        api.collectionRuns(),
        api.rawLeadRecords(),
        api.leads(),
      ]);
      setCollectionRuns([run, ...runData.filter((item) => item.id !== run.id)]);
      setCollectionTasks(taskData);
      setRawLeadRecords(rawData);
      setLeads(leadData);
      setCollectionMessage(
        `采集完成：抓取 ${run.fetchedCount} 条，入库 ${run.insertedCount} 条，重复 ${run.duplicateCount} 条，失败 ${run.failedCount} 条。`,
      );
    } catch (error) {
      setCollectionMessage(error instanceof Error ? error.message : "采集运行失败，请检查服务端数据源配置。");
    } finally {
      setRunningCollectionTaskId(null);
    }
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
    const leadIds = selectedCallableLeadIds;
    if (!outboundForm.name.trim()) {
      setOutboundTaskMessage("请先填写任务名称。");
      return;
    }
    if (leadIds.length === 0) {
      setOutboundTaskMessage("请先选择要拨打的线索。");
      return;
    }

    try {
      const created = await api.createOutboundTask({
        name: outboundForm.name,
        leadIds,
        concurrency: Number(outboundForm.concurrency),
        scriptId: persistedScriptId(activeScript),
        scheduledAt: outboundForm.scheduledAt || null,
      });
      setTasks((current) => [created, ...current.filter((task) => task.id !== created.id)]);
      setOutboundTaskMessage(`已创建「${created.name}」，共 ${leadIds.length} 条线索，可在右侧启动。`);
      setActiveModule("outbound");
      setActiveOutboundTab("任务列表");
    } catch (error) {
      setOutboundTaskMessage(error instanceof Error ? error.message : "外呼任务创建失败。");
    }
  }

  async function startOutboundTask(taskId: string) {
    try {
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
      setOutboundTaskMessage(`已启动「${updated.name}」，正在进入实时监听。`);
      setActiveOutboundTab("实时监听");
    } catch (error) {
      setOutboundTaskMessage(error instanceof Error ? error.message : "外呼任务启动失败。");
    }
  }

  async function refreshAsteriskSidecarStatus() {
    if (!isDesktopClient || !window.aiAcqDesktop?.getAsteriskSidecarStatus) {
      setAsteriskSidecarStatus(null);
      return;
    }
    try {
      const status = await window.aiAcqDesktop.getAsteriskSidecarStatus();
      setAsteriskSidecarStatus(status);
    } catch (error) {
      setTelephonyMessage(error instanceof Error ? error.message : "内置 Asterisk 状态读取失败");
    }
  }

  async function startAsteriskSidecar() {
    if (!isDesktopClient || !window.aiAcqDesktop?.startAsteriskSidecar) {
      setTelephonyMessage("请在客户桌面客户端中启动内置 Asterisk。");
      return;
    }
    setIsStartingAsteriskSidecar(true);
    setTelephonyMessage("正在启动客户端内置 Asterisk...");
    try {
      const status = await window.aiAcqDesktop.startAsteriskSidecar();
      setAsteriskSidecarStatus(status);
      setTelephonyMessage(status.nextStep);
      await refreshTelephonyStatus();
    } catch (error) {
      setTelephonyMessage(error instanceof Error ? error.message : "内置 Asterisk 启动失败");
    } finally {
      setIsStartingAsteriskSidecar(false);
    }
  }

  async function refreshRealtimeLiveEvents(showLoading = true) {
    if (showLoading) setIsRefreshingRealtimeEvents(true);
    try {
      const events = await api.realtimeLiveEvents(80);
      setRealtimeLiveEvents(events);
    } catch {
      // 真实事件日志可能尚未创建；不要覆盖线路试拨状态。
    } finally {
      if (showLoading) setIsRefreshingRealtimeEvents(false);
    }
  }

  async function refreshTelephonyStatus() {
    setIsCheckingTelephony(true);
    setTelephonyMessage("正在预检语音网关/Asterisk 线路...");
    try {
      const [config, preflight] = await Promise.all([api.telephonyConfig(), api.telephonyPreflight(telephonyTestForm.phone)]);
      setTelephonyConfig(config);
      setTelephonyHealth(preflight.health);
      setTelephonyPreflight(preflight);
      setTelephonyMessage(preflight.nextStep || telephonyReadinessDetail(config, preflight.health));
      await refreshAsteriskSidecarStatus();
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
    setTelephonyLineRecovery(null);
    setTelephonyMessage("正在提交单号试拨请求...");
    await refreshRealtimeLiveEvents(false);
    try {
      const result = await api.createTelephonyTestCall({
        phone: telephonyTestForm.phone.trim(),
        callerId: telephonyTestForm.callerId.trim() || null,
      });
      setTelephonyTestResult(result);
      setTelephonyLineRecovery(result.autoRecovery ?? null);
      setTelephonyMessage(
        result.cellularDiagnostic?.title || result.message || (result.accepted ? "试拨请求已被 Asterisk 接收。" : "测试拨号失败"),
      );
      await refreshRealtimeLiveEvents(false);
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
      void refreshRealtimeLiveEvents(false);
    }
  }

  async function recoverTelephonyLine() {
    setIsRecoveringTelephony(true);
    setTelephonyMessage("正在恢复 Asterisk/语音网关线路...");
    try {
      const recovery = await api.recoverTelephonyLine();
      setTelephonyLineRecovery(recovery);
      setTelephonyHealth(recovery.health);
      setTelephonyMessage(recovery.nextStep || recovery.summary);
      try {
        const preflight = await api.telephonyPreflight(telephonyTestForm.phone);
        setTelephonyHealth(preflight.health);
        setTelephonyPreflight(preflight);
      } catch {
        // 恢复结果已经返回，预检刷新失败不覆盖恢复提示。
      }
    } catch (error) {
      setTelephonyMessage(error instanceof Error ? error.message : "线路恢复失败");
    } finally {
      setIsRecoveringTelephony(false);
    }
  }

  async function startRealtimeMockSession() {
    const voice = activeRealtimeVoiceOption?.selection;
    if (!voice) {
      setRealtimeMessage("请先在声音档案中准备至少一个可用音色。");
      return;
    }
    setIsStartingRealtimeSession(true);
    setRealtimeMessage("正在创建模拟实时通话...");
    try {
      const [pipeline, session] = await Promise.all([
        api.realtimePipeline(),
        api.createRealtimeSession({
          merchantName: realtimeForm.merchantName.trim() || "模拟商家",
          phone: realtimeForm.phone.trim() || null,
          voice,
          conversationRoute: realtimeForm.conversationRoute,
        }),
      ]);
      setRealtimePipeline(pipeline);
      setRealtimeSession(session);
      setRealtimeLastReply("");
      setRealtimeMessage("模拟实时通话已就绪，可以输入客户说的话。");
    } catch (error) {
      setRealtimeMessage(error instanceof Error ? error.message : "创建实时通话失败");
    } finally {
      setIsStartingRealtimeSession(false);
    }
  }

  async function sendRealtimeUtterance(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!realtimeForm.customerText.trim()) return;
    let activeSession = realtimeSession;
    setIsSendingRealtimeUtterance(true);
    setRealtimeMessage("正在模拟 ASR/意图/LLM/TTS...");
    try {
      if (!activeSession) {
        const voice = activeRealtimeVoiceOption?.selection;
        if (!voice) throw new Error("请先在声音档案中准备至少一个可用音色。");
        activeSession = await api.createRealtimeSession({
          merchantName: realtimeForm.merchantName.trim() || "模拟商家",
          phone: realtimeForm.phone.trim() || null,
          voice,
          conversationRoute: realtimeForm.conversationRoute,
        });
      }
      const turn = await api.realtimeUtterance(activeSession.id, {
        text: realtimeForm.customerText.trim(),
        bargeIn: true,
      });
      setRealtimeSession(turn.session);
      setRealtimeLastReply(turn.reply);
      setRealtimeMessage(turn.interrupted ? "检测到客户插话，已停止上一段 TTS 并生成新回复。" : "已生成 TTS 分块，等待播放完成或客户打断。");
    } catch (error) {
      setRealtimeMessage(error instanceof Error ? error.message : "模拟实时通话失败");
    } finally {
      setIsSendingRealtimeUtterance(false);
    }
  }

  async function interruptRealtimePlayback() {
    if (!realtimeSession) return;
    const updated = await api.interruptRealtimeSession(realtimeSession.id);
    setRealtimeSession(updated);
    setRealtimeMessage("已停止当前 TTS 播放队列，继续监听客户。");
  }

  async function completeRealtimePlayback() {
    if (!realtimeSession) return;
    const updated = await api.completeRealtimePlayback(realtimeSession.id);
    setRealtimeSession(updated);
    setRealtimeMessage("AI 播放完成，回到监听客户。");
  }

  async function submitDmTask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const leadIds =
      selectedDmPlatformLeadIds.length > 0 ? selectedDmPlatformLeadIds : dmPlatformLeads.slice(0, 20).map((lead) => lead.id);
    if (!dmForm.name.trim()) {
      setDmTaskMessage("请先填写任务名称。");
      return;
    }
    if (dmPlatformLoggedInAccounts.length === 0) {
      setDmTaskMessage(`${dmTaskPlatform}暂无已登录可用个人号，请先到账号管理完成登录后检测。`);
      return;
    }
    if (leadIds.length === 0) {
      setDmTaskMessage(`${dmTaskPlatform}暂无可私信线索，请先在线索库导入该平台商家。`);
      return;
    }

    try {
      const created = await api.createDmTask({
        name: dmForm.name,
        leadIds,
        accountId: null,
        templateId: activeDmTemplate?.id ?? null,
        scheduledAt: dmForm.scheduledAt || null,
      });
      setTasks((current) => [created, ...current.filter((task) => task.id !== created.id)]);
      setDmTaskMessage(`已创建${dmTaskPlatform}私信任务，将使用${dmPlatformLoggedInAccounts.length}个已登录个人号自动轮换。`);
      setActiveModule("dm");
      setActiveDmTab("任务列表");
    } catch (error) {
      setDmTaskMessage(error instanceof Error ? error.message : "创建私信任务失败");
    }
  }

  async function submitCommentSource(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!commentSourceForm.name.trim()) {
      setCommentInterceptMessage("请先填写截流来源名称。");
      return;
    }
    if (!isDesktopClient) {
      setCommentInterceptMessage("自动搜索和私信准备需要桌面客户端内置登录页，请打开桌面客户端后再添加并执行。");
      return;
    }
    try {
      const created = await api.createCommentInterceptSource({
        ...commentSourceForm,
        ownerAccountId: null,
        syncFrequencyMinutes: Number(commentSourceForm.syncFrequencyMinutes) || 120,
        autoReplyEnabled: false,
        humanConfirmRequired: true,
      });
      setCommentSources((current) => [created, ...current.filter((source) => source.id !== created.id)]);
      setCommentInterceptMessage(`已添加「${created.name}」，准备启动内置页自动搜索、滚动采集和私信草稿链路...`);
      await runCommentAutomationForSource(created.id, created);
    } catch (error) {
      setCommentInterceptMessage(error instanceof Error ? error.message : "添加评论截流来源失败");
    }
  }

  async function refreshCommentInterceptData() {
    const [overviewData, sourcesData, commentsData] = await Promise.all([
      api.commentInterceptOverview(),
      api.commentInterceptSources(),
      api.socialComments(),
    ]);
    setCommentInterceptOverview(overviewData);
    setCommentSources(sourcesData);
    setSocialComments(commentsData);
    setSelectedCommentIds((current) => current.filter((id) => commentsData.some((comment) => comment.id === id)));
    return commentsData;
  }

  async function refreshCommentAutomationQueue() {
    setIsLoadingCommentAutomationQueue(true);
    try {
      const queue = await api.commentInterceptAutomationQueue();
      setCommentAutomationQueue(queue);
      return queue;
    } catch (error) {
      setCommentInterceptMessage(error instanceof Error ? error.message : "自动化队列刷新失败");
      return commentAutomationQueue;
    } finally {
      setIsLoadingCommentAutomationQueue(false);
    }
  }

  function selectorsForCommentAutomation(platform: string) {
    const draftPlatform = activeCommentCaptureAccount?.platform ?? commentSourceForm.platform;
    const config = dmPlatformConfigs.find((item) => item.platform === platform);
    const source = platform === draftPlatform ? commentSelectorDraft : selectorDraftFromConfig(config);
    return {
      riskCheckSelector: source.riskCheckSelector.trim(),
      messageButtonSelector: source.messageButtonSelector.trim(),
      inputSelector: source.inputSelector.trim(),
      sendButtonSelector: source.sendButtonSelector.trim(),
      sentSuccessSelector: source.sentSuccessSelector.trim(),
    };
  }

  async function saveCommentSelectorDraft() {
    const platform = activeCommentCaptureAccount?.platform ?? commentSourceForm.platform;
    if (!platform) {
      setCommentInterceptMessage("请选择一个评论截流平台后再保存选择器。");
      return;
    }
    setIsSavingCommentSelectors(true);
    try {
      const realConfig = dmPlatformConfigs.find((config) => config.platform === platform && !config.id.startsWith("dm_platform_"));
      const baseConfig = dmPlatformConfigs.find((config) => config.platform === platform);
      const payload = {
        platform,
        homeUrl: baseConfig?.homeUrl ?? platformLoginUrls[platform] ?? "",
        inboxUrl: baseConfig?.inboxUrl ?? "",
        merchantSearchUrl: baseConfig?.merchantSearchUrl ?? "",
        loginCheckSelector: baseConfig?.loginCheckSelector ?? "",
        riskCheckSelector: commentSelectorDraft.riskCheckSelector.trim(),
        merchantLinkSelector: baseConfig?.merchantLinkSelector ?? "",
        messageButtonSelector: commentSelectorDraft.messageButtonSelector.trim(),
        inputSelector: commentSelectorDraft.inputSelector.trim(),
        sendButtonSelector: commentSelectorDraft.sendButtonSelector.trim(),
        sentSuccessSelector: commentSelectorDraft.sentSuccessSelector.trim(),
        unreadSelector: baseConfig?.unreadSelector ?? "",
        conversationItemSelector: baseConfig?.conversationItemSelector ?? "",
        conversationTitleSelector: baseConfig?.conversationTitleSelector ?? "",
        messageTextSelector: baseConfig?.messageTextSelector ?? "",
        enabled: true,
      };
      const saved = realConfig
        ? await api.updateDmPlatformConfig(realConfig.id, payload)
        : await api.createDmPlatformConfig(payload);
      setDmPlatformConfigs((current) => [saved, ...current.filter((config) => config.id !== saved.id && config.platform !== platform)]);
      setCommentInterceptMessage(`${platform}选择器配置已保存，下一次自动化会优先使用这些选择器。`);
      await refreshCommentAutomationQueue();
    } catch (error) {
      setCommentInterceptMessage(error instanceof Error ? error.message : "选择器配置保存失败");
    } finally {
      setIsSavingCommentSelectors(false);
    }
  }

  async function pauseCommentAutomationForLoginRequired(source: CommentInterceptSource, account: DmAccount, reason: string) {
    const result = await api.reportCommentInterceptAutomationRisk(source.id, {
      platform: source.platform,
      accountId: account.id,
      status: "login-required",
      reason,
      step: "account_switch",
    });
    await refreshCommentAutomationQueue();
    return result.message;
  }

  async function reportCommentAutomationRiskFromResult(
    source: CommentInterceptSource,
    accountId: string | null,
    automation: AiAcqDesktopCommentAutomationResult,
  ) {
    if (automation.dmActions.length === 0) return "";
    const blocked = automation.dmActions.find((action) => action.status === "send-blocked" || action.receiptStatus === "blocked");
    const allSelectorMissing = automation.dmActions.every((action) => ["no-input", "send-button-missing"].includes(action.status));
    const selectorMissing = allSelectorMissing ? automation.dmActions[0] : undefined;
    const action = blocked ?? selectorMissing;
    if (!action) return "";

    const status = blocked ? "send-blocked" : action.status === "send-button-missing" ? "send-button-missing" : "no-input";
    const result = await api.reportCommentInterceptAutomationRisk(source.id, {
      platform: source.platform,
      accountId,
      status,
      reason: action.receiptMessage || action.message || action.status,
      step: "prepare_dm",
      url: action.url,
      rawPayload: {
        authorName: action.authorName,
        profileUrl: action.profileUrl,
        status: action.status,
        receiptStatus: action.receiptStatus,
      },
    });
    await refreshCommentAutomationQueue();
    return result.message;
  }

  async function dispatchNextCommentAutomation(trigger: "manual" | "scheduled" = "manual") {
    if (isDispatchingCommentQueue || isRunningCommentAutomation || isCapturingBrowserComments) return;
    setIsDispatchingCommentQueue(true);
    try {
      const queue = await refreshCommentAutomationQueue();
      const nextItem =
        queue.items.find((item) => item.status === "ready" && item.due) ??
        queue.items.find((item) => item.status === "ready");
      if (!nextItem) {
        setCommentInterceptMessage(queue.message || "当前没有可执行的评论截流队列任务。");
        return;
      }
      let source = commentSources.find((item) => item.id === nextItem.sourceId);
      if (!source) {
        const sources = await api.commentInterceptSources();
        setCommentSources(sources);
        source = sources.find((item) => item.id === nextItem.sourceId);
      }
      if (!source) {
        setCommentInterceptMessage("队列中的评论截流来源不存在，请刷新后重试。");
        return;
      }
      setCommentInterceptMessage(
        `${trigger === "scheduled" ? "定时队列" : "手动队列"}选择「${source.name}」，账号 ${nextItem.nextAccountName ?? "待分配"}。`,
      );
      await runCommentAutomationForSource(source.id, source, nextItem.nextAccountId ?? undefined);
    } finally {
      setIsDispatchingCommentQueue(false);
    }
  }

  function selectHighIntentCommentRows(commentsData: SocialComment[]) {
    const newHighIntentIds = commentsData
      .filter((comment) => ["A", "B"].includes(comment.intentLevel) && comment.status !== "已转线索")
      .map((comment) => comment.id);
    setSelectedCommentIds(newHighIntentIds);
  }

  async function syncCommentSource(sourceId: string) {
    setIsSyncingComments(true);
    setCommentInterceptMessage("正在同步评论...");
    try {
      const result: CommentSyncResult = await api.syncCommentInterceptSource(sourceId);
      const commentsData = await refreshCommentInterceptData();
      selectHighIntentCommentRows(commentsData);
      setCommentInterceptMessage(result.message);
    } catch (error) {
      await refreshCommentInterceptData().catch(() => undefined);
      setCommentInterceptMessage(error instanceof Error ? error.message : "同步评论失败");
    } finally {
      setIsSyncingComments(false);
    }
  }

  async function prepareCommentCaptureWebview(
    source: CommentInterceptSource,
    actionLabel: string,
    preferredAccountId?: string | null,
    pauseOnLoginFailure = false,
  ) {
    if (!source) {
      setCommentInterceptMessage("评论截流来源不存在，请刷新后重试。");
      return null;
    }
    if (!isCommentCapturePlatform(source.platform)) {
      setCommentInterceptMessage(`${source.platform}暂未开放浏览器登录评论采集。`);
      return null;
    }

    const preferredAccount = preferredAccountId
      ? commentCaptureAccounts.find((account) => account.id === preferredAccountId && account.platform === source.platform)
      : undefined;
    let captureAccount =
      preferredAccount ??
      (activeLoginAccount?.platform === source.platform
        ? activeLoginAccount
        : commentCaptureAccounts.find((account) => account.platform === source.platform));
    if (!captureAccount) {
      setCommentInterceptMessage(`请先在账号管理里添加一个${source.platform}个人号，再使用内置登录页采集评论。`);
      setActiveDmTab("账号管理");
      return null;
    }

    if (!isDesktopClient) {
      setSelectedDmLoginAccountId(captureAccount.id);
      setCommentInterceptMessage(`当前是网页预览，不能${actionLabel}。请用桌面客户端打开后再执行。`);
      return null;
    }

    const currentWebview = nativeLoginWebviewRef.current;
    const currentWebContentsId =
      currentWebview?.getAttribute("data-account-id") === captureAccount.id ? currentWebview.getWebContentsId?.() ?? 0 : 0;
    let webContentsId = currentWebContentsId;

    if (!webContentsId) {
      setCommentInterceptMessage(`正在自动切换到${captureAccount.accountName}，加载该账号的内置登录页...`);
      const session = await openRealDmLogin(captureAccount.id);
      if (!session) return null;
      try {
        const ready = await waitForNativeLoginWebview(captureAccount.id, 20000);
        webContentsId = ready.webContentsId;
      } catch (error) {
        const message = error instanceof Error ? error.message : "账号内置页加载超时";
        if (pauseOnLoginFailure) {
          const riskMessage = await pauseCommentAutomationForLoginRequired(source, captureAccount, message).catch(() => "");
          setCommentInterceptMessage(`${captureAccount.accountName}切换失败，自动化已暂停。${riskMessage || message}`);
        } else {
          setCommentInterceptMessage(`${captureAccount.accountName}内置页未就绪：${message}`);
        }
        return null;
      }
    }

    try {
      const updatedAccount = await inspectEmbeddedDmLoginAccount(captureAccount, webContentsId, actionLabel);
      captureAccount = updatedAccount;
      if (!isDmLoginReadyStatus(updatedAccount.sessionStatus)) {
        const reason = updatedAccount.lastError || `${updatedAccount.accountName}未检测到真实平台登录态`;
        if (pauseOnLoginFailure) {
          const riskMessage = await pauseCommentAutomationForLoginRequired(source, updatedAccount, reason).catch(() => "");
          setCommentInterceptMessage(`${updatedAccount.accountName}未登录，自动化已暂停。${riskMessage || reason}`);
        } else {
          setCommentInterceptMessage(reason);
        }
        return null;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "自动检测账号登录态失败";
      if (pauseOnLoginFailure) {
        const riskMessage = await pauseCommentAutomationForLoginRequired(source, captureAccount, message).catch(() => "");
        setCommentInterceptMessage(`${captureAccount.accountName}登录态检测失败，自动化已暂停。${riskMessage || message}`);
      } else {
        setCommentInterceptMessage(message);
      }
      return null;
    }

    return { captureAccount, webContentsId };
  }

  async function captureCommentsFromEmbeddedPage(sourceId: string, sourceOverride?: CommentInterceptSource) {
    const source = sourceOverride ?? commentSources.find((item) => item.id === sourceId);
    if (!source) {
      setCommentInterceptMessage("评论截流来源不存在，请刷新后重试。");
      return;
    }
    const prepared = await prepareCommentCaptureWebview(source, "采集当前内置页");
    if (!prepared) return;
    const { captureAccount, webContentsId } = prepared;

    setIsCapturingBrowserComments(true);
    setCommentInterceptMessage(`正在读取${captureAccount.platform}内置页 DOM，并导入当前页面评论...`);
    try {
      const capture = await window.aiAcqDesktop!.captureCommentIntercept({
        webContentsId,
        platform: source.platform,
      });
      if (capture.error) {
        throw new Error(capture.error);
      }
      const result = await api.captureCommentInterceptFromBrowser(source.id, {
        platform: source.platform,
        pageUrl: capture.url,
        pageTitle: capture.title,
        comments: capture.comments as BrowserCapturedComment[],
      });
      const commentsData = await refreshCommentInterceptData();
      selectHighIntentCommentRows(commentsData);
      setCommentInterceptMessage(result.message);
    } catch (error) {
      await refreshCommentInterceptData().catch(() => undefined);
      setCommentInterceptMessage(error instanceof Error ? error.message : "采集当前内置页评论失败");
    } finally {
      setIsCapturingBrowserComments(false);
    }
  }

  async function runCommentAutomationForSource(
    sourceId: string,
    sourceOverride?: CommentInterceptSource,
    preferredAccountId?: string | null,
  ) {
    const source = sourceOverride ?? commentSources.find((item) => item.id === sourceId);
    if (!source) {
      setCommentInterceptMessage("评论截流来源不存在，请刷新后重试。");
      return;
    }
    let queueItem: CommentAutomationQueueItem | null = null;
    try {
      queueItem = await api.preflightCommentInterceptAutomation(source.id);
      setCommentAutomationQueue((current) => ({
        ...current,
        items: [queueItem as CommentAutomationQueueItem, ...current.items.filter((item) => item.sourceId !== source.id)],
      }));
    } catch (error) {
      setCommentInterceptMessage(error instanceof Error ? error.message : "自动化预检失败");
      return;
    }
    if (!queueItem) return;
    if (["blocked", "paused"].includes(queueItem.status)) {
      setCommentInterceptMessage(`「${source.name}」暂不能自动执行：${queueItem.blockedReason || commentAutomationStatusText(queueItem.status)}`);
      return;
    }
    const prepared = await prepareCommentCaptureWebview(source, "自动搜索并执行", preferredAccountId ?? queueItem.nextAccountId, true);
    if (!prepared) return;
    const { captureAccount, webContentsId } = prepared;

    let allowSend = false;
    const requestedMaxAuthors = Number(commentAutomationForm.maxAuthors) || 0;
    let effectiveMaxAuthors = requestedMaxAuthors;
    const sendIntervalSeconds = Math.max(
      Number(commentAutomationForm.sendIntervalSeconds) || 0,
      Number(captureAccount.minSendIntervalSeconds) || 0,
    );
    let sendGateMessage = "私信动作将停在草稿/确认前。";
    if (commentAutomationForm.allowLiveSend) {
      if (!isSupportedDmPlatform(source.platform)) {
        sendGateMessage = `${source.platform}当前未接入自动私信发送，只会填草稿。`;
      } else if (captureAccount.status !== "可用" || !isDmLoginReadyStatus(captureAccount.sessionStatus)) {
        sendGateMessage = `${captureAccount.accountName}还不是可用/已登录状态，只会填草稿。`;
      } else if (["需验证", "风控暂停", "封禁", "异常"].includes(captureAccount.riskStatus ?? "")) {
        sendGateMessage = `${captureAccount.accountName}风险状态为${captureAccount.riskStatus}，只会填草稿。`;
      } else if (captureAccount.dailyLimit - captureAccount.sentToday <= 0) {
        sendGateMessage = `${captureAccount.accountName}今日额度已用完，只会填草稿。`;
      } else {
        try {
          const dmConfig = await api.dmConfig();
          if (dmConfig.browserLiveSendEnabled) {
            const remainingQuota = Math.max(0, captureAccount.dailyLimit - captureAccount.sentToday);
            effectiveMaxAuthors = Math.min(Math.max(0, requestedMaxAuthors), remainingQuota);
            allowSend = window.confirm(
              `确认要在真实平台自动点击发送私信？本次最多处理 ${effectiveMaxAuthors} 个作者，发送间隔 ${sendIntervalSeconds} 秒，会使用当前内置登录账号对评论作者发出消息。`,
            );
            sendGateMessage = allowSend ? `已确认真实发送闸门，最多发送 ${effectiveMaxAuthors} 条。` : "已取消真实发送，改为只填草稿。";
          } else {
            sendGateMessage = "后台未开启 browserLiveSendEnabled，只会填草稿。";
          }
        } catch {
          sendGateMessage = "未能读取私信发送配置，只会填草稿。";
        }
      }
    }

    setIsRunningCommentAutomation(true);
    setLastCommentAutomationResult(null);
    setCommentInterceptMessage(`正在用${captureAccount.platform}内置页执行自动搜索、打开视频、滚动评论和私信准备。${sendGateMessage}`);
    try {
      const automation = await window.aiAcqDesktop!.runCommentInterceptAutomation({
        webContentsId,
        platform: source.platform,
        keyword: source.keyword || commentSourceForm.keyword,
        sourceUrl: source.videoUrl || commentSourceForm.videoUrl,
        sourceType: source.sourceType || commentSourceForm.sourceType,
        scrollRounds: Number(commentAutomationForm.scrollRounds) || 6,
        maxAuthors: allowSend ? effectiveMaxAuthors : requestedMaxAuthors,
        sendIntervalSeconds,
        dmMessage: commentAutomationForm.dmMessage,
        allowSend,
        selectors: selectorsForCommentAutomation(source.platform),
      });
      setLastCommentAutomationResult(automation);
      if (automation.error) {
        throw new Error(automation.error);
      }
      const result = await api.captureCommentInterceptFromBrowser(source.id, {
        platform: source.platform,
        pageUrl: automation.url,
        pageTitle: automation.title,
        comments: automation.comments as BrowserCapturedComment[],
      });
      const commentsData = await refreshCommentInterceptData();
      selectHighIntentCommentRows(commentsData);
      let recordMessage = "";
      if (automation.dmActions.length > 0) {
        const recordResult = await api.recordCommentInterceptDmActions(source.id, {
          platform: source.platform,
          accountId: captureAccount.id,
          messageContent: commentAutomationForm.dmMessage,
          actions: automation.dmActions.map(
            (action): BrowserDmAction => ({
              authorName: action.authorName,
              profileUrl: action.profileUrl,
              status: action.status,
              sent: action.sent,
              sendClicked: Boolean(action.sendClicked),
              sentConfirmed: Boolean(action.sentConfirmed),
              receiptStatus: action.receiptStatus || "",
              receiptMessage: action.receiptMessage || "",
              outgoingContent: action.outgoingContent || commentAutomationForm.dmMessage,
              message: action.message,
              url: action.url,
              rawPayload: {
                receiptStatus: action.receiptStatus || "",
                receiptMessage: action.receiptMessage || "",
              },
            }),
          ),
        });
        recordMessage = recordResult.message;
        const [dmOverviewData, conversationData, messageData, leadData, accountData, taskData] = await Promise.all([
          api.dmOverview(),
          api.dmConversations(),
          api.dmMessages(),
          api.leads(),
          api.dmAccounts(),
          api.tasks(),
        ]);
        setDmOverview(dmOverviewData);
        setDmConversations(conversationData);
        setDmMessages(messageData);
        setLeads(leadData);
        setDmAccounts(accountData);
        setTasks(taskData);
      }
      const riskMessage = await reportCommentAutomationRiskFromResult(source, captureAccount.id, automation);
      if (!riskMessage) await refreshCommentAutomationQueue();
      const draftCount = automation.dmActions.filter((action) => action.status === "draft-ready").length;
      const sentCount = automation.dmActions.filter((action) => action.sent).length;
      const receiptUnconfirmedCount = automation.dmActions.filter((action) => action.receiptStatus === "unconfirmed").length;
      const failedCount = automation.dmActions.filter((action) =>
        ["failed", "no-input", "send-button-missing", "send-blocked"].includes(action.status),
      ).length;
      setCommentInterceptMessage(
        `${result.message} 自动化完成：${automation.steps.length} 步，处理作者 ${automation.dmActions.length} 个，草稿 ${draftCount} 条，已发送 ${sentCount} 条，回执未确认 ${receiptUnconfirmedCount} 条，异常 ${failedCount} 个。${recordMessage ? ` ${recordMessage}` : ""}${riskMessage ? ` ${riskMessage}` : ""}`,
      );
    } catch (error) {
      await refreshCommentInterceptData().catch(() => undefined);
      setCommentInterceptMessage(error instanceof Error ? error.message : "自动搜索采集链路执行失败");
    } finally {
      setIsRunningCommentAutomation(false);
    }
  }

  function toggleComment(commentId: string) {
    setSelectedCommentIds((current) =>
      current.includes(commentId) ? current.filter((id) => id !== commentId) : [...current, commentId],
    );
  }

  function selectHighIntentComments() {
    setSelectedCommentIds(highIntentComments.filter((comment) => comment.status !== "已转线索").map((comment) => comment.id));
    setCommentInterceptMessage("已选择 A/B 级高意向评论。");
  }

  async function convertSelectedCommentsToLeads() {
    if (selectedPendingComments.length === 0) {
      setCommentInterceptMessage("请先选择待转线索的评论。");
      return null;
    }
    setIsConvertingComments(true);
    setCommentInterceptMessage("正在把评论转入线索库...");
    try {
      const firstComment = selectedPendingComments[0];
      const result = await api.convertCommentsToLeads({
        commentIds: selectedPendingComments.map((comment) => comment.id),
        city: firstComment.city === "待识别" ? "待识别" : firstComment.city,
        category: firstComment.category === "待识别" ? "待识别" : firstComment.category,
        status: "待私信",
      });
      setLastCommentConvertResult(result);
      const [leadData] = await Promise.all([api.leads(), refreshCommentInterceptData()]);
      setLeads(leadData);
      setSelectedDmLeadIds((current) => Array.from(new Set([...current, ...result.leadIds])));
      setCommentInterceptMessage(result.message);
      return result;
    } catch (error) {
      setCommentInterceptMessage(error instanceof Error ? error.message : "评论转线索失败");
      return null;
    } finally {
      setIsConvertingComments(false);
    }
  }

  async function prepareDmTaskFromComments() {
    const result = await convertSelectedCommentsToLeads();
    if (!result || result.leadIds.length === 0) return;

    const leadData = await api.leads();
    setLeads(leadData);
    const convertedLeads = leadData.filter((lead) => result.leadIds.includes(lead.id) && isSupportedDmPlatform(lead.platform));
    const nextPlatform = convertedLeads[0]?.platform;
    if (!nextPlatform) {
      setCommentInterceptMessage("评论已转线索；当前选中评论没有可自动私信的平台，可走评论回复、人工跟进或外呼。");
      return;
    }
    const platformLeadIds = convertedLeads.filter((lead) => lead.platform === nextPlatform).map((lead) => lead.id);
    setDmForm((current) => ({
      ...current,
      platform: nextPlatform,
      name: `${nextPlatform}评论截流线索首轮私信`,
    }));
    setSelectedDmLeadIds(platformLeadIds);
    setDmTaskMessage(`已带入 ${platformLeadIds.length} 条${nextPlatform}评论截流线索，创建后将使用已登录${nextPlatform}个人号轮换发送。`);
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
    if (!dmAccountForm.accountName.trim() || !isLoginCapablePlatform(dmAccountForm.platform)) return;

    const created = await api.createDmAccount({
      ...dmAccountForm,
      dailyLimit: Number(dmAccountForm.dailyLimit),
      minSendIntervalSeconds: Number(dmAccountForm.minSendIntervalSeconds),
    });
    setDmAccounts((current) => [created, ...current]);
    if (isSupportedDmPlatform(created.platform)) {
      setDmForm((current) => ({ ...current, platform: created.platform }));
    }
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
    if (!isLoginCapablePlatform(platform)) return;

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

  function waitForNativeLoginWebview(accountId: string, timeoutMs = 15000) {
    return new Promise<{ webview: DmLoginWebviewElement; webContentsId: number }>((resolve, reject) => {
      const startedAt = Date.now();
      const poll = () => {
        const webview = nativeLoginWebviewRef.current;
        const webContentsId = webview?.getWebContentsId?.() ?? 0;
        const matchedAccount = webview?.getAttribute("data-account-id") === accountId;
        const isLoading = Boolean(webview?.isLoading?.());
        if (matchedAccount && webContentsId > 0 && !isLoading) {
          resolve({ webview, webContentsId });
          return;
        }
        if (Date.now() - startedAt >= timeoutMs) {
          reject(new Error("账号内置页加载超时，请检查客户端 WebView 或平台入口。"));
          return;
        }
        window.setTimeout(poll, 250);
      };
      poll();
    });
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
      return null;
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
      return session;
    } catch (error) {
      setDmLoginMessage(error instanceof Error ? error.message : "加载客户端内置登录页失败");
      return null;
    } finally {
      setIsPreparingDmLogin(false);
    }
  }

  async function inspectEmbeddedDmLoginAccount(account: DmAccount, webContentsId: number, contextLabel: string) {
    if (!window.aiAcqDesktop?.inspectDmLogin) {
      throw new Error("桌面客户端未开放登录态检测能力。");
    }
    setDmLoginMessage(`正在自动检测${account.accountName}登录态...`);
    const evidence: DmDesktopLoginEvidence = await window.aiAcqDesktop.inspectDmLogin({
      webContentsId,
      platform: account.platform,
    });
    const updated = await api.completeDmDesktopLoginCheck(account.id, evidence);
    setDmAccounts((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    setDmLoginMessage(
      isDmLoginReadyStatus(updated.sessionStatus)
        ? `${contextLabel}：${updated.accountName} 登录态检测通过。`
        : updated.lastError || `${contextLabel}：${updated.accountName} 未检测到登录态。`,
    );
    return updated;
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

  function toggleAllCallableLeads() {
    setSelectedLeadIds((current) => {
      const callableSet = new Set(callableLeadIds);
      if (allCallableSelected) return current.filter((leadId) => !callableSet.has(leadId));
      return Array.from(new Set([...current, ...callableLeadIds]));
    });
  }

  function generateScriptDraft() {
    setIsGeneratingScript(true);
    const selectedLead = callableLeads.find((lead) => selectedCallableLeadIds.includes(lead.id)) ?? callableLeads[0] ?? leads[0];
    const messages = transcriptToMonitorMessages(selectedLiveCall);
    const latestCustomerReply = [...messages].reverse().find((message) => message.speaker === "customer")?.text;
    const city = selectedLead?.city || "本地";
    const category = selectedLead?.category || "本地生活";
    const merchant = selectedLiveCall?.merchantName || selectedLead?.name || "商家";
    setScriptDraft({
      name: `${category}商家实时外呼话术`,
      opening: `您好，我是视频号本地生活服务顾问，看到${merchant}在${city}${category}领域适合做团购获客，想快速确认是否方便聊两分钟。`,
      qualification: `您现在更想提升到店客流、团购转化，还是先把线上曝光做起来？目前每月希望新增多少有效客户？`,
      objection: latestCustomerReply
        ? `刚刚客户反馈“${latestCustomerReply}”。先复述理解，再给一个低风险试跑方案，只问是否愿意看同城案例。`
        : "如果客户担心成本或效果，先给同城案例和低风险试跑，不催促成交。",
      closing: "如果方便，我把适合您品类的案例和基础方案发过去，后续由顾问按您的时间继续跟进。",
      isActive: true,
    });
    window.setTimeout(() => setIsGeneratingScript(false), 220);
    setScriptMessage("AI 已根据业务和当前客户回复生成一版话术，可继续手动调整。");
  }

  async function saveScriptDraft() {
    if (!scriptDraft.name.trim() || !scriptDraft.opening.trim()) {
      setScriptMessage("请至少填写话术名称和开场白。");
      return;
    }
    setIsSavingScript(true);
    try {
      const payload = {
        ...scriptDraft,
        name: scriptDraft.name.trim(),
        opening: scriptDraft.opening.trim(),
        qualification: scriptDraft.qualification.trim(),
        objection: scriptDraft.objection.trim(),
        closing: scriptDraft.closing.trim(),
      };
      const activeScriptId = persistedScriptId(activeScript);
      const saved = activeScriptId
        ? await api.updateCallScript(activeScriptId, payload)
        : await api.createCallScript(payload);
      setScripts((current) => [
        saved,
        ...current
          .filter((script) => script.id !== saved.id)
          .map((script) => (saved.isActive ? { ...script, isActive: false } : script)),
      ]);
      setScriptDraft(scriptDraftFrom(saved));
      setScriptMessage(`已保存「${saved.name}」。`);
    } catch (error) {
      setScriptMessage(error instanceof Error ? error.message : "话术保存失败。");
    } finally {
      setIsSavingScript(false);
    }
  }

  async function saveRecallRuleDraft() {
    if (!activeRule?.id) {
      setRuleMessage("暂无可保存的重拨规则。");
      return;
    }
    setIsSavingRule(true);
    try {
      const saved = await api.updateRecallRule(activeRule.id, {
        ...ruleDraft,
        name: ruleDraft.name.trim() || "默认重拨规则",
        noAnswerIntervalMinutes: Number(ruleDraft.noAnswerIntervalMinutes) || 240,
        busyIntervalMinutes: Number(ruleDraft.busyIntervalMinutes) || 120,
        maxAttempts: Number(ruleDraft.maxAttempts) || 3,
      });
      setRecallRules((current) => [saved, ...current.filter((rule) => rule.id !== saved.id)]);
      setRuleDraft(recallRuleDraftFrom(saved));
      setRuleMessage(`已保存「${saved.name}」。`);
    } catch (error) {
      setRuleMessage(error instanceof Error ? error.message : "重拨规则保存失败。");
    } finally {
      setIsSavingRule(false);
    }
  }

  function toggleDmLead(leadId: string) {
    setSelectedDmLeadIds((current) =>
      current.includes(leadId) ? current.filter((id) => id !== leadId) : [...current, leadId],
    );
  }

  function renderRealtimePipelinePanel() {
    return (
      <article className="panel span-2 realtime-voice-panel">
        <div className="panel-title">
          <div>
            <p>Realtime Voice</p>
            <h2>实时语音管线</h2>
          </div>
          <div className="button-row">
            <button className="secondary-button" disabled={isRefreshingRealtimeEvents} onClick={() => void refreshRealtimeLiveEvents()} type="button">
              <RefreshCw size={16} className={isRefreshingRealtimeEvents ? "spin" : ""} />
              真实事件
            </button>
            <button className="secondary-button" disabled={isStartingRealtimeSession} onClick={() => void startRealtimeMockSession()} type="button">
              <Bot size={16} />
              {isStartingRealtimeSession ? "创建中" : "模拟通话"}
            </button>
          </div>
        </div>
        <div className="realtime-pipeline-summary">
          <div>
            <span>当前路线</span>
            <strong>{activeRealtimeRoute?.label ?? (realtimePipeline.mode === "half_duplex_interruptible" ? "半双工可打断" : realtimePipeline.mode)}</strong>
          </div>
          <div>
            <span>媒体桥</span>
            <strong>{realtimePipeline.bridgeMode === "mock_media" ? "模拟媒体" : "Asterisk媒体"}</strong>
          </div>
          <div>
            <span>目标延迟</span>
            <strong>{realtimePipeline.targetLatencyMs} ms</strong>
          </div>
          <div>
            <span>预估成本</span>
            <strong>¥{realtimePipeline.estimatedAiCostPerMinute.toFixed(2)} / 分钟</strong>
          </div>
        </div>
        <div className="realtime-pipeline-steps">
          {realtimePipeline.steps.map((step) => (
            <div className="line-preflight-step" key={step.key}>
              <span className={`line-preflight-badge is-${step.status}`}>{realtimePipelineStatusText(step.status)}</span>
              <div>
                <strong>{step.label}</strong>
                <small>{step.provider} · {step.latencyMs} ms</small>
                <em>{step.detail}</em>
              </div>
            </div>
          ))}
        </div>
        <form className="realtime-call-form" onSubmit={sendRealtimeUtterance}>
          <label>
            模拟商家
            <input
              value={realtimeForm.merchantName}
              onChange={(event) => setRealtimeForm({ ...realtimeForm, merchantName: event.target.value })}
            />
          </label>
          <label>
            电话
            <input
              placeholder="可留空"
              value={realtimeForm.phone}
              onChange={(event) => setRealtimeForm({ ...realtimeForm, phone: event.target.value })}
            />
          </label>
          <label className="wide">
            对话路线
            <select
              value={realtimeForm.conversationRoute}
              onChange={(event) => {
                const nextRoute = event.target.value as "pipeline" | "omni";
                setRealtimeForm({ ...realtimeForm, conversationRoute: nextRoute });
                setRealtimeSession(null);
                setRealtimeLastReply("");
                setRealtimeMessage("已切换对话路线，请重新创建或发送一句模拟通话。");
              }}
            >
              {realtimePipeline.routeOptions.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label} - ¥{option.estimatedAiCostPerMinute.toFixed(2)}/分钟 · {option.estimatedLatencyMs}ms
                </option>
              ))}
            </select>
          </label>
          <label className="wide">
            本次外呼音色
            <select
              value={activeRealtimeVoiceOption?.key ?? realtimeForm.voiceChoice}
              onChange={(event) => setRealtimeForm({ ...realtimeForm, voiceChoice: event.target.value })}
            >
              {realtimeVoiceOptions.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label} - {option.selection.voiceType === "clone" ? "复刻音色" : "系统音色"}
                </option>
              ))}
            </select>
          </label>
          <label className="wide">
            客户说话
            <input
              value={realtimeForm.customerText}
              onChange={(event) => setRealtimeForm({ ...realtimeForm, customerText: event.target.value })}
            />
          </label>
          <button className="primary-button" disabled={isSendingRealtimeUtterance || !realtimeForm.customerText.trim()} type="submit">
            <Radio size={16} />
            {isSendingRealtimeUtterance ? "处理中" : realtimeSession ? "发送一句" : "创建并发送"}
          </button>
        </form>
        <div className="realtime-session-board">
          <div className="line-test-result">
            <strong>{realtimeSession ? realtimeSessionStatusText(realtimeSession.status) : "未开始"}</strong>
            <span>{realtimeMessage}</span>
            {activeRealtimeVoiceOption && <small>{activeRealtimeRoute?.label} · {activeRealtimeVoiceOption.label} · {activeRealtimeVoiceOption.detail}</small>}
          </div>
          <div className="line-test-result">
            <strong>{realtimeSession?.currentIntent ?? "待识别"}</strong>
            <span>{realtimeSession?.currentNode ?? realtimePipeline.nextStep}</span>
            {realtimeSession && <small>打断 {realtimeSession.interruptions} 次 · ¥{realtimeSession.costEstimatePerMinute.toFixed(2)} / 分钟</small>}
          </div>
          <div className="button-row realtime-actions">
            <button className="secondary-button" disabled={!realtimeSession || realtimeSession.status !== "speaking"} onClick={() => void interruptRealtimePlayback()} type="button">
              <ShieldAlert size={16} />
              打断 TTS
            </button>
            <button className="secondary-button" disabled={!realtimeSession || realtimeSession.status !== "speaking"} onClick={() => void completeRealtimePlayback()} type="button">
              <CheckCircle2 size={16} />
              播放完成
            </button>
          </div>
        </div>
        {realtimeLastReply && <div className="form-result">AI：{realtimeLastReply}</div>}
        {realtimeSession && (
          <div className="realtime-event-list">
            {realtimeSession.events.slice(-8).map((event) => (
              <div className="timeline-item" key={event.id}>
                <span>{event.actor}</span>
                <strong>{event.type} · {event.status}</strong>
                <p>{event.text}</p>
                <small>
                  {event.detail} {event.latencyMs ? `· ${event.latencyMs} ms` : ""}
                </small>
              </div>
            ))}
          </div>
        )}
        {realtimeLiveEvents.score && (
          <div className="realtime-score-board">
            <div className="line-test-result">
              <strong>{realtimeLiveEvents.score.score} 分</strong>
              <span>{realtimeLiveEvents.score.summary}</span>
              <small>{realtimeLiveEvents.score.callId ? `Call ${realtimeLiveEvents.score.callId.slice(0, 8)}` : "最近真实通话"}</small>
            </div>
            <div className="realtime-score-grid">
              {realtimeLiveEvents.score.metrics.map((metric) => (
                <div className="line-preflight-step" key={metric.name}>
                  <span className={`line-preflight-badge is-${metric.status}`}>{metric.score}</span>
                  <div>
                    <strong>{metric.name}</strong>
                    <em>{metric.detail}</em>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="realtime-event-list">
          {realtimeLiveEvents.events.length === 0 && <div className="empty-state compact">暂无真实通话事件。</div>}
          {realtimeLiveEvents.events.slice(-10).map((event) => (
            <div className="timeline-item" key={event.id}>
              <span>{event.callId ? event.callId.slice(0, 8) : "bridge"}</span>
              <strong>
                {realtimeLiveEventTitle(event.type)}
                {event.strategy ? ` · ${event.strategy}` : ""}
              </strong>
              <p>{event.reply || event.text || event.detail || event.type}</p>
              <small>
                {event.at ? new Date(event.at).toLocaleString("zh-CN", { hour12: false }) : "无时间"}
                {event.latencyMs ? ` · ${event.latencyMs} ms` : ""}
              </small>
            </div>
          ))}
        </div>
      </article>
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
          <MetricCard
            icon={<Radio size={20} />}
            label="声音库"
            value={availableCloneVoiceRecords.length + (systemVoices.length || voiceOverview.systemVoices)}
            detail={`复刻 ${availableCloneVoiceRecords.length} / 系统 ${systemVoices.length || voiceOverview.systemVoices}`}
            tone="green"
          />
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
                  <small className="voice-library-count">
                    声音库 · 已复刻 {availableCloneVoiceRecords.length} · 系统 {systemVoices.length || voiceOverview.systemVoices}
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
                        <td>
                          <strong>{record.clonedVoiceName}</strong>
                          <small>{record.status === "可用" ? "已进入声音库" : "复刻记录"}</small>
                        </td>
                        <td className="voice-id-cell">
                          {record.externalVoiceId ? <code>{record.externalVoiceId}</code> : <span className="muted-cell">未生成</span>}
                        </td>
                        <td>{record.sampleCount} 条 / {record.sampleMinutes} 分钟</td>
                        <td>{record.engine}</td>
                        <td>
                          <span className={`voice-record-status ${record.status === "可用" ? "is-ready" : record.status === "失败" ? "is-failed" : ""}`}>
                            {record.status}
                          </span>
                        </td>
                        <td>
                          {record.previewAudioUrl ? (
                            <audio controls preload="none" src={apiAssetUrl(record.previewAudioUrl)} />
                          ) : (
                            "暂无"
                          )}
                        </td>
                        <td className="voice-result-cell">{record.result}</td>
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

  function renderAuthGate() {
    return (
      <main className="auth-shell">
        <section className="auth-panel">
          <div className="auth-brand">
            <span className="brand-mark">
              <Sparkles size={20} />
            </span>
            <div>
              <strong>商家AI获客</strong>
              <small>客户工作台</small>
            </div>
          </div>
          <div className="auth-heading">
            <p>{authMode === "login" ? "客户账号登录" : "客户开通申请"}</p>
            <h1>{authMode === "login" ? "登录进入获客工作台" : "申请开通客户账号"}</h1>
          </div>
          {authMode === "login" ? (
            <form className="auth-form" onSubmit={submitLogin}>
              <label>
                登录账号
                <input
                  autoComplete="username"
                  value={loginForm.identifier}
                  onChange={(event) => setLoginForm({ ...loginForm, identifier: event.target.value })}
                />
              </label>
              <label>
                密码
                <input
                  autoComplete="current-password"
                  type="password"
                  value={loginForm.password}
                  onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })}
                />
              </label>
              <button className="primary-button" disabled={isSubmittingAuth} type="submit">
                <KeyRound size={16} />
                {isSubmittingAuth ? "登录中" : "登录"}
              </button>
            </form>
          ) : (
            <form className="auth-form" onSubmit={submitRegistrationRequest}>
              <label>
                公司名称
                <input
                  value={registrationForm.companyName}
                  onChange={(event) => setRegistrationForm({ ...registrationForm, companyName: event.target.value })}
                />
              </label>
              <label>
                商户/项目
                <input
                  value={registrationForm.projectName}
                  onChange={(event) => setRegistrationForm({ ...registrationForm, projectName: event.target.value })}
                />
              </label>
              <label>
                联系人
                <input
                  value={registrationForm.contactName}
                  onChange={(event) => setRegistrationForm({ ...registrationForm, contactName: event.target.value })}
                />
              </label>
              <label>
                联系手机号
                <input
                  value={registrationForm.contactPhone}
                  onChange={(event) => setRegistrationForm({ ...registrationForm, contactPhone: event.target.value })}
                />
              </label>
              <label>
                登录账号
                <input
                  value={registrationForm.desiredUsername}
                  onChange={(event) => setRegistrationForm({ ...registrationForm, desiredUsername: event.target.value })}
                />
              </label>
              <label>
                联系邮箱
                <input
                  value={registrationForm.contactEmail}
                  onChange={(event) => setRegistrationForm({ ...registrationForm, contactEmail: event.target.value })}
                />
              </label>
              <button className="primary-button" disabled={isSubmittingAuth} type="submit">
                <CheckCircle2 size={16} />
                {isSubmittingAuth ? "提交中" : "提交申请"}
              </button>
            </form>
          )}
          {authMessage && <p className="auth-message">{authMessage}</p>}
          <div className="auth-switch">
            <span>{authMode === "login" ? "还没有客户账号？" : "已有账号？"}</span>
            <button
              className="secondary-button"
              onClick={() => {
                setAuthMode(authMode === "login" ? "register" : "login");
                setAuthMessage("");
              }}
              type="button"
            >
              {authMode === "login" ? "申请开通" : "返回登录"}
            </button>
          </div>
        </section>
      </main>
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

  function renderCollectorWorkspace() {
    const latestRun = collectionRuns[0];
    const providerLabel = (provider: string) =>
      provider === "amap"
        ? "高德地图"
        : provider === "baidu"
          ? "百度地图"
          : provider === "tencent"
            ? "腾讯位置服务"
            : provider === "public_web"
              ? "公开网页"
              : provider;

    return (
      <>
        <section className="metrics">
          <MetricCard label="采集任务" value={collectionTasks.length} detail="服务端执行" />
          <MetricCard label="原始线索" value={rawLeadRecords.length} detail="含地图点位" tone="green" />
          <MetricCard label="最近入库" value={latestRun?.insertedCount ?? 0} detail={latestRun?.status ?? "待运行"} tone="amber" />
          <MetricCard label="可外呼线索" value={callableLeads.length} detail="有电话记录" tone="rose" />
        </section>

        <section className="content-grid">
          <article className="panel">
            <div className="panel-title">
              <div>
                <p>地图点位采集</p>
                <h2>新建采集任务</h2>
              </div>
              <Search size={22} />
            </div>
            <form className="form-grid" onSubmit={submitCollectionTask}>
              <label className="wide">
                任务名称
                <input
                  value={collectionForm.name}
                  onChange={(event) => setCollectionForm({ ...collectionForm, name: event.target.value })}
                />
              </label>
              <label>
                数据源
                <select
                  value={collectionForm.provider}
                  onChange={(event) => setCollectionForm({ ...collectionForm, provider: event.target.value })}
                >
                  <option value="amap">高德地图</option>
                  <option value="baidu">百度地图</option>
                  <option value="tencent">腾讯位置服务</option>
                  <option value="public_web">公开网页（无需 Key/登录）</option>
                </select>
              </label>
              <label>
                每组目标数
                <input
                  min={1}
                  max={200}
                  type="number"
                  value={collectionForm.targetPerKeyword}
                  onChange={(event) => setCollectionForm({ ...collectionForm, targetPerKeyword: Number(event.target.value) })}
                />
              </label>
              <label>
                城市
                <input
                  placeholder="南昌，杭州"
                  value={collectionForm.cities}
                  onChange={(event) => setCollectionForm({ ...collectionForm, cities: event.target.value })}
                />
              </label>
              <label>
                品类
                <input
                  placeholder="餐饮，美业"
                  value={collectionForm.categories}
                  onChange={(event) => setCollectionForm({ ...collectionForm, categories: event.target.value })}
                />
              </label>
              <label className="wide">
                关键词
                <input
                  placeholder="团购，到店，附近商家"
                  value={collectionForm.keywords}
                  onChange={(event) => setCollectionForm({ ...collectionForm, keywords: event.target.value })}
                />
              </label>
              <button className="primary-button" disabled={isCreatingCollectionTask} type="submit">
                <CheckCircle2 size={16} />
                {isCreatingCollectionTask ? "创建中" : "创建采集任务"}
              </button>
            </form>
            <p className="form-result">{collectionMessage}</p>
          </article>

          <article className="panel">
            <div className="panel-title">
              <div>
                <p>采集任务</p>
                <h2>运行队列</h2>
              </div>
              <ClipboardList size={22} />
            </div>
            <div className="task-list">
              {collectionTasks.length === 0 && <div className="empty-state">暂无采集任务，先从左侧创建。</div>}
              {collectionTasks.map((task) => (
                <div className="task-row" key={task.id}>
                  <span>{providerLabel(task.provider)}</span>
                  <div>
                    <strong>{task.name}</strong>
                    <small>
                      {task.cities.join("、")} · {task.categories.join("、")} · 每组 {task.targetPerKeyword}
                    </small>
                  </div>
                  <em>{task.status}</em>
                  <button
                    className="row-action"
                    disabled={runningCollectionTaskId === task.id}
                    onClick={() => runCollectionTask(task.id)}
                    type="button"
                  >
                    {runningCollectionTaskId === task.id ? "运行中" : "运行"}
                  </button>
                </div>
              ))}
            </div>
          </article>
        </section>

        <section className="content-grid lower">
          <article className="panel">
            <div className="panel-title">
              <div>
                <p>采集运行</p>
                <h2>最近结果</h2>
              </div>
              <Activity size={22} />
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>来源</th>
                    <th>状态</th>
                    <th>抓取</th>
                    <th>入库</th>
                    <th>重复</th>
                    <th>失败</th>
                  </tr>
                </thead>
                <tbody>
                  {collectionRuns.length === 0 && (
                    <tr>
                      <td colSpan={6}>
                        <span className="empty-state">暂无运行记录。</span>
                      </td>
                    </tr>
                  )}
                  {collectionRuns.map((run) => (
                    <tr key={run.id}>
                      <td>{providerLabel(run.provider)}</td>
                      <td>{run.status}</td>
                      <td>{run.fetchedCount}</td>
                      <td>{run.insertedCount}</td>
                      <td>{run.duplicateCount}</td>
                      <td>{run.failedCount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>

          <article className="panel">
            <div className="panel-title">
              <div>
                <p>原始线索</p>
                <h2>采集入库明细</h2>
              </div>
              <Database size={22} />
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>商家</th>
                    <th>城市</th>
                    <th>来源</th>
                    <th>电话</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {rawLeadRecords.length === 0 && (
                    <tr>
                      <td colSpan={5}>
                        <span className="empty-state">暂无原始采集记录。</span>
                      </td>
                    </tr>
                  )}
                  {rawLeadRecords.slice(0, 80).map((record) => (
                    <tr key={record.id}>
                      <td>
                        <strong>{record.name}</strong>
                        <small>{record.category || "-"}</small>
                      </td>
                      <td>{record.city || "-"}</td>
                      <td>{providerLabel(record.provider)}</td>
                      <td>{record.phone || "-"}</td>
                      <td>
                        <span className="badge">{record.importStatus}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
    const routeStatus = routeHealthSummary(telephonyHealth, telephonyPreflight);
    const serverRegistrationTarget = serverSipRegistrationTarget(telephonyConfig);
    const deviceDiscoveryLabel = voiceGatewayDiscoveryLabel(asteriskSidecarStatus);
    const deviceDiscoveryDetail = voiceGatewayDiscoveryDetail(asteriskSidecarStatus);
    const discoveredGatewayAddress =
      asteriskSidecarStatus?.voiceGatewayDiscovery?.host && asteriskSidecarStatus.voiceGatewayDiscovery.sipPort
        ? `${asteriskSidecarStatus.voiceGatewayDiscovery.host}:${asteriskSidecarStatus.voiceGatewayDiscovery.sipPort}`
        : asteriskSidecarStatus?.customerDelivery?.gatewayAddress || "等待自动检测";
    const customerRouteNextStep =
      routeStatus.status === "pass"
        ? "线路检测通过，可以创建任务或进入实时监听。"
        : routeStatus.status === "warn"
          ? "后台正在处理线路联通，完成后客户工作台会自动显示可用状态。"
          : "线路暂未接通，请等待服务人员在后台完成接入。";
    const routeCheckedAt = new Date(telephonyPreflight.checkedAt).toLocaleString("zh-CN", { hour12: false });
    const monitorCalls = liveCalls.length > 0 ? liveCalls : callRecords.slice(0, 6);

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
                  <p>外呼线路</p>
                  <h2>线路是否通畅</h2>
                </div>
              </div>
              <div className={`route-status-card is-${routeStatus.status}`}>
                <div className="route-status-main">
                  <span className={`line-preflight-badge is-${routeStatus.status}`}>{routeStatus.status.toUpperCase()}</span>
                  <div>
                    <strong>{routeStatus.title}</strong>
                    <small>{routeStatus.detail}</small>
                  </div>
                </div>
                <div className="route-status-grid">
                  <div>
                    <span>线路状态</span>
                    <strong>{telephonyReadinessLabel(telephonyHealth, telephonyPreflight)}</strong>
                  </div>
                  <div>
                    <span>后台处理</span>
                    <strong>{routeStatus.action}</strong>
                  </div>
                </div>
              </div>
              <div className={`customer-route-summary is-${routeStatus.status}`}>
                <div>
                  <span>已绑定线路</span>
                  <strong>{telephonyConfig.voiceGatewayProfile.label}</strong>
                  <small>客户前端只展示线路状态；设备、账号、网关和外呼策略由后台维护。</small>
                </div>
                <div>
                  <span>最近检测</span>
                  <strong>{telephonyPreflightSummary(telephonyPreflight)}</strong>
                  <small>{routeCheckedAt}</small>
                </div>
                <div>
                  <span>下一步</span>
                  <strong>{customerRouteNextStep}</strong>
                </div>
              </div>
              <div className={`device-onboarding-card is-${routeStatus.status}`}>
                <div className="device-onboarding-header">
                  <div>
                    <span>现场设备对接</span>
                    <strong>{telephonyHealth.trunkReachable ? "语音网关已注册到云端" : "语音网关等待注册到云端"}</strong>
                    <small>
                      交付人员把现场语音网关注册到云端后，客户前端只做状态验收；未注册前不会进入真实拨号。
                    </small>
                  </div>
                  <div className="device-onboarding-actions">
                    <button className="secondary-button" disabled={!isDesktopClient} onClick={() => void refreshAsteriskSidecarStatus()} type="button">
                      <RefreshCw size={16} />
                      {isDesktopClient ? "自动检测现场设备" : "桌面客户端检测"}
                    </button>
                    <button className="secondary-button" disabled={isCheckingTelephony} onClick={refreshTelephonyStatus} type="button">
                      <RefreshCw size={16} className={isCheckingTelephony ? "spin" : ""} />
                      刷新线路状态
                    </button>
                  </div>
                </div>
                <div className="device-onboarding-grid">
                  <div>
                    <span>自动检测</span>
                    <strong>{deviceDiscoveryLabel}</strong>
                    <small>{deviceDiscoveryDetail}</small>
                  </div>
                  <div>
                    <span>本地发现地址</span>
                    <strong>{discoveredGatewayAddress}</strong>
                    <small>如果客户更换网络或换设备，点击自动检测重新识别。</small>
                  </div>
                  <div>
                    <span>云端注册目标</span>
                    <strong>{serverRegistrationTarget}</strong>
                    <small>交付人员在语音网关后台把 SIP Server / Registrar 指向这个地址。</small>
                  </div>
                  <div>
                    <span>SIP账号</span>
                    <strong>{telephonyConfig.voiceGatewayProfile.trunkName || telephonyConfig.asteriskTrunkName}</strong>
                    <small>鉴权密码由交付人员配置，不在客户前端展示。</small>
                  </div>
                </div>
                <div className="device-onboarding-steps">
                  <span>1. 设备通电、插 SIM 卡并接入客户网络。</span>
                  <span>2. 客户端点击自动检测，确认现场设备可被发现。</span>
                  <span>3. 交付人员在语音网关后台填写云端注册目标和 SIP 账号。</span>
                  <span>4. 云端收到注册后，本页自动变为线路通畅，再进入单号试拨。</span>
                </div>
              </div>
              {telephonyConfig.asteriskDeploymentMode === "server" ? (
                <div className={`asterisk-sidecar-strip is-${telephonyHealth.authenticated ? "pass" : telephonyHealth.amiReachable ? "warn" : "fail"}`}>
                  <div className="asterisk-sidecar-main">
                    <span className={`line-preflight-badge is-${telephonyHealth.authenticated ? "pass" : telephonyHealth.amiReachable ? "warn" : "fail"}`}>
                      {telephonyHealth.authenticated ? "PASS" : telephonyHealth.amiReachable ? "WARN" : "FAIL"}
                    </span>
                    <div>
                      <strong>服务器 Asterisk：{telephonyHealth.authenticated ? "AMI 已登录" : telephonyHealth.amiReachable ? "AMI 可达" : "待连接"}</strong>
                      <small>{telephonyConfig.voiceGatewayProfile.label} 主动注册到云端 Asterisk；客户电脑不再依赖本机 Asterisk runtime。</small>
                    </div>
                  </div>
                  <div className="asterisk-sidecar-meta">
                    <div>
                      <span>后端 AMI</span>
                      <strong>{serverAmiDisplay(telephonyConfig)}</strong>
                    </div>
                    <div>
                      <span>SIP 注册</span>
                      <strong>{serverSipRegistrationTarget(telephonyConfig)}</strong>
                    </div>
                    <div>
                      <span>交付设备</span>
                      <strong>{telephonyConfig.voiceGatewayProfile.label}</strong>
                    </div>
                    <div>
                      <span>通道池</span>
                      <strong>{telephonyConfig.voiceGatewayProfile.maxChannels || telephonyConfig.asteriskMaxChannels} 路</strong>
                    </div>
                  </div>
                  <div className="asterisk-sidecar-actions">
                    <button className="secondary-button" disabled={isCheckingTelephony} onClick={refreshTelephonyStatus} type="button">
                      <RefreshCw size={16} className={isCheckingTelephony ? "spin" : ""} />
                      刷新服务器线路
                    </button>
                  </div>
                </div>
              ) : (
              <div className={`asterisk-sidecar-strip is-${asteriskSidecarBadgeStatus(asteriskSidecarStatus)}`}>
                <div className="asterisk-sidecar-main">
                  <span className={`line-preflight-badge is-${asteriskSidecarBadgeStatus(asteriskSidecarStatus)}`}>
                    {asteriskSidecarStatus?.running ? "PASS" : asteriskSidecarStatus?.runtimeFound ? "WARN" : "FAIL"}
                  </span>
                  <div>
                    <strong>客户端内置 Asterisk：{isDesktopClient ? asteriskSidecarStatusText(asteriskSidecarStatus) : "仅桌面客户端可用"}</strong>
                    <small>
                      {isDesktopClient
                        ? asteriskSidecarStatus?.nextStep ?? "正在等待客户端侧线路运行时检测。"
                        : "网页预览只用于查看功能；客户交付时由桌面客户端管理 Asterisk 和本机 AMI 配置。"}
                    </small>
                  </div>
                </div>
                <div className="asterisk-sidecar-meta">
                  <div>
                    <span>AMI</span>
                    <strong>
                      {asteriskSidecarStatus ? `${asteriskSidecarStatus.amiHost}:${asteriskSidecarStatus.amiPort}` : "127.0.0.1:5038"}
                    </strong>
                  </div>
                  <div>
                    <span>语音网关</span>
                    <strong>
                      {asteriskSidecarStatus
                        ? `${asteriskSidecarStatus.voiceGatewayHost ?? asteriskSidecarStatus.uc100Host}:${
                            asteriskSidecarStatus.voiceGatewaySipPort ?? asteriskSidecarStatus.uc100SipPort
                          }`
                        : `${telephonyConfig.voiceGatewayProfile.host}:${telephonyConfig.voiceGatewayProfile.sipPort}`}
                    </strong>
                  </div>
                  <div>
                    <span>档案</span>
                    <strong>{asteriskSidecarStatus?.voiceGatewayLabel ?? telephonyConfig.voiceGatewayProfile.label}</strong>
                  </div>
                  <div>
                    <span>配置</span>
                    <strong>{asteriskSidecarStatus?.backendEnvReady ? "已生成" : "待生成"}</strong>
                  </div>
                </div>
                <div className="asterisk-sidecar-actions">
                  <button
                    className="primary-button"
                    disabled={
                      !isDesktopClient ||
                      isStartingAsteriskSidecar ||
                      Boolean(asteriskSidecarStatus?.running) ||
                      Boolean(asteriskSidecarStatus && !asteriskSidecarStatus.runtimeFound)
                    }
                    onClick={startAsteriskSidecar}
                    type="button"
                  >
                    <Zap size={16} />
                    {asteriskSidecarStatus?.running
                      ? "已启动"
                      : isStartingAsteriskSidecar
                        ? "启动中"
                        : asteriskSidecarStatus && !asteriskSidecarStatus.runtimeFound
                          ? "缺少运行时"
                          : "启动内置Asterisk"}
                  </button>
                  <button
                    className="secondary-button icon-only"
                    disabled={!isDesktopClient || isStartingAsteriskSidecar}
                    onClick={() => void refreshAsteriskSidecarStatus()}
                    title="刷新内置 Asterisk 状态"
                    type="button"
                  >
                    <RefreshCw size={16} />
                  </button>
                </div>
              </div>
              )}
              <div className={`customer-delivery-card is-${
                telephonyConfig.asteriskDeploymentMode === "server"
                  ? telephonyHealth.authenticated && telephonyHealth.trunkReachable
                    ? "pass"
                    : telephonyHealth.amiReachable
                      ? "warn"
                      : "fail"
                  : isDesktopClient
                    ? asteriskCustomerDeliveryStatus(asteriskSidecarStatus)
                    : "warn"
              }`}>
                <div className="customer-delivery-copy">
                  <span>客户交付状态</span>
                  <strong>
                    {telephonyConfig.asteriskDeploymentMode === "server"
                      ? telephonyHealth.readyForTestCall
                        ? "服务器线路已就绪"
                        : "线路待现场联通"
                      : isDesktopClient
                      ? asteriskSidecarStatus?.customerDelivery?.title ?? "等待客户端检测语音网关"
                      : "网页预览不能作为客户现场运行方式"}
                  </strong>
                  <small>
                    {telephonyConfig.asteriskDeploymentMode === "server"
                      ? "语音网关、Asterisk 和媒体桥由交付人员预置；客户工作台只展示状态、预检和单号试拨验收。"
                      : isDesktopClient
                      ? asteriskSidecarStatus?.customerDelivery?.message ??
                        "桌面客户端会负责发现语音网关、生成 Asterisk 配置并输出后端环境。"
                      : "交付给客户时必须安装桌面客户端；设备发现、Asterisk、AMI 和本机媒体桥都在客户端内完成。"}
                  </small>
                </div>
                <div className="customer-delivery-meta">
                  <div>
                    <span>{telephonyConfig.asteriskDeploymentMode === "server" ? "UC100 注册目标" : "当前绑定"}</span>
                    <strong>
                      {telephonyConfig.asteriskDeploymentMode === "server"
                        ? serverSipRegistrationTarget(telephonyConfig)
                        : asteriskSidecarStatus?.customerDelivery?.gatewayAddress ||
                          `${telephonyConfig.voiceGatewayProfile.host}:${telephonyConfig.voiceGatewayProfile.sipPort}`}
                    </strong>
                  </div>
                  <div>
                    <span>自动匹配</span>
                    <strong>
                      {telephonyConfig.asteriskDeploymentMode === "server"
                        ? telephonyHealth.trunkReachable
                          ? "已注册"
                          : "待注册"
                        : asteriskSidecarStatus?.customerDelivery?.discoveryStatus === "updated"
                        ? "已重绑"
                        : asteriskSidecarStatus?.customerDelivery?.discoveryStatus === "current"
                          ? "已确认"
                          : asteriskSidecarStatus?.customerDelivery?.discoveryStatus === "not_found"
                            ? "未发现"
                            : isDesktopClient
                              ? "待检测"
                              : "桌面端执行"}
                    </strong>
                  </div>
                  <div>
                    <span>{telephonyConfig.asteriskDeploymentMode === "server" ? "设备注册状态" : "上一地址"}</span>
                    <strong>
                      {telephonyConfig.asteriskDeploymentMode === "server"
                        ? telephonyHealth.trunkReachable
                          ? "已注册到云端"
                          : "未收到注册"
                        : asteriskSidecarStatus?.customerDelivery?.previousGatewayAddress || "无变更"}
                    </strong>
                  </div>
                </div>
                <div className="customer-delivery-actions">
                  {(telephonyConfig.asteriskDeploymentMode === "server"
                    ? [
                        `在 ${telephonyConfig.voiceGatewayProfile.label} 后台把 SIP Server/Registrar 指向 ${serverSipRegistrationTarget(telephonyConfig)}。`,
                        `SIP 用户名/鉴权账号使用 ${telephonyConfig.voiceGatewayProfile.trunkName || telephonyConfig.asteriskTrunkName}；密码由交付人员在服务器端配置。`,
                        "单号试拨必须确认蜂窝侧、媒体链路和 AI 首句。",
                        "批量真实外呼保持关闭，直到单号验证稳定。",
                      ]
                    : isDesktopClient
                    ? asteriskSidecarStatus?.customerDelivery?.actionItems ?? ["刷新客户端线路状态，确认设备绑定和 Asterisk 运行状态。"]
                    : ["安装并打开桌面客户端。", "让客户电脑和语音网关接入同一局域网。", "在客户端中刷新/启动内置 Asterisk。"]
                  ).map((item) => (
                    <span key={item}>{item}</span>
                  ))}
                </div>
              </div>
              {telephonyConfig.asteriskDeploymentMode !== "server" && asteriskSidecarStatus && (
                <div className="asterisk-sidecar-checks">
                  {asteriskSidecarStatus.checks.map((check) => (
                    <div className="asterisk-sidecar-check" key={check.key}>
                      <span className={`line-preflight-badge is-${check.status}`}>{telephonyPreflightStatusText(check.status)}</span>
                      <div>
                        <strong>{check.label}</strong>
                        <small>{check.detail}</small>
                      </div>
                    </div>
                  ))}
                </div>
              )}
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
                  <strong>{telephonyConfig.voiceGatewayProfile.trunkName || telephonyConfig.asteriskTrunkName || "待配置"}</strong>
                </div>
                <div>
                  <span>通道上限</span>
                  <strong>{telephonyConfig.voiceGatewayProfile.maxChannels || telephonyHealth.maxChannels || telephonyConfig.asteriskMaxChannels} 路</strong>
                </div>
                <div>
                  <span>拨号开关</span>
                  <strong>{telephonyConfig.asteriskLiveCallEnabled ? "单号试拨" : "未开启"}</strong>
                </div>
              </div>
              <div className="line-preflight gateway-profile-strip">
                <div className="line-preflight-header">
                  <div>
                    <span>已绑定线路档案</span>
                    <strong>{telephonyConfig.voiceGatewayProfile.label}</strong>
                  </div>
                  <small>{telephonyHealth.readyForTestCall ? "可单号试拨" : "待线路联通"}</small>
                </div>
                <div className="line-health-grid">
                  <div>
                    <span>设备</span>
                    <strong>{telephonyConfig.voiceGatewayProfile.model}</strong>
                  </div>
                  <div>
                    <span>线路池</span>
                    <strong>{telephonyConfig.voiceGatewayProfile.maxChannels || telephonyConfig.asteriskMaxChannels} 路</strong>
                  </div>
                  <div>
                    <span>拨号</span>
                    <strong>{telephonyConfig.asteriskLiveCallEnabled ? "单号试拨开启" : "待验收开启"}</strong>
                  </div>
                  <div>
                    <span>批量外呼</span>
                    <strong>{telephonyConfig.asteriskBulkCallEnabled ? "已开启" : "关闭"}</strong>
                  </div>
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
              {telephonyTestResult?.cellularDiagnostic && (
                <div className={`cellular-diagnostic is-${telephonyTestResult.cellularDiagnostic.status}`}>
                  <div>
                    <span>蜂窝线路诊断</span>
                    <strong>{telephonyTestResult.cellularDiagnostic.title}</strong>
                    <small>{telephonyDiagnosticStatusText(telephonyTestResult.cellularDiagnostic.status)} · {telephonyTestResult.cellularDiagnostic.stage}</small>
                  </div>
                  <p>{telephonyTestResult.cellularDiagnostic.summary}</p>
                  <p>{telephonyTestResult.cellularDiagnostic.detail}</p>
                  <div className="cellular-action-list">
                    {telephonyTestResult.cellularDiagnostic.actionItems.slice(0, 4).map((item) => (
                      <span key={item}>{item}</span>
                    ))}
                  </div>
                  {telephonyTestResult.cellularDiagnostic.technicalDetail && (
                    <code>{telephonyTestResult.cellularDiagnostic.technicalDetail}</code>
                  )}
                  <div className="button-row cellular-actions">
                    <button className="secondary-button" disabled={isRecoveringTelephony} onClick={() => void recoverTelephonyLine()} type="button">
                      <RefreshCw size={16} className={isRecoveringTelephony ? "spin" : ""} />
                      {isRecoveringTelephony ? "恢复中" : "恢复线路"}
                    </button>
                  </div>
                </div>
              )}
              {telephonyLineRecovery && (
                <div className={`cellular-recovery-result is-${telephonyLineRecovery.status}`}>
                  <div>
                    <span>恢复结果</span>
                    <strong>{telephonyLineRecovery.summary}</strong>
                    <small>{telephonyLineRecovery.nextStep}</small>
                  </div>
                  <div className="cellular-command-list">
                    {telephonyLineRecovery.commands.slice(0, 5).map((command) => (
                      <span key={command.command}>
                        {command.ok ? "PASS" : "WARN"} · {command.command}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </article>

            <article className="panel span-2 realtime-monitor-panel">
              <div className="panel-title">
                <div>
                  <p>Live Monitor</p>
                  <h2>实时监听聊天</h2>
                </div>
                <button className="secondary-button" onClick={loadData} type="button">
                  <RefreshCw size={16} className={isLoading ? "spin" : ""} />
                  刷新
                </button>
              </div>
              <div className="realtime-monitor-layout">
                <div className="monitor-call-list" aria-label="实时通话客户">
                  {monitorCalls.length === 0 && <span className="empty-state">暂无实时通话，创建外呼任务后点击启动。</span>}
                  {monitorCalls.map((record) => (
                    <button
                      className={record.id === selectedLiveCall?.id ? "is-active" : ""}
                      key={record.id}
                      onClick={() => setSelectedLiveCallId(record.id)}
                      type="button"
                    >
                      <span>{record.needHandoff ? "接管" : record.recallAt ? "重拨" : "监听"}</span>
                      <strong>{record.merchantName}</strong>
                      <small>
                        {record.phone ?? "无电话"} · {formatDuration(record.durationSeconds)} · {record.currentNode}
                      </small>
                    </button>
                  ))}
                </div>
                <div className="monitor-chat-panel">
                  <div className="monitor-chat-header">
                    <div>
                      <span>{selectedLiveCall?.aiSeat ?? "AI坐席"}</span>
                      <strong>{selectedLiveCall?.merchantName ?? "选择客户查看监听"}</strong>
                      <small>{selectedLiveCall?.outcome ?? "等待通话"}</small>
                    </div>
                    {selectedLiveCall && (
                      <span className={`intent-pill intent-${selectedLiveCall.intentLevel.toLowerCase()}`}>
                        {selectedLiveCall.intentLevel}
                      </span>
                    )}
                  </div>
                  <div className="monitor-chat-stream">
                    {selectedLiveCallMessages.map((message, index) => (
                      <div className={`monitor-message is-${message.speaker}`} key={`${message.label}-${index}`}>
                        <span>{message.label}</span>
                        <p>{message.text}</p>
                      </div>
                    ))}
                  </div>
                  <div className="monitor-ai-next">
                    <span>当前话术</span>
                    <strong>{activeScript?.name ?? "未选择话术"}</strong>
                    <p>{activeScript?.objection || activeScript?.qualification || "保存话术后会在这里显示实时应答依据。"}</p>
                  </div>
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
                  并发数量
                  <input
                    min={1}
                    max={50}
                    type="number"
                    value={outboundForm.concurrency}
                    onChange={(event) => setOutboundForm({ ...outboundForm, concurrency: Number(event.target.value) })}
                  />
                </label>
                <label>
                  日期
                  <input
                    type="datetime-local"
                    value={outboundForm.scheduledAt}
                    onChange={(event) => setOutboundForm({ ...outboundForm, scheduledAt: event.target.value })}
                  />
                </label>
                <button className="primary-button" disabled={selectedCallableLeadIds.length === 0} type="submit">
                  <Plus size={16} />
                  创建外呼任务
                </button>
              </form>

              <div className="lead-picker">
                <div className="section-caption">
                  <div>
                    <strong>选择外呼线索</strong>
                    <small>{selectedCallableLeadIds.length}/{callableLeads.length} 个已选</small>
                  </div>
                  <button className="secondary-button" onClick={toggleAllCallableLeads} type="button">
                    <CheckCircle2 size={16} />
                    {allCallableSelected ? "清空" : "全选"}
                  </button>
                </div>
                <LeadTable leads={callableLeads} selectable selectedLeadIds={selectedLeadIds} onToggleLead={toggleLead} />
              </div>
              <p className="form-result">{outboundTaskMessage}</p>
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
              <div className="script-editor">
                <div className="section-caption">
                  <div>
                    <strong>{scriptDraft.name || "未命名话术"}</strong>
                    <small>{scriptDraft.isActive ? "启用中" : "未启用"}</small>
                  </div>
                  <div className="button-row">
                    <button className="secondary-button" disabled={isGeneratingScript} onClick={generateScriptDraft} type="button">
                      <Sparkles size={16} />
                      {isGeneratingScript ? "生成中" : "AI生成"}
                    </button>
                    <button className="primary-button" disabled={isSavingScript} onClick={() => void saveScriptDraft()} type="button">
                      <CheckCircle2 size={16} />
                      {isSavingScript ? "保存中" : "保存话术"}
                    </button>
                  </div>
                </div>
                <div className="script-editor-grid">
                  <label>
                    话术名称
                    <input
                      value={scriptDraft.name}
                      onChange={(event) => setScriptDraft({ ...scriptDraft, name: event.target.value })}
                    />
                  </label>
                  <label className="script-active-toggle">
                    <input
                      checked={scriptDraft.isActive}
                      onChange={(event) => setScriptDraft({ ...scriptDraft, isActive: event.target.checked })}
                      type="checkbox"
                    />
                    启用这套话术
                  </label>
                  <label>
                    开场白
                    <textarea
                      value={scriptDraft.opening}
                      onChange={(event) => setScriptDraft({ ...scriptDraft, opening: event.target.value })}
                    />
                  </label>
                  <label>
                    需求确认
                    <textarea
                      value={scriptDraft.qualification}
                      onChange={(event) => setScriptDraft({ ...scriptDraft, qualification: event.target.value })}
                    />
                  </label>
                  <label>
                    异议处理
                    <textarea
                      value={scriptDraft.objection}
                      onChange={(event) => setScriptDraft({ ...scriptDraft, objection: event.target.value })}
                    />
                  </label>
                  <label>
                    收口动作
                    <textarea
                      value={scriptDraft.closing}
                      onChange={(event) => setScriptDraft({ ...scriptDraft, closing: event.target.value })}
                    />
                  </label>
                </div>
                <p className="form-result">{scriptMessage}</p>
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
                <button className="primary-button" disabled={isSavingRule} onClick={() => void saveRecallRuleDraft()} type="button">
                  <CheckCircle2 size={16} />
                  {isSavingRule ? "保存中" : "保存规则"}
                </button>
              </div>
              <div className="rule-editor-grid">
                <label className="wide">
                  规则名称
                  <input value={ruleDraft.name} onChange={(event) => setRuleDraft({ ...ruleDraft, name: event.target.value })} />
                </label>
                <label>
                  未接后重拨
                  <input
                    min={1}
                    type="number"
                    value={ruleDraft.noAnswerIntervalMinutes}
                    onChange={(event) => setRuleDraft({ ...ruleDraft, noAnswerIntervalMinutes: Number(event.target.value) })}
                  />
                </label>
                <label>
                  忙线后重拨
                  <input
                    min={1}
                    type="number"
                    value={ruleDraft.busyIntervalMinutes}
                    onChange={(event) => setRuleDraft({ ...ruleDraft, busyIntervalMinutes: Number(event.target.value) })}
                  />
                </label>
                <label>
                  最大次数
                  <input
                    min={1}
                    max={20}
                    type="number"
                    value={ruleDraft.maxAttempts}
                    onChange={(event) => setRuleDraft({ ...ruleDraft, maxAttempts: Number(event.target.value) })}
                  />
                </label>
                <label>
                  静默开始
                  <input
                    type="time"
                    value={ruleDraft.quietStart}
                    onChange={(event) => setRuleDraft({ ...ruleDraft, quietStart: event.target.value })}
                  />
                </label>
                <label>
                  静默结束
                  <input
                    type="time"
                    value={ruleDraft.quietEnd}
                    onChange={(event) => setRuleDraft({ ...ruleDraft, quietEnd: event.target.value })}
                  />
                </label>
                <label className="script-active-toggle">
                  <input
                    checked={ruleDraft.enabled}
                    onChange={(event) => setRuleDraft({ ...ruleDraft, enabled: event.target.checked })}
                    type="checkbox"
                  />
                  启用重拨
                </label>
              </div>
              <p className="form-result">{ruleMessage}</p>
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
    const showIntercept = showOverview || activeDmTab === "评论截流";
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

        {showIntercept && (
          <section className="content-grid lower comment-intercept-grid">
            <article className="panel">
              <div className="panel-title">
                <div>
                  <p>Intercept</p>
                  <h2>评论截流来源</h2>
                </div>
                <Search size={22} />
              </div>
              <div className="intercept-summary">
                <div>
                  <strong>{commentInterceptOverview.sources}</strong>
                  <span>截流来源</span>
                </div>
                <div>
                  <strong>{commentInterceptOverview.comments}</strong>
                  <span>评论总数</span>
                </div>
                <div>
                  <strong>{commentInterceptOverview.highIntentComments}</strong>
                  <span>A/B意向</span>
                </div>
                <div>
                  <strong>{commentInterceptOverview.convertedLeads}</strong>
                  <span>已转线索</span>
                </div>
              </div>

              <form className="form-grid" onSubmit={submitCommentSource}>
                <label>
                  平台
                  <select
                    value={commentSourceForm.platform}
                    onChange={(event) => setCommentSourceForm({ ...commentSourceForm, platform: event.target.value })}
                  >
                    <option value="抖音">抖音</option>
                    <option value="视频号">视频号</option>
                  </select>
                </label>
                <label>
                  来源类型
                  <select
                    value={commentSourceForm.sourceType}
                    onChange={(event) => setCommentSourceForm({ ...commentSourceForm, sourceType: event.target.value })}
                  >
                    <option value="视频链接">视频链接</option>
                    <option value="关键词">关键词</option>
                    <option value="账号主页">账号主页</option>
                  </select>
                </label>
                <label className="wide">
                  来源名称
                  <input value={commentSourceForm.name} onChange={(event) => setCommentSourceForm({ ...commentSourceForm, name: event.target.value })} />
                </label>
                <label className="wide">
                  视频或主页 URL
                  <input
                    placeholder="粘贴抖音/视频号视频或主页链接；桌面客户端会从当前内置页采集评论"
                    value={commentSourceForm.videoUrl}
                    onChange={(event) => setCommentSourceForm({ ...commentSourceForm, videoUrl: event.target.value })}
                  />
                </label>
                <label>
                  关键词
                  <input value={commentSourceForm.keyword} onChange={(event) => setCommentSourceForm({ ...commentSourceForm, keyword: event.target.value })} />
                </label>
                <label>
                  同步间隔分钟
                  <input
                    min={5}
                    type="number"
                    value={commentSourceForm.syncFrequencyMinutes}
                    onChange={(event) => setCommentSourceForm({ ...commentSourceForm, syncFrequencyMinutes: Number(event.target.value) })}
                  />
                </label>
                <label className="wide">
                  高意向关键词
                  <input
                    value={commentSourceForm.keywordRules}
                    onChange={(event) => setCommentSourceForm({ ...commentSourceForm, keywordRules: event.target.value })}
                  />
                </label>
                <button
                  className="primary-button"
                  disabled={!isDesktopClient || isSyncingComments || isCapturingBrowserComments || isRunningCommentAutomation}
                  type="submit"
                >
                  <Plus size={16} />
                  {!isDesktopClient ? "桌面客户端执行" : isRunningCommentAutomation ? "自动执行中" : "添加并自动执行"}
                </button>
              </form>

              {activeDmTab === "评论截流" && (
                <div className="comment-capture-workbench">
                  <div className="section-caption">
                    <div>
                      <strong>内置登录页采集</strong>
                      <small>登录后打开目标视频或主页，再读取当前页评论</small>
                    </div>
                    <button
                      className="row-action is-primary"
                      disabled={!activeCommentCaptureAccount || isPreparingDmLogin || !isDesktopClient}
                      onClick={() => activeCommentCaptureAccount && openRealDmLogin(activeCommentCaptureAccount.id)}
                      type="button"
                    >
                      {isPreparingDmLogin ? "加载中" : "打开内置页"}
                    </button>
                  </div>
                  <div className="comment-automation-grid">
                    <label>
                      滚动轮次
                      <input
                        min={1}
                        max={20}
                        type="number"
                        value={commentAutomationForm.scrollRounds}
                        onChange={(event) =>
                          setCommentAutomationForm({ ...commentAutomationForm, scrollRounds: Number(event.target.value) })
                        }
                      />
                    </label>
                    <label>
                      作者主页数
                      <input
                        min={0}
                        max={12}
                        type="number"
                        value={commentAutomationForm.maxAuthors}
                        onChange={(event) => setCommentAutomationForm({ ...commentAutomationForm, maxAuthors: Number(event.target.value) })}
                      />
                    </label>
                    <label>
                      发送间隔秒
                      <input
                        min={0}
                        max={600}
                        type="number"
                        value={commentAutomationForm.sendIntervalSeconds}
                        onChange={(event) =>
                          setCommentAutomationForm({ ...commentAutomationForm, sendIntervalSeconds: Number(event.target.value) })
                        }
                      />
                    </label>
                    <label className="wide">
                      私信草稿文案
                      <textarea
                        rows={3}
                        value={commentAutomationForm.dmMessage}
                        onChange={(event) => setCommentAutomationForm({ ...commentAutomationForm, dmMessage: event.target.value })}
                      />
                    </label>
                    <label className="checkbox-field wide">
                      <input
                        checked={commentAutomationForm.allowLiveSend}
                        onChange={(event) => setCommentAutomationForm({ ...commentAutomationForm, allowLiveSend: event.target.checked })}
                        type="checkbox"
                      />
                      <span>允许真实点击发送，执行前还会二次确认</span>
                    </label>
                  </div>
                  <div className="comment-queue-panel">
                    <div className="comment-queue-toolbar">
                      <div>
                        <strong>本机自动化队列</strong>
                        <small>
                          到期 {commentAutomationQueue.dueCount} · 可执行 {commentAutomationQueue.readyCount} · 暂停{" "}
                          {commentAutomationQueue.pausedCount} · 阻塞 {commentAutomationQueue.blockedCount}
                        </small>
                      </div>
                      <div className="comment-queue-actions">
                        <label className="mini-toggle">
                          <input
                            checked={isCommentSchedulerEnabled}
                            onChange={(event) => setIsCommentSchedulerEnabled(event.target.checked)}
                            type="checkbox"
                          />
                          <span>定时队列</span>
                        </label>
                        <input
                          aria-label="调度间隔分钟"
                          className="mini-number-input"
                          min={1}
                          max={240}
                          type="number"
                          value={commentSchedulerIntervalMinutes}
                          onChange={(event) => setCommentSchedulerIntervalMinutes(Number(event.target.value))}
                        />
                        <button
                          className="row-action"
                          disabled={isLoadingCommentAutomationQueue}
                          onClick={() => void refreshCommentAutomationQueue()}
                          type="button"
                        >
                          <RefreshCw size={14} />
                          {isLoadingCommentAutomationQueue ? "刷新中" : "刷新队列"}
                        </button>
                        <button
                          className="row-action is-primary"
                          disabled={!isDesktopClient || !nextReadyCommentQueueItem || isDispatchingCommentQueue || isRunningCommentAutomation}
                          onClick={() => void dispatchNextCommentAutomation("manual")}
                          type="button"
                        >
                          <Clock3 size={14} />
                          {isDispatchingCommentQueue ? "调度中" : "运行下一条"}
                        </button>
                      </div>
                    </div>
                    <div className="comment-queue-list">
                      {commentAutomationQueue.items.length === 0 && <div className="empty-state compact">队列暂无来源。</div>}
                      {commentAutomationQueue.items.slice(0, 4).map((item) => (
                        <div className={`comment-queue-row is-${item.status}`} key={item.sourceId}>
                          <div>
                            <strong>{item.sourceName}</strong>
                            <small>
                              {item.platform} · {item.sourceType} · 下次 {compactDateTime(item.nextRunAt)}
                            </small>
                          </div>
                          <span className="queue-status">{commentAutomationStatusText(item.status)}</span>
                          <small>{item.nextAccountName ?? "无可用账号"}</small>
                          <small>{item.blockedReason || `选择器 ${item.selectorProfile}`}</small>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="comment-selector-panel">
                    <div className="section-caption">
                      <div>
                        <strong>{activeCommentCaptureAccount?.platform ?? commentSourceForm.platform} 选择器快速修复</strong>
                        <small>
                          {activeCommentQueueItem
                            ? `${commentAutomationStatusText(activeCommentQueueItem.status)} · ${activeCommentQueueItem.selectorProfile}`
                            : "当前平台自动化选择器"}
                        </small>
                      </div>
                      <button
                        className="row-action is-primary"
                        disabled={isSavingCommentSelectors}
                        onClick={() => void saveCommentSelectorDraft()}
                        type="button"
                      >
                        <CheckCircle2 size={14} />
                        {isSavingCommentSelectors ? "保存中" : "保存选择器"}
                      </button>
                    </div>
                    <div className="comment-selector-grid">
                      <label>
                        私信按钮
                        <input
                          value={commentSelectorDraft.messageButtonSelector}
                          onChange={(event) => setCommentSelectorDraft({ ...commentSelectorDraft, messageButtonSelector: event.target.value })}
                        />
                      </label>
                      <label>
                        输入框
                        <input
                          value={commentSelectorDraft.inputSelector}
                          onChange={(event) => setCommentSelectorDraft({ ...commentSelectorDraft, inputSelector: event.target.value })}
                        />
                      </label>
                      <label>
                        发送按钮
                        <input
                          value={commentSelectorDraft.sendButtonSelector}
                          onChange={(event) => setCommentSelectorDraft({ ...commentSelectorDraft, sendButtonSelector: event.target.value })}
                        />
                      </label>
                      <label>
                        成功回执
                        <input
                          value={commentSelectorDraft.sentSuccessSelector}
                          onChange={(event) => setCommentSelectorDraft({ ...commentSelectorDraft, sentSuccessSelector: event.target.value })}
                        />
                      </label>
                      <label className="wide">
                        风控提示
                        <input
                          value={commentSelectorDraft.riskCheckSelector}
                          onChange={(event) => setCommentSelectorDraft({ ...commentSelectorDraft, riskCheckSelector: event.target.value })}
                        />
                      </label>
                    </div>
                  </div>
                  <div className="comment-capture-shell">
                    <aside className="login-account-rail comment-capture-account-rail">
                      {commentCaptureAccounts.length === 0 && <div className="empty-state compact">暂无抖音/视频号个人号。</div>}
                      {commentCaptureAccounts.map((account) => (
                        <button
                          className={`login-account-chip ${account.id === activeLoginAccount?.id ? "is-selected" : ""}`}
                          disabled={isPreparingDmLogin}
                          key={account.id}
                          onClick={() => selectDmLoginAccount(account.id)}
                          type="button"
                        >
                          <span>{account.platform}</span>
                          <strong>{account.accountName}</strong>
                          <small>{displayDmLoginStatus(account.sessionStatus)} · 当前页采集</small>
                        </button>
                      ))}
                    </aside>
                    <section className="embedded-login-frame comment-capture-frame">
                      <div className="embedded-browser-bar">
                        <span className="status-dot" />
                        <strong>{activeCommentCaptureAccount ? `${activeCommentCaptureAccount.platform} 内置页` : "选择采集账号"}</strong>
                        <em>{loginEntryHost(activeCommentCaptureUrl)}</em>
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
                                <span>{activeCommentCaptureAccount?.platform ?? "平台"}</span>
                                <strong>客户端内置登录采集</strong>
                                <p>
                                  {isDesktopClient
                                    ? "先加载内置页并登录，再在里面打开目标视频或主页。"
                                    : "网页预览不能读取内置登录页，请打开桌面客户端。"}
                                </p>
                              </div>
                            )}
                          </div>
                          <div className="real-login-note">
                            <strong>{activeCommentCaptureAccount?.accountName ?? "抖音/视频号个人号"}</strong>
                            <span>自动链路会搜索、开视频、滚评论、导入评论，并按安全闸门填好私信草稿。</span>
                          </div>
                        </div>
                        <div className="button-row comment-capture-actions">
                          <button
                            className="secondary-button"
                            disabled={!activeCommentCaptureAccount || isCheckingDmLogin}
                            onClick={() => activeCommentCaptureAccount && preflightDmAccount(activeCommentCaptureAccount.id)}
                            type="button"
                          >
                            <RefreshCw size={16} />
                            {isCheckingDmLogin && checkingDmAccountId === activeCommentCaptureAccount?.id ? "检测中" : "登录后检测"}
                          </button>
                          <button
                            className="primary-button"
                            disabled={!isDesktopClient || !activeBrowserCaptureSource || isRunningCommentAutomation || isCapturingBrowserComments}
                            onClick={() =>
                              activeBrowserCaptureSource && runCommentAutomationForSource(activeBrowserCaptureSource.id, activeBrowserCaptureSource)
                            }
                            type="button"
                          >
                            <Zap size={16} />
                            {isRunningCommentAutomation ? "自动执行中" : "自动搜索并执行"}
                          </button>
                          <button
                            className="secondary-button"
                            disabled={!isDesktopClient || !activeBrowserCaptureSource || isCapturingBrowserComments || isRunningCommentAutomation}
                            onClick={() =>
                              activeBrowserCaptureSource && captureCommentsFromEmbeddedPage(activeBrowserCaptureSource.id, activeBrowserCaptureSource)
                            }
                            type="button"
                          >
                            <Search size={16} />
                            {isCapturingBrowserComments ? "采集中" : "采集当前内置页"}
                          </button>
                        </div>
                        {lastCommentAutomationResult && (
                          <div className="automation-trace">
                            {lastCommentAutomationResult.steps.slice(0, 6).map((step) => (
                              <span className={`automation-step is-${step.status}`} key={`${step.name}-${step.message}`}>
                                {step.message}
                              </span>
                            ))}
                            {lastCommentAutomationResult.dmActions.slice(0, 4).map((action) => (
                              <span className={`automation-step is-${action.status}`} key={`${action.profileUrl}-${action.status}`}>
                                {action.authorName}：{action.receiptStatus ? `${action.receiptStatus} · ` : ""}
                                {action.message || action.status}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </section>
                  </div>
                </div>
              )}

              <div className="intercept-source-list">
                {commentSources.length === 0 && <div className="empty-state">暂无评论来源，先添加一个抖音或视频号视频。</div>}
                {commentSources.slice(0, 5).map((source) => (
                  <article className="intercept-source-card" key={source.id}>
                    <div>
                      <span className="badge">{source.platform}</span>
                      <strong>{source.name}</strong>
                      <small>{source.sourceType} · {source.syncStatus} · {source.lastSyncAt ? "已同步" : "未同步"}</small>
                      {source.lastError && <small className="error-text">{source.lastError}</small>}
                    </div>
                    <div className="source-card-actions">
                      <button
                        className="row-action is-primary"
                        disabled={!isDesktopClient || isRunningCommentAutomation || isCapturingBrowserComments}
                        onClick={() => void runCommentAutomationForSource(source.id, source)}
                        type="button"
                      >
                        {isRunningCommentAutomation ? "执行中" : "自动执行"}
                      </button>
                      <button
                        className="row-action"
                        disabled={!isDesktopClient || isCapturingBrowserComments || isRunningCommentAutomation}
                        onClick={() => void captureCommentsFromEmbeddedPage(source.id, source)}
                        type="button"
                      >
                        {isCapturingBrowserComments ? "采集中" : "当前页采集"}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </article>

            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Comment Pool</p>
                  <h2>评论线索池</h2>
                </div>
                <div className="button-row">
                  <button className="secondary-button" onClick={selectHighIntentComments} type="button">
                    <CheckCircle2 size={16} />
                    选择高意向
                  </button>
                  <button className="secondary-button" onClick={() => void refreshCommentInterceptData()} type="button">
                    <RefreshCw size={16} />
                    刷新评论
                  </button>
                </div>
              </div>
              <div className="rotation-hint">
                <CheckCircle2 size={16} />
                <span>
                  已选 {selectedSocialComments.length} 条评论，待转线索 {selectedPendingComments.length} 条，涉及平台
                  {selectedCommentPlatforms.length > 0 ? ` ${selectedCommentPlatforms.join("、")}` : " 暂无"}；
                  其中 {selectedSendableCommentCount} 条属于可自动私信平台。
                </span>
              </div>
              <div className="rotation-hint is-warning">
                <ShieldAlert size={16} />
                <span>视频号评论可以截流和转线索，但视频号助手当前不支持主动私信商家，适合走评论回复、人工跟进或外呼。</span>
              </div>
              {commentInterceptMessage && <div className="form-result">{commentInterceptMessage}</div>}
              <div className="table-wrap comment-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>选择</th>
                      <th>评论用户</th>
                      <th>评论内容</th>
                      <th>平台</th>
                      <th>意向</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {socialComments.length === 0 && (
	                      <tr>
	                        <td colSpan={6}>
	                          <span className="empty-state">暂无评论，先用客户端内置页采集一个截流来源。</span>
	                        </td>
	                      </tr>
                    )}
                    {socialComments.map((comment) => (
                      <tr key={comment.id}>
                        <td>
                          <input
                            checked={selectedCommentIds.includes(comment.id)}
                            disabled={comment.status === "已转线索"}
                            onChange={() => toggleComment(comment.id)}
                            type="checkbox"
                          />
                        </td>
                        <td>
                          <strong>{comment.authorName}</strong>
                          <small>{comment.city} · {comment.category}</small>
                        </td>
                        <td className="comment-content-cell">{comment.content}</td>
                        <td>{comment.platform}</td>
                        <td>
                          <span className={`intent-pill intent-${comment.intentLevel.toLowerCase()}`}>{comment.intentLevel}</span>
                          <small>{comment.intentScore}</small>
                        </td>
                        <td>
                          <span className="badge">{comment.status}</span>
                          <small>{comment.riskStatus}</small>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="intercept-actions">
                <button
                  className="secondary-button"
                  disabled={isConvertingComments || selectedPendingComments.length === 0}
                  onClick={() => void convertSelectedCommentsToLeads()}
                  type="button"
                >
                  <Upload size={16} />
                  {isConvertingComments ? "转入中" : "转入线索库"}
                </button>
                <button
                  className="primary-button"
                  disabled={isConvertingComments || selectedPendingComments.length === 0}
                  onClick={() => void prepareDmTaskFromComments()}
                  type="button"
                >
                  <MessageSquareText size={16} />
                  转线索并去创建任务
                </button>
                {lastCommentConvertResult && (
                  <small>
                    最近转入：新增 {lastCommentConvertResult.converted} 条，复用/跳过 {lastCommentConvertResult.skipped} 条。
                  </small>
                )}
              </div>
            </article>
          </section>
        )}

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
                  私信平台
                  <select
                    value={dmTaskPlatform}
                    onChange={(event) => {
                      const nextPlatform = event.target.value;
                      const nextPlatformLeadIds = new Set(
                        dmReachableLeads.filter((lead) => lead.platform === nextPlatform).map((lead) => lead.id),
                      );
                      const nextName = dmAccountPlatforms.some((platformName) => dmForm.name.startsWith(platformName))
                        ? dmForm.name.replace(/^(美团|饿了么|抖音)/, nextPlatform)
                        : dmForm.name;
                      setDmForm({ ...dmForm, platform: nextPlatform, name: nextName });
                      setSelectedDmLeadIds((current) => current.filter((leadId) => nextPlatformLeadIds.has(leadId)));
                      setDmTaskMessage("");
                    }}
                  >
                    {dmAccountPlatforms.map((platformName) => (
                      <option key={platformName} value={platformName}>
                        {platformName}（已登录 {dmLoggedInAccounts.filter((account) => account.platform === platformName).length} 个号）
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
              {dmTaskMessage && (
                <div className={`rotation-hint ${dmTaskMessage.includes("已创建") ? "" : "is-warning"}`}>
                  {dmTaskMessage.includes("已创建") ? <CheckCircle2 size={16} /> : <ShieldAlert size={16} />}
                  <span>{dmTaskMessage}</span>
                </div>
              )}

              <div className="lead-picker">
                <div className="section-caption">
                  <div>
                    <strong>{dmTaskPlatform} 私信对象</strong>
                    <small>
                      {selectedDmPlatformLeadIds.length} 个已选 · {dmPlatformLeads.length} 条可选 · 未选时默认取前 20 条
                    </small>
                  </div>
                  <div className="button-row">
                    <button
                      className="row-action"
                      disabled={dmPlatformLeads.length === 0}
                      onClick={() => {
                        const nextLeadIds = new Set(selectedDmLeadIds);
                        dmPlatformLeads.forEach((lead) => nextLeadIds.add(lead.id));
                        setSelectedDmLeadIds(Array.from(nextLeadIds));
                        setDmTaskMessage("");
                      }}
                      type="button"
                    >
                      全选当前平台
                    </button>
                    <button
                      className="row-action"
                      disabled={selectedDmPlatformLeadIds.length === 0}
                      onClick={() => {
                        setSelectedDmLeadIds((current) => current.filter((leadId) => !dmPlatformLeadIds.has(leadId)));
                        setDmTaskMessage("");
                      }}
                      type="button"
                    >
                      清空选择
                    </button>
                  </div>
                </div>
                <div className="rotation-hint">
                  <CheckCircle2 size={16} />
                  <span>
                    本任务只发送 {dmTaskPlatform} 线索，系统会从 {dmPlatformLoggedInAccounts.length} 个已登录
                    {dmTaskPlatform}个人号中自动轮换，当前剩余额度 {dmPlatformRemainingQuota} 条。
                  </span>
                </div>
                <div className="rotation-hint">
                  <CheckCircle2 size={16} />
                  <span>
                    多账号会共同进入同平台账号池，系统按发送间隔、剩余额度和风控状态自动轮换，避免某个账号被集中消耗。
                  </span>
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
                <LeadTable leads={dmPlatformLeads} selectable selectedLeadIds={selectedDmLeadIds} onToggleLead={toggleDmLead} />
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
                  <strong>{dmLoginAccounts.length}</strong>
                  <span>已配置个人号</span>
                </div>
                <div>
                  <strong>{isolatedDmAccountCount}</strong>
                  <span>独立登录环境</span>
                </div>
                <p>每个个人号独立登录、独立额度、独立风控状态，可按平台添加多个账号轮流触达。</p>
              </div>
              <div className="platform-account-strip" aria-label="按平台添加个人号">
                {loginCapablePlatforms.map((platform) => (
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
                    {loginCapablePlatforms.map((platform) => (
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
                  {dmLoginAccounts.length === 0 && <div className="empty-state">暂无可登录的平台个人号。</div>}
                  {dmLoginAccounts.map((account) => (
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
                        <strong>
                          {activeLoginAccount && !isSupportedDmPlatform(activeLoginAccount.platform)
                            ? "仅用于登录采集"
                            : "只给同平台商家发送"}
                        </strong>
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
          : activeModule === "collector"
            ? "新建采集"
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
    if (activeModule === "collector") {
      setCollectionMessage("在左侧填写城市、品类和关键词后创建采集任务。");
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

  if (!auth?.accessToken) {
    return renderAuthGate();
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
            <p>当前商户：{currentUser?.displayName ?? auth.user.displayName} · {apiStatus}</p>
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
            <button className="secondary-button" onClick={logout} type="button">
              退出
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
        ) : activeModule === "collector" ? (
          renderCollectorWorkspace()
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

export default TeammateWorkspace;
