const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8017/api";

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

export type IntentOverview = {
  totalCustomers: number;
  highIntent: number;
  needsHandoff: number;
  pendingWorkOrders: number;
  dncBlocked: number;
};

export type IntentCustomer = {
  id: string;
  leadId?: string | null;
  merchantName: string;
  platform: string;
  city: string;
  category: string;
  contactName?: string | null;
  phone?: string | null;
  intentLevel: string;
  intentScore: number;
  sourceChannels: string;
  latestSignal: string;
  evidenceSummary: string;
  ownerName: string;
  followStatus: string;
  nextFollowAt?: string | null;
  needHandoff: boolean;
  dncStatus: boolean;
  createdAt: string;
  updatedAt: string;
};

export type IntentEvent = {
  id: string;
  customerId: string;
  leadId?: string | null;
  sourceType: string;
  sourceRecordId?: string | null;
  channel: string;
  intentLevel: string;
  summary: string;
  evidenceText: string;
  needHandoff: boolean;
  createdAt: string;
};

export type FollowUpWorkOrder = {
  id: string;
  customerId: string;
  title: string;
  ownerName: string;
  status: string;
  priority: string;
  slaDueAt?: string | null;
  lastNote: string;
  closedReason?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type LearningOverview = {
  suggestions: number;
  pending: number;
  approved: number;
  published: number;
  knowledgeItems: number;
  activeExperiments: number;
};

export type LearningSuggestion = {
  id: string;
  sourceType: string;
  sourceRecordId?: string | null;
  targetType: string;
  title: string;
  summary: string;
  proposedContent: string;
  evidenceText: string;
  status: string;
  reviewer?: string | null;
  reviewNote?: string | null;
  impactScore: number;
  rollbackPoint?: string | null;
  createdAt: string;
  reviewedAt?: string | null;
  publishedAt?: string | null;
};

export type KnowledgeBaseItem = {
  id: string;
  title: string;
  category: string;
  content: string;
  status: string;
  version: string;
  sourceSuggestionId?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type LearningExperiment = {
  id: string;
  name: string;
  targetType: string;
  status: string;
  hypothesis: string;
  variant: string;
  sampleSize: number;
  successMetric: string;
  resultSummary: string;
  startedAt?: string | null;
  endedAt?: string | null;
  createdAt: string;
};

export type VoiceOverview = {
  profiles: number;
  usableProfiles: number;
  pendingAuthorization: number;
  trainingJobs: number;
  usageRecords: number;
  fallbackUsage: number;
  systemVoices: number;
  defaultVoice: string;
};

export type SystemVoice = {
  id: string;
  name: string;
  provider: string;
  gender: string;
  style: string;
  scenario: string;
  status: string;
  isDefault: boolean;
  sampleText: string;
};

export type VoiceProfile = {
  id: string;
  name: string;
  ownerName: string;
  scenario: string;
  status: string;
  authorizationStatus: string;
  sampleCount: number;
  fallbackVoice: string;
  consentMaterial: string;
  riskNote: string;
  createdAt: string;
  updatedAt: string;
};

export type VoiceTrainingJob = {
  id: string;
  profileId: string;
  status: string;
  progress: number;
  engine: string;
  sampleMinutes: number;
  message: string;
  createdAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
};

export type VoiceSample = {
  id: string;
  profileId: string;
  fileName: string;
  contentType: string;
  sizeBytes: number;
  durationSeconds: number;
  qualityStatus: string;
  transcript: string;
  uploadedBy: string;
  createdAt: string;
};

export type VoiceCloneRecord = {
  id: string;
  profileId: string;
  trainingJobId?: string | null;
  clonedVoiceName: string;
  engine: string;
  status: string;
  sampleCount: number;
  sampleMinutes: number;
  result: string;
  createdAt: string;
  completedAt?: string | null;
};

export type VoiceUsageRecord = {
  id: string;
  profileId?: string | null;
  taskId?: string | null;
  merchantName: string;
  scenario: string;
  result: string;
  fallbackUsed: boolean;
  createdAt: string;
};

export type ReportFunnelStep = {
  key: string;
  label: string;
  value: number;
  rate: number;
};

export type ReportOverview = {
  totalLeads: number;
  totalTouches: number;
  connected: number;
  highIntent: number;
  pendingWorkOrders: number;
  conversionRate: number;
  exportJobs: number;
  funnel: ReportFunnelStep[];
  updatedAt: string;
};

export type ChannelReport = {
  id: string;
  channel: string;
  leads: number;
  touches: number;
  connected: number;
  intent: number;
  handoff: number;
  conversionRate: number;
  status: string;
  insight: string;
};

export type SalesPerformanceReport = {
  id: string;
  ownerName: string;
  assignedCustomers: number;
  pendingWorkOrders: number;
  closedWorkOrders: number;
  highIntent: number;
  handoff: number;
  conversionRate: number;
  lastActivityAt?: string | null;
};

export type ReportExport = {
  id: string;
  reportType: string;
  dateRange: string;
  fileFormat: string;
  requester: string;
  status: string;
  downloadUrl: string;
  rowCount: number;
  sensitiveFieldsIncluded: boolean;
  createdAt: string;
  finishedAt?: string | null;
};

export type ReportExportCreate = {
  reportType: string;
  dateRange: string;
  fileFormat: string;
  requester: string;
  includeSensitiveFields: boolean;
};

export type SettingsGroupOverview = {
  groupKey: string;
  label: string;
  total: number;
  enabled: number;
  warning: number;
};

export type SettingsOverview = {
  totalSettings: number;
  enabledSettings: number;
  warningSettings: number;
  sensitiveSettings: number;
  auditLogs: number;
  groups: SettingsGroupOverview[];
};

export type SystemSetting = {
  id: string;
  groupKey: string;
  itemKey: string;
  label: string;
  value: string;
  valueType: string;
  status: string;
  description: string;
  sensitive: boolean;
  updatedBy: string;
  createdAt: string;
  updatedAt: string;
};

export type SystemSettingUpdate = {
  value?: string;
  status?: string;
  description?: string;
  actor?: string;
};

export type SystemAuditLog = {
  id: string;
  actor: string;
  action: string;
  targetType: string;
  targetId?: string | null;
  summary: string;
  beforeValue?: string | null;
  afterValue?: string | null;
  createdAt: string;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const errorText = await response.text();
    let detail: unknown;
    try {
      const errorBody = JSON.parse(errorText) as { detail?: unknown };
      detail = errorBody.detail;
    } catch {
      detail = null;
    }
    if (typeof detail === "string") {
      throw new Error(detail);
    }
    throw new Error(`API ${response.status}: ${errorText}`);
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
  intentOverview: () => request<IntentOverview>("/intent/overview"),
  intentCustomers: () => request<IntentCustomer[]>("/intent/customers"),
  updateIntentCustomer: (customerId: string, customer: Partial<IntentCustomer>) =>
    request<IntentCustomer>(`/intent/customers/${customerId}`, {
      method: "PATCH",
      body: JSON.stringify(customer),
    }),
  intentEvents: () => request<IntentEvent[]>("/intent/events"),
  intentCustomerEvents: (customerId: string) => request<IntentEvent[]>(`/intent/customers/${customerId}/events`),
  followUpWorkOrders: () => request<FollowUpWorkOrder[]>("/intent/work-orders"),
  learningOverview: () => request<LearningOverview>("/learning/overview"),
  learningSuggestions: () => request<LearningSuggestion[]>("/learning/suggestions"),
  updateLearningSuggestion: (suggestionId: string, suggestion: Partial<LearningSuggestion>) =>
    request<LearningSuggestion>(`/learning/suggestions/${suggestionId}`, {
      method: "PATCH",
      body: JSON.stringify(suggestion),
    }),
  knowledgeBase: () => request<KnowledgeBaseItem[]>("/learning/knowledge"),
  learningExperiments: () => request<LearningExperiment[]>("/learning/experiments"),
  voiceOverview: () => request<VoiceOverview>("/voice/overview"),
  systemVoices: () => request<SystemVoice[]>("/voice/system-voices"),
  voiceProfiles: () => request<VoiceProfile[]>("/voice/profiles"),
  createVoiceProfile: (profile: Omit<VoiceProfile, "id" | "createdAt" | "updatedAt">) =>
    request<VoiceProfile>("/voice/profiles", {
      method: "POST",
      body: JSON.stringify(profile),
    }),
  updateVoiceProfile: (profileId: string, profile: Partial<VoiceProfile>) =>
    request<VoiceProfile>(`/voice/profiles/${profileId}`, {
      method: "PATCH",
      body: JSON.stringify(profile),
    }),
  voiceSamples: () => request<VoiceSample[]>("/voice/samples"),
  uploadVoiceSample: (profileId: string, file: File, payload?: { uploadedBy?: string; durationSeconds?: number; transcript?: string }) => {
    const form = new FormData();
    form.append("file", file);
    form.append("uploaded_by", payload?.uploadedBy || "客户");
    form.append("duration_seconds", String(payload?.durationSeconds ?? 0));
    form.append("transcript", payload?.transcript || "");
    return request<VoiceSample>(`/voice/profiles/${profileId}/samples`, {
      method: "POST",
      body: form,
    });
  },
  voiceTrainingJobs: () => request<VoiceTrainingJob[]>("/voice/training-jobs"),
  createVoiceTrainingJob: (profileId: string, job: { engine: string; sampleMinutes: number; message?: string }) =>
    request<VoiceTrainingJob>(`/voice/profiles/${profileId}/training-jobs`, {
      method: "POST",
      body: JSON.stringify(job),
    }),
  voiceCloneRecords: () => request<VoiceCloneRecord[]>("/voice/clone-records"),
  voiceUsageRecords: () => request<VoiceUsageRecord[]>("/voice/usage-records"),
  reportsOverview: () => request<ReportOverview>("/reports/overview"),
  reportChannels: () => request<ChannelReport[]>("/reports/channels"),
  salesReports: () => request<SalesPerformanceReport[]>("/reports/sales"),
  reportExports: () => request<ReportExport[]>("/reports/exports"),
  createReportExport: (payload: ReportExportCreate) =>
    request<ReportExport>("/reports/exports", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  settingsOverview: () => request<SettingsOverview>("/settings/overview"),
  systemSettings: () => request<SystemSetting[]>("/settings/items"),
  updateSystemSetting: (settingId: string, payload: SystemSettingUpdate) =>
    request<SystemSetting>(`/settings/items/${settingId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  systemAuditLogs: () => request<SystemAuditLog[]>("/settings/audit-logs"),
};
