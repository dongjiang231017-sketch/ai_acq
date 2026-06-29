const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export type ModuleSummary = {
  key: string;
  name: string;
  description: string;
  pageCount: number;
  status: string;
};

export type Lead = {
  id: string;
  name: string;
  platform: string;
  city: string;
  category: string;
  phone?: string | null;
  contactName?: string | null;
  platformUrl?: string | null;
  source: string;
  intentScore: number;
  status: string;
};

export type OutreachTask = {
  id: string;
  name: string;
  channel: "collector" | "call" | "dm";
  status: string;
  targetCount: number;
  completedCount: number;
  connectedCount: number;
  intentCount: number;
  failedCount: number;
  concurrency: number;
  scriptId?: string | null;
  dmAccountId?: string | null;
  dmTemplateId?: string | null;
  scheduledAt?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
};

export type OutboundOverview = {
  aiSeats: number;
  activeCalls: number;
  needsHandoff: number;
  silentAlerts: number;
  todayCalls: number;
  connectedRate: number;
  intentCount: number;
};

export type CallRecord = {
  id: string;
  taskId: string;
  leadId: string;
  merchantName: string;
  phone?: string | null;
  aiSeat: string;
  durationSeconds: number;
  intentLevel: string;
  currentNode: string;
  outcome: string;
  transcript: string;
  gatewayCallId?: string | null;
  gatewayStatus: string;
  rawPayload?: string | null;
  needHandoff: boolean;
  recallAt?: string | null;
  createdAt: string;
};

export type CallScript = {
  id: string;
  name: string;
  opening: string;
  qualification: string;
  objection: string;
  closing: string;
  isActive: boolean;
  createdAt: string;
};

export type RecallRule = {
  id: string;
  name: string;
  noAnswerIntervalMinutes: number;
  busyIntervalMinutes: number;
  maxAttempts: number;
  quietStart: string;
  quietEnd: string;
  enabled: boolean;
};

export type TelephonyConfig = {
  gatewayMode: string;
  queueEnabled: boolean;
  queueName: string;
  redisUrlConfigured: boolean;
  asteriskHost: string;
  asteriskAmiPort: number;
  asteriskUsernameConfigured: boolean;
  asteriskTrunkName: string;
};

export type DmOverview = {
  accounts: number;
  activeAccounts: number;
  todaySent: number;
  replies: number;
  needsHandoff: number;
  intentCount: number;
};

export type DmAccount = {
  id: string;
  platform: string;
  accountName: string;
  loginLabel?: string | null;
  status: string;
  browserProfileKey?: string | null;
  browserProfilePath?: string | null;
  sessionStatus?: string | null;
  riskStatus?: string | null;
  dailyLimit: number;
  sentToday: number;
  minSendIntervalSeconds: number;
  cooldownUntil?: string | null;
  lastSentAt?: string | null;
  lastSyncAt?: string | null;
  lastLoginCheckAt?: string | null;
  lastError?: string | null;
  createdAt: string;
};

export type DmLoginSession = {
  accountId: string;
  platform: string;
  accountName: string;
  loginUrl: string;
  profileKey: string;
  profilePath: string;
  sessionStatus?: string | null;
  riskStatus?: string | null;
  embeddedMode: string;
  isolated: boolean;
};

export type DmLoginWindow = DmLoginSession & {
  launched: boolean;
  launchMessage: string;
};

export type DmTemplate = {
  id: string;
  name: string;
  platform: string;
  content: string;
  isActive: boolean;
  createdAt: string;
};

export type DmConversation = {
  id: string;
  taskId: string;
  leadId: string;
  accountId?: string | null;
  platform: string;
  merchantName: string;
  status: string;
  intentLevel: string;
  lastMessage: string;
  lastMessageAt?: string | null;
  needHandoff: boolean;
  createdAt: string;
};

export type DmMessage = {
  id: string;
  conversationId: string;
  direction: "outbound" | "inbound" | string;
  content: string;
  status: string;
  externalMessageId?: string | null;
  rawPayload?: string | null;
  createdAt: string;
};

export type DmConfig = {
  gatewayMode: string;
  queueEnabled: boolean;
  queueName: string;
  redisUrlConfigured: boolean;
  browserProfileRoot: string;
  browserHeadless: boolean;
  browserChannel: string;
  browserLiveSendEnabled: boolean;
};

export type DmPlatformConfig = {
  id: string;
  platform: string;
  homeUrl: string;
  inboxUrl: string;
  merchantSearchUrl: string;
  loginCheckSelector: string;
  riskCheckSelector: string;
  merchantLinkSelector: string;
  messageButtonSelector: string;
  inputSelector: string;
  sendButtonSelector: string;
  sentSuccessSelector: string;
  unreadSelector: string;
  conversationItemSelector: string;
  conversationTitleSelector: string;
  messageTextSelector: string;
  enabled: boolean;
  createdAt: string;
};

export type DmSyncResult = {
  checked: number;
  newReplies: number;
  needsHandoff: number;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`);
  }

  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; service: string }>("/health"),
  modules: () => request<ModuleSummary[]>("/modules"),
  leads: () => request<Lead[]>("/leads"),
  createLead: (lead: Omit<Lead, "id" | "intentScore" | "status">) =>
    request<Lead>("/leads", {
      method: "POST",
      body: JSON.stringify(lead),
    }),
  tasks: () => request<OutreachTask[]>("/tasks"),
  createTask: (task: Pick<OutreachTask, "name" | "channel" | "targetCount" | "scheduledAt">) =>
    request<OutreachTask>("/tasks", {
      method: "POST",
      body: JSON.stringify(task),
    }),
  outboundOverview: () => request<OutboundOverview>("/outbound/overview"),
  outboundTasks: () => request<OutreachTask[]>("/outbound/tasks"),
  createOutboundTask: (task: {
    name: string;
    leadIds: string[];
    concurrency: number;
    scriptId?: string | null;
    scheduledAt?: string | null;
  }) =>
    request<OutreachTask>("/outbound/tasks", {
      method: "POST",
      body: JSON.stringify(task),
    }),
  startOutboundTask: (taskId: string) =>
    request<OutreachTask>(`/outbound/tasks/${taskId}/start`, {
      method: "POST",
    }),
  callRecords: () => request<CallRecord[]>("/outbound/records"),
  liveCalls: () => request<CallRecord[]>("/outbound/live"),
  callScripts: () => request<CallScript[]>("/outbound/scripts"),
  recallRules: () => request<RecallRule[]>("/outbound/recall-rules"),
  telephonyConfig: () => request<TelephonyConfig>("/outbound/telephony/config"),
  dmOverview: () => request<DmOverview>("/direct-messages/overview"),
  dmConfig: () => request<DmConfig>("/direct-messages/config"),
  dmAccounts: () => request<DmAccount[]>("/direct-messages/accounts"),
  createDmAccount: (account: {
    platform: string;
    accountName: string;
    loginLabel?: string | null;
    status: string;
    browserProfileKey?: string | null;
    sessionStatus?: string | null;
    riskStatus?: string | null;
    dailyLimit: number;
    minSendIntervalSeconds?: number;
  }) =>
    request<DmAccount>("/direct-messages/accounts", {
      method: "POST",
      body: JSON.stringify(account),
    }),
  updateDmAccount: (accountId: string, account: Partial<DmAccount>) =>
    request<DmAccount>(`/direct-messages/accounts/${accountId}`, {
      method: "PATCH",
      body: JSON.stringify(account),
    }),
  preflightDmAccount: (accountId: string) =>
    request<DmAccount>(`/direct-messages/accounts/${accountId}/preflight`, {
      method: "POST",
    }),
  createDmLoginSession: (accountId: string) =>
    request<DmLoginSession>(`/direct-messages/accounts/${accountId}/login-session`, {
      method: "POST",
    }),
  openDmLoginWindow: (accountId: string) =>
    request<DmLoginWindow>(`/direct-messages/accounts/${accountId}/login-window`, {
      method: "POST",
    }),
  dmPlatformConfigs: () => request<DmPlatformConfig[]>("/direct-messages/platform-configs"),
  createDmPlatformConfig: (config: Omit<DmPlatformConfig, "id" | "createdAt">) =>
    request<DmPlatformConfig>("/direct-messages/platform-configs", {
      method: "POST",
      body: JSON.stringify(config),
    }),
  updateDmPlatformConfig: (configId: string, config: Partial<DmPlatformConfig>) =>
    request<DmPlatformConfig>(`/direct-messages/platform-configs/${configId}`, {
      method: "PATCH",
      body: JSON.stringify(config),
    }),
  dmTemplates: () => request<DmTemplate[]>("/direct-messages/templates"),
  createDmTemplate: (template: { name: string; platform: string; content: string; isActive: boolean }) =>
    request<DmTemplate>("/direct-messages/templates", {
      method: "POST",
      body: JSON.stringify(template),
    }),
  dmTasks: () => request<OutreachTask[]>("/direct-messages/tasks"),
  createDmTask: (task: {
    name: string;
    leadIds: string[];
    accountId?: string | null;
    templateId?: string | null;
    scheduledAt?: string | null;
  }) =>
    request<OutreachTask>("/direct-messages/tasks", {
      method: "POST",
      body: JSON.stringify(task),
    }),
  startDmTask: (taskId: string) =>
    request<OutreachTask>(`/direct-messages/tasks/${taskId}/start`, {
      method: "POST",
    }),
  dmConversations: () => request<DmConversation[]>("/direct-messages/conversations"),
  syncDmReplies: () =>
    request<DmSyncResult>("/direct-messages/sync-replies", {
      method: "POST",
    }),
  dmMessages: (conversationId?: string) =>
    request<DmMessage[]>(
      conversationId ? `/direct-messages/messages?conversationId=${encodeURIComponent(conversationId)}` : "/direct-messages/messages",
    ),
};
