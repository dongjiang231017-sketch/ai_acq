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
  DmAccount,
  DmConversation,
  DmLoginSession,
  DmMessage,
  DmOverview,
  DmPlatformConfig,
  DmSyncResult,
  DmTemplate,
  Lead,
  ModuleSummary,
  OutboundOverview,
  OutreachTask,
  RecallRule,
  api,
} from "./lib/api";

const icons = [BarChart3, Search, Database, PhoneCall, MessageSquareText, Users, Bot, Headphones, ClipboardList, Settings];

const fallbackModules: ModuleSummary[] = [
  { key: "dashboard", name: "实时工作台", description: "监控今日获客、外呼、私信和预警。", pageCount: 4, status: "ready" },
  { key: "collector", name: "线索采集", description: "采集任务、来源配置、清洗规则。", pageCount: 5, status: "ready" },
  { key: "leads", name: "商家线索库", description: "商家资料、电话库、主页和去重审核。", pageCount: 5, status: "ready" },
  { key: "outbound", name: "AI外呼系统", description: "外呼任务、话术流程、通话记录。", pageCount: 6, status: "ready" },
  { key: "dm", name: "平台私信系统", description: "平台账号、私信任务、模板和会话。", pageCount: 6, status: "ready" },
  { key: "intent", name: "意向客户池", description: "客户分级、工单跟进和分配规则。", pageCount: 4, status: "ready" },
  { key: "learning", name: "AI学习中心", description: "建议队列、知识库和实验结果。", pageCount: 5, status: "ready" },
  { key: "voice", name: "声音档案", description: "授权、音色训练和使用记录。", pageCount: 4, status: "ready" },
  { key: "reports", name: "数据报表", description: "渠道、绩效和导出中心。", pageCount: 4, status: "ready" },
  { key: "settings", name: "系统设置", description: "线路、账号、模型 API、权限和审计。", pageCount: 6, status: "ready" },
];

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
    platformUrl: "https://e.meituan.com/",
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
  activeAccounts: 2,
  todaySent: 128,
  replies: 32,
  needsHandoff: 9,
  intentCount: 18,
};

const fallbackDmAccounts: DmAccount[] = [
  {
    id: "dm_account_1",
    platform: "美团",
    accountName: "南昌本地生活招商号",
    loginLabel: "已登录",
    status: "可用",
    browserProfileKey: "meituan-nanchang-local",
    browserProfilePath: ".dm_browser_profiles/meituan-nanchang-local",
    sessionStatus: "模拟可用",
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
    accountName: "餐饮团购增长号",
    loginLabel: "待扫码",
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
    lastError: "请先扫码登录",
    createdAt: new Date().toISOString(),
  },
];

const fallbackDmPlatformConfigs: DmPlatformConfig[] = [
  {
    id: "dm_platform_1",
    platform: "美团",
    homeUrl: "https://e.meituan.com/",
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
  },
];

const fallbackDmSyncResult: DmSyncResult = {
  checked: 0,
  newReplies: 0,
  needsHandoff: 0,
};

const platformLoginUrls: Record<string, string> = {
  美团: "https://e.meituan.com/",
  饿了么: "https://open.shop.ele.me/",
  抖音: "https://business.douyin.com/",
  视频号: "https://channels.weixin.qq.com/",
};

const defaultDmPlatformForm: Omit<DmPlatformConfig, "id" | "createdAt"> = {
  platform: "美团",
  homeUrl: "https://e.meituan.com/",
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

const outboundTabs = ["外呼总览", "任务列表", "话术流程", "通话记录", "重拨规则", "实时监听"] as const;
type OutboundTab = (typeof outboundTabs)[number];
const dmTabs = ["私信总览", "任务列表", "账号管理", "消息模板", "会话记录", "回复监听"] as const;
type DmTab = (typeof dmTabs)[number];

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
  const [activeModule, setActiveModule] = useState("outbound");
  const [apiStatus, setApiStatus] = useState("连接中");
  const [isLoading, setIsLoading] = useState(false);
  const [activeOutboundTab, setActiveOutboundTab] = useState<OutboundTab>("实时监听");
  const [activeDmTab, setActiveDmTab] = useState<DmTab>("回复监听");
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
  const [dmForm, setDmForm] = useState({
    name: "美团高意向商家首轮私信",
    accountId: "",
    templateId: "",
    scheduledAt: "",
  });
  const [dmAccountForm, setDmAccountForm] = useState({
    platform: "美团",
    accountName: "",
    loginLabel: "待扫码",
    status: "待登录",
    browserProfileKey: "",
    sessionStatus: "未登录",
    riskStatus: "正常",
    dailyLimit: 200,
    minSendIntervalSeconds: 45,
  });
  const [dmTemplateForm, setDmTemplateForm] = useState({
    name: "视频号团购邀约私信",
    platform: "通用",
    content: "您好，看到{商家名称}适合做视频号本地生活团购曝光，想了解下您是否考虑新增线上获客渠道？",
    isActive: true,
  });
  const [dmLoginSession, setDmLoginSession] = useState<DmLoginSession | null>(null);
  const [dmLoginMessage, setDmLoginMessage] = useState("");
  const [dmLoginWindowUrl, setDmLoginWindowUrl] = useState("");
  const [isOpeningDmLogin, setIsOpeningDmLogin] = useState(false);
  const [editingDmPlatformConfigId, setEditingDmPlatformConfigId] = useState<string | null>(null);
  const [dmPlatformForm, setDmPlatformForm] = useState(defaultDmPlatformForm);
  const loginWorkbenchRef = useRef<HTMLElement | null>(null);

  const active = useMemo(
    () => modules.find((module) => module.key === activeModule) ?? modules[0],
    [activeModule, modules],
  );
  const outboundTasks = useMemo(() => tasks.filter((task) => task.channel === "call"), [tasks]);
  const dmTasks = useMemo(() => tasks.filter((task) => task.channel === "dm"), [tasks]);
  const callableLeads = useMemo(() => leads.filter((lead) => Boolean(lead.phone)), [leads]);
  const dmReachableLeads = useMemo(() => leads.filter((lead) => Boolean(lead.platform)), [leads]);
  const activeScript = scripts.find((script) => script.isActive) ?? scripts[0];
  const activeRule = recallRules[0];
  const activeDmTemplate = dmTemplates.find((template) => template.id === dmForm.templateId) ?? dmTemplates[0];
  const activeLoginAccount = useMemo(() => {
    return dmAccounts.find((account) => account.id === dmLoginSession?.accountId) ?? dmAccounts[0];
  }, [dmAccounts, dmLoginSession]);
  const activeLoginConfig = useMemo(() => {
    if (!activeLoginAccount) return null;
    return dmPlatformConfigs.find((config) => config.platform === activeLoginAccount.platform) ?? null;
  }, [activeLoginAccount, dmPlatformConfigs]);
  const activeLoginUrl =
    dmLoginSession?.loginUrl || activeLoginConfig?.homeUrl || (activeLoginAccount ? platformLoginUrls[activeLoginAccount.platform] : "") || "";
  const activeProfileKey =
    dmLoginSession?.profileKey || activeLoginAccount?.browserProfileKey || `${activeLoginAccount?.platform ?? "platform"}-account`;
  const activeProfilePath =
    dmLoginSession?.profilePath || activeLoginAccount?.browserProfilePath || `.dm_browser_profiles/${activeProfileKey}`;

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
    ]);

    if (results[0].status === "fulfilled") {
      setApiStatus(results[0].value.status === "ok" ? "后端已连接" : results[0].value.status);
    } else {
      setApiStatus("使用前端示例数据");
    }
    if (results[1].status === "fulfilled") setModules(results[1].value);
    const leadResult = results[2];
    if (leadResult.status === "fulfilled") {
      const nextLeads = leadResult.value;
      setLeads(nextLeads);
      setSelectedLeadIds((current) => current.filter((id) => nextLeads.some((lead) => lead.id === id)));
      setSelectedDmLeadIds((current) => current.filter((id) => nextLeads.some((lead) => lead.id === id)));
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
        accountId: current.accountId || nextAccounts[0]?.id || "",
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

  async function submitDmTask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const leadIds = selectedDmLeadIds.length > 0 ? selectedDmLeadIds : dmReachableLeads.slice(0, 20).map((lead) => lead.id);
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
    if (!dmAccountForm.accountName.trim()) return;

    const created = await api.createDmAccount({
      ...dmAccountForm,
      dailyLimit: Number(dmAccountForm.dailyLimit),
      minSendIntervalSeconds: Number(dmAccountForm.minSendIntervalSeconds),
    });
    setDmAccounts((current) => [created, ...current]);
    setDmForm((current) => ({ ...current, accountId: created.id }));
    setDmAccountForm({
      platform: "美团",
      accountName: "",
      loginLabel: "待扫码",
      status: "待登录",
      browserProfileKey: "",
      sessionStatus: "未登录",
      riskStatus: "正常",
      dailyLimit: 200,
      minSendIntervalSeconds: 45,
    });
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

  async function openDmLoginSession(accountId: string) {
    setIsOpeningDmLogin(true);
    setDmLoginMessage("正在打开该账号的隔离登录窗口...");
    revealDmLoginWorkbench();
    try {
      const session = await api.openDmLoginWindow(accountId);
      setDmLoginSession(session);
      setDmLoginWindowUrl(session.loginUrl);
      setDmLoginMessage(session.launchMessage || "已打开该账号的隔离登录窗口");
      setDmAccounts((current) =>
        current.map((account) =>
          account.id === accountId
            ? {
                ...account,
                status: session.sessionStatus === "已登录" || session.sessionStatus === "模拟可用" ? account.status : "待登录",
                sessionStatus: session.sessionStatus,
                riskStatus: session.riskStatus,
                browserProfileKey: session.profileKey,
                browserProfilePath: session.profilePath,
                lastError:
                  session.sessionStatus === "已登录" || session.sessionStatus === "模拟可用"
                    ? account.lastError
                    : "独立登录窗口已打开，完成登录后点击检测",
              }
            : account,
        ),
      );
    } catch (error) {
      setDmLoginMessage(error instanceof Error ? error.message : "打开登录窗口失败");
    } finally {
      setIsOpeningDmLogin(false);
    }
  }

  async function preflightDmAccount(accountId: string) {
    const updated = await api.preflightDmAccount(accountId);
    setDmAccounts((current) => current.map((account) => (account.id === updated.id ? updated : account)));
    setDmLoginMessage(updated.sessionStatus === "已登录" || updated.sessionStatus === "模拟可用" ? "登录态检测通过" : "还未检测到登录态");
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
      homeUrl: config.homeUrl,
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
          <MetricCard icon={<MessageSquareText size={20} />} label="平台账号" value={dmOverview.activeAccounts} detail={`共 ${dmOverview.accounts} 个`} tone="blue" />
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
                  平台账号
                  <select value={dmForm.accountId} onChange={(event) => setDmForm({ ...dmForm, accountId: event.target.value })}>
                    <option value="">账号池轮转</option>
                    {dmAccounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.platform} · {account.accountName}
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
                  <small>{selectedDmLeadIds.length} 个已选</small>
                </div>
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
                  <h2>平台账号管理</h2>
                </div>
                <Users size={22} />
              </div>
              <form className="form-grid" onSubmit={submitDmAccount}>
                <label>
                  平台
                  <select value={dmAccountForm.platform} onChange={(event) => setDmAccountForm({ ...dmAccountForm, platform: event.target.value })}>
                    <option>美团</option>
                    <option>饿了么</option>
                    <option>抖音</option>
                    <option>视频号</option>
                  </select>
                </label>
                <label>
                  账号名称
                  <input
                    value={dmAccountForm.accountName}
                    onChange={(event) => setDmAccountForm({ ...dmAccountForm, accountName: event.target.value })}
                  />
                </label>
                <label>
                  登录标识
                  <input
                    value={dmAccountForm.loginLabel}
                    onChange={(event) => setDmAccountForm({ ...dmAccountForm, loginLabel: event.target.value })}
                  />
                </label>
                <label>
                  Profile 标识
                  <input
                    value={dmAccountForm.browserProfileKey}
                    onChange={(event) => setDmAccountForm({ ...dmAccountForm, browserProfileKey: event.target.value })}
                  />
                </label>
                <label>
                  登录态
                  <select
                    value={dmAccountForm.sessionStatus}
                    onChange={(event) => setDmAccountForm({ ...dmAccountForm, sessionStatus: event.target.value })}
                  >
                    <option>未登录</option>
                    <option>已登录</option>
                    <option>模拟可用</option>
                    <option>需扫码</option>
                  </select>
                </label>
                <label>
                  风险状态
                  <select
                    value={dmAccountForm.riskStatus}
                    onChange={(event) => setDmAccountForm({ ...dmAccountForm, riskStatus: event.target.value })}
                  >
                    <option>正常</option>
                    <option>需验证</option>
                    <option>风控暂停</option>
                    <option>异常</option>
                  </select>
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
                  <p>Status</p>
                  <h2>账号额度和登录状态</h2>
                </div>
                <ShieldAlert size={22} />
              </div>
              <div className="account-list">
                {dmAccounts.map((account) => (
                  <article className="account-row" key={account.id}>
                    <div className="account-row-head">
                      <div>
                        <strong>{account.accountName}</strong>
                        <small>{account.platform} · {account.loginLabel ?? "未绑定"} · {account.browserProfileKey ?? "未生成Profile"}</small>
                        {account.lastError && <small className="error-text">{account.lastError}</small>}
                      </div>
                      <em>
                        {account.sentToday}/{account.dailyLimit} · {account.minSendIntervalSeconds ?? 0}s
                      </em>
                    </div>
                    <div className="account-row-meta">
                      <span>{account.status}</span>
                      <span>{account.sessionStatus ?? "未登录"}</span>
                      <span>{account.riskStatus ?? "正常"}</span>
                    </div>
                    <div className="account-row-actions">
                      <button
                        className="row-action is-primary"
                        disabled={isOpeningDmLogin}
                        onClick={() => openDmLoginSession(account.id)}
                        type="button"
                      >
                        {isOpeningDmLogin ? "打开中" : "登录"}
                      </button>
                      <button className="row-action" onClick={() => preflightDmAccount(account.id)} type="button">
                        检测
                      </button>
                    </div>
                  </article>
                ))}
              </div>
              <div className="platform-config-list">
                <div className="section-caption">
                  <strong>平台页面选择器</strong>
                  <small>{dmPlatformConfigs.length} 个平台</small>
                </div>
                {dmPlatformConfigs.map((config) => (
                  <article className="platform-config-row" key={config.id}>
                    <strong>{config.platform}</strong>
                    <span>{config.enabled ? "已启用" : "待配置"}</span>
                    <small>{config.homeUrl || "未配置首页"}</small>
                    <button className="row-action" onClick={() => editDmPlatformConfig(config)} type="button">
                      编辑
                    </button>
                  </article>
                ))}
              </div>
            </article>

            <article className="panel span-2 login-workbench" ref={loginWorkbenchRef}>
              <div className="panel-title">
                <div>
                  <p>Login</p>
                  <h2>客户端内置登录工作台</h2>
                </div>
                <KeyRound size={22} />
              </div>

              <div className="login-shell">
                <aside className="login-account-rail">
                  {dmAccounts.map((account) => (
                    <button
                      className={`login-account-chip ${account.id === activeLoginAccount?.id ? "is-selected" : ""}`}
                      disabled={isOpeningDmLogin}
                      key={account.id}
                      onClick={() => openDmLoginSession(account.id)}
                      type="button"
                    >
                      <span>{account.platform}</span>
                      <strong>{account.accountName}</strong>
                      <small>{account.browserProfileKey ?? "独立 Profile 待生成"}</small>
                    </button>
                  ))}
                </aside>

                <section className="embedded-login-frame">
                  <div className="embedded-browser-bar">
                    <span className="status-dot" />
                    <strong>{activeLoginAccount ? `${activeLoginAccount.platform} 登录页` : "选择平台账号"}</strong>
                    <em>{activeLoginUrl || "请先配置平台首页"}</em>
                  </div>
                  <div className={`embedded-login-body ${dmLoginWindowUrl ? "is-open" : ""}`}>
                    <div className={`login-preview ${dmLoginWindowUrl ? "has-webview" : ""}`}>
                      {dmLoginWindowUrl ? (
                        <div className="embedded-webview">
                          <iframe
                            referrerPolicy="no-referrer"
                            src={dmLoginWindowUrl}
                            title={`${activeLoginAccount?.platform ?? "平台"}隔离登录页`}
                          />
                          <div className="embedded-webview-note">
                            <strong>{activeLoginAccount ? activeLoginAccount.accountName : "平台账号"}</strong>
                            <span>{dmLoginMessage || "独立登录窗口已打开"}</span>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="login-qr-mark">
                            <KeyRound size={34} />
                          </div>
                          <strong>{activeLoginAccount ? activeLoginAccount.accountName : "暂无账号"}</strong>
                          <span>{activeLoginAccount?.sessionStatus ?? "未登录"}</span>
                          <p>{dmLoginMessage || "点击登录后，在该账号自己的隔离页面完成扫码或账号登录。"}</p>
                        </>
                      )}
                    </div>
                    <div className="profile-inspector">
                      <div>
                        <span>平台</span>
                        <strong>{activeLoginAccount?.platform ?? "-"}</strong>
                      </div>
                      <div>
                        <span>隔离 Profile</span>
                        <strong>{activeProfileKey}</strong>
                      </div>
                      <div>
                        <span>会话目录</span>
                        <strong>{activeProfilePath}</strong>
                      </div>
                      <div>
                        <span>风险状态</span>
                        <strong>{activeLoginAccount?.riskStatus ?? "正常"}</strong>
                      </div>
                    </div>
                  </div>
                  <div className="button-row login-actions">
                    <button
                      className="primary-button"
                      disabled={!activeLoginAccount || isOpeningDmLogin}
                      onClick={() => activeLoginAccount && openDmLoginSession(activeLoginAccount.id)}
                      type="button"
                    >
                      <KeyRound size={16} />
                      {isOpeningDmLogin ? "正在打开" : "打开内置登录页"}
                    </button>
                    <button
                      className="secondary-button"
                      disabled={!activeLoginAccount}
                      onClick={() => activeLoginAccount && preflightDmAccount(activeLoginAccount.id)}
                      type="button"
                    >
                      <RefreshCw size={16} />
                      登录后检测
                    </button>
                    {activeLoginUrl && (
                      <a className="secondary-link-button" href={activeLoginUrl} rel="noreferrer" target="_blank">
                        <ExternalLink size={16} />
                        备用打开
                      </a>
                    )}
                  </div>
                </section>
              </div>
            </article>

            <article className="panel span-2">
              <div className="panel-title">
                <div>
                  <p>Adapter</p>
                  <h2>真实平台适配器配置</h2>
                </div>
                <Code2 size={22} />
              </div>
              <form className="form-grid adapter-form" onSubmit={submitDmPlatformConfig}>
                <label>
                  平台
                  <select
                    value={dmPlatformForm.platform}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, platform: event.target.value })}
                  >
                    <option>美团</option>
                    <option>饿了么</option>
                    <option>抖音</option>
                    <option>视频号</option>
                  </select>
                </label>
                <label>
                  启用状态
                  <select
                    value={dmPlatformForm.enabled ? "enabled" : "disabled"}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, enabled: event.target.value === "enabled" })}
                  >
                    <option value="disabled">待配置</option>
                    <option value="enabled">已启用</option>
                  </select>
                </label>
                <label>
                  平台首页
                  <input
                    value={dmPlatformForm.homeUrl}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, homeUrl: event.target.value })}
                  />
                </label>
                <label>
                  收件箱 URL
                  <input
                    value={dmPlatformForm.inboxUrl}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, inboxUrl: event.target.value })}
                  />
                </label>
                <label className="wide">
                  商家搜索 URL 模板
                  <input
                    placeholder="支持 {商家名称}、{城市}、{品类}、{平台}"
                    value={dmPlatformForm.merchantSearchUrl}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, merchantSearchUrl: event.target.value })}
                  />
                </label>
                <label>
                  登录态选择器
                  <input
                    value={dmPlatformForm.loginCheckSelector}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, loginCheckSelector: event.target.value })}
                  />
                </label>
                <label>
                  风控选择器
                  <input
                    value={dmPlatformForm.riskCheckSelector}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, riskCheckSelector: event.target.value })}
                  />
                </label>
                <label>
                  商家结果选择器
                  <input
                    value={dmPlatformForm.merchantLinkSelector}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, merchantLinkSelector: event.target.value })}
                  />
                </label>
                <label>
                  私信按钮选择器
                  <input
                    value={dmPlatformForm.messageButtonSelector}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, messageButtonSelector: event.target.value })}
                  />
                </label>
                <label>
                  输入框选择器
                  <input
                    value={dmPlatformForm.inputSelector}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, inputSelector: event.target.value })}
                  />
                </label>
                <label>
                  发送按钮选择器
                  <input
                    value={dmPlatformForm.sendButtonSelector}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, sendButtonSelector: event.target.value })}
                  />
                </label>
                <label>
                  发送成功选择器
                  <input
                    value={dmPlatformForm.sentSuccessSelector}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, sentSuccessSelector: event.target.value })}
                  />
                </label>
                <label>
                  未读消息选择器
                  <input
                    value={dmPlatformForm.unreadSelector}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, unreadSelector: event.target.value })}
                  />
                </label>
                <label>
                  会话条目选择器
                  <input
                    value={dmPlatformForm.conversationItemSelector}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, conversationItemSelector: event.target.value })}
                  />
                </label>
                <label>
                  会话标题选择器
                  <input
                    value={dmPlatformForm.conversationTitleSelector}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, conversationTitleSelector: event.target.value })}
                  />
                </label>
                <label>
                  消息文本选择器
                  <input
                    value={dmPlatformForm.messageTextSelector}
                    onChange={(event) => setDmPlatformForm({ ...dmPlatformForm, messageTextSelector: event.target.value })}
                  />
                </label>
                <div className="button-row wide">
                  <button className="primary-button" type="submit">
                    <CheckCircle2 size={16} />
                    {editingDmPlatformConfigId ? "保存配置" : "新增配置"}
                  </button>
                  <button
                    className="secondary-button"
                    onClick={() => {
                      setEditingDmPlatformConfigId(null);
                      setDmPlatformForm(defaultDmPlatformForm);
                    }}
                    type="button"
                  >
                    重置
                  </button>
                </div>
              </form>
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
              onClick={() => {
                if (activeModule === "dm") {
                  setActiveDmTab("任务列表");
                } else {
                  setActiveModule("outbound");
                  setActiveOutboundTab("任务列表");
                }
              }}
              type="button"
            >
              <Plus size={16} />
              新建任务
            </button>
          </div>
        </header>

        {activeModule === "outbound" ? (
          renderOutboundWorkspace()
        ) : activeModule === "dm" ? (
          renderDmWorkspace()
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
