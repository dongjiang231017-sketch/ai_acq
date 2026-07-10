const LOCAL_API_PORT = 8001;
const DEFAULT_API_TIMEOUT_MS = 25000;

function resolveApiBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  if (configured) return configured;
  if (typeof window === "undefined") return `http://127.0.0.1:${LOCAL_API_PORT}/api`;

  const { hostname, protocol } = window.location;
  const apiHost = hostname === "localhost" ? "127.0.0.1" : hostname || "127.0.0.1";
  return `${protocol}//${apiHost}:${LOCAL_API_PORT}/api`;
}

export const API_BASE_URL = resolveApiBaseUrl();

// 分页信封（对应后端 app/schemas/common.py Page）
export type PageResp<T> = { items: T[]; total: number; page: number; pageSize: number };

export function apiAssetUrl(path: string) {
  if (!path) return "";
  if (/^https?:\/\//.test(path)) return path;
  const base = API_BASE_URL.replace(/\/api\/?$/, "");
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

const AUTH_STORAGE_KEY = "ai_acq_client_auth";

export type AuthUser = {
  id: string;
  username: string;
  displayName: string;
  email?: string | null;
  phone?: string | null;
  status: string;
  roles: string[];
  lastLoginAt?: string | null;
  createdAt: string;
};

export type LoginResponse = {
  accessToken: string;
  tokenType: string;
  expiresIn: number;
  user: AuthUser;
};

export type RegistrationRequestCreate = {
  projectName: string;
  companyName: string;
  contactName?: string | null;
  contactPhone: string;
  contactEmail?: string | null;
  desiredUsername?: string | null;
  password?: string | null;
  note?: string | null;
};

export type RegistrationRequestRead = Omit<RegistrationRequestCreate, "password"> & {
  id: string;
  status: string;
  createdAt: string;
};

export function readStoredAuth(): LoginResponse | null {
  try {
    return JSON.parse(window.localStorage.getItem(AUTH_STORAGE_KEY) || "null") as LoginResponse | null;
  } catch {
    return null;
  }
}

export function storeAuth(auth: LoginResponse) {
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
}

export function clearStoredAuth() {
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
}

function readStoredAccessToken(): string | null {
  return readStoredAuth()?.accessToken || null;
}

function authHeaders(): HeadersInit {
  const token = readStoredAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

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
  contactTitle?: string | null;
  wechatId?: string | null;
  platformUrl?: string | null;
  platformHomepageUrl?: string | null;
  sourcePoiId?: string | null;
  province?: string | null;
  district?: string | null;
  address?: string | null;
  longitude?: string | null;
  latitude?: string | null;
  source: string;
  intentScore: number;
  status: string;
  followUpStatus?: string;
  remark?: string | null;
  ownerUserId?: string | null;
  createdByUserId?: string | null;
  lastContactAt?: string | null;
  nextFollowUpAt?: string | null;
  createdAt?: string;
  updatedAt?: string;
};

export type LeadCollectionTask = {
  id: string;
  name: string;
  provider: string;
  collectionMode: string;
  cities: string[];
  categories: string[];
  keywords: string[];
  targetPerKeyword: number;
  status: string;
  lastRunStatus?: string | null;
  remark?: string | null;
  ownerUserId?: string | null;
  createdByUserId?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type LeadCollectionRun = {
  id: string;
  taskId: string;
  provider: string;
  collectionMode: string;
  status: string;
  requestedCount: number;
  fetchedCount: number;
  insertedCount: number;
  updatedCount: number;
  duplicateCount: number;
  failedCount: number;
  errorMessage?: string | null;
  startedAt: string;
  finishedAt?: string | null;
};

export type RawLeadRecord = {
  id: string;
  taskId: string;
  runId: string;
  leadId?: string | null;
  ownerUserId?: string | null;
  provider: string;
  sourcePoiId: string;
  name: string;
  city?: string | null;
  district?: string | null;
  category?: string | null;
  phone?: string | null;
  address?: string | null;
  sourceUrl?: string | null;
  longitude?: string | null;
  latitude?: string | null;
  importStatus: string;
  createdAt: string;
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
  taskId?: string | null;
  leadId?: string | null;
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

export type CallScriptEntry = {
  number: string;
  category: string;
  customerTrigger: string;
  content: string;
  executionTip: string;
  audioFile: string;
};

export type CallScript = {
  id: string;
  name: string;
  opening: string;
  qualification: string;
  objection: string;
  closing: string;
  entries?: CallScriptEntry[];
  audioMapping?: Record<string, string>;
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

export type VoiceGatewayProfile = {
  key: string;
  label: string;
  vendor: string;
  model: string;
  category: string;
  transport: string;
  host: string;
  sipPort: number;
  trunkName: string;
  maxChannels: number;
  lineType: string;
  adminUrl: string;
  discoveryMode: string;
  tested: boolean;
  capabilities: string[];
  notes: string[];
};

export type VoiceGatewayConfigField = {
  label: string;
  value: string;
  target: string;
  note: string;
};

export type VoiceGatewayDeliveryStep = {
  key: string;
  label: string;
  detail: string;
  expectedResult: string;
};

export type VoiceGatewayConfigCard = {
  lineId: string;
  customerName: string;
  lineName: string;
  gatewayProfileKey: string;
  gatewayLabel: string;
  sipServer: string;
  sipPort: number;
  sipTransport: string;
  sipUsername: string;
  sipAuthUsername: string;
  sipPasswordSecretAlias: string;
  sipPasswordDisplay: string;
  trunkName: string;
  channelCount: number;
  codecPrimary: string;
  codecSecondary: string;
  dtmfMode: string;
  rtpPortRange: string;
  routeDirection: string;
  fieldMapping: VoiceGatewayConfigField[];
  deliverySteps: VoiceGatewayDeliveryStep[];
};

export type VoiceGatewayLine = {
  id: string;
  ownerUserId: string;
  createdByUserId?: string | null;
  lineName: string;
  customerName: string;
  status: string;
  gatewayProfileKey: string;
  gatewayLabel: string;
  gatewayVendor: string;
  gatewayModel: string;
  gatewayCategory: string;
  deploymentMode: string;
  sipServerHost: string;
  sipServerPort: number;
  sipTransport: string;
  sipUsername: string;
  sipAuthUsername: string;
  sipPasswordSecretAlias: string;
  sipPasswordDisplay: string;
  trunkName: string;
  channelCount: number;
  codecPrimary: string;
  codecSecondary: string;
  dtmfMode: string;
  rtpPortRange: string;
  routeDirection: string;
  deviceAdminUrl: string;
  deviceSerial: string;
  deviceMac: string;
  networkNote: string;
  registrationStatus: string;
  routeStatus: string;
  simStatus: string;
  rtpStatus: string;
  acceptanceStatus: string;
  lastRegisteredAt?: string | null;
  lastPreflightAt?: string | null;
  notes: string;
  configCard: VoiceGatewayConfigCard;
  createdAt: string;
  updatedAt: string;
};

export type VoiceGatewayDeviceDiscoveryUpdate = {
  deviceAdminUrl?: string | null;
  deviceIp?: string | null;
  deviceMac?: string | null;
  deviceSerial?: string | null;
  source?: string;
  status?: string;
  summary?: string;
  detail?: string;
  evidenceJson?: string;
};

export type VoiceGatewayDeviceDiscoveryCreate = VoiceGatewayDeviceDiscoveryUpdate & {
  gatewayProfileKey?: string | null;
  gatewayLabel?: string | null;
  sipPort?: number | null;
};

export type VoiceGatewayDeviceDiscovery = {
  id: string;
  ownerUserId: string;
  reporterUserId?: string | null;
  matchedLineId?: string | null;
  status: string;
  source: string;
  gatewayProfileKey: string;
  gatewayLabel: string;
  deviceAdminUrl: string;
  deviceIp: string;
  deviceMac: string;
  deviceSerial: string;
  sipPort: number;
  summary: string;
  detail: string;
  evidenceJson: string;
  createdAt: string;
  updatedAt: string;
};

export type TelephonyConfig = {
  gatewayMode: string;
  asteriskDeploymentMode: string;
  voiceGatewayProfile: VoiceGatewayProfile;
  queueEnabled: boolean;
  queueName: string;
  redisUrlConfigured: boolean;
  asteriskHost: string;
  asteriskAmiPort: number;
  asteriskUsernameConfigured: boolean;
  asteriskTrunkName: string;
  asteriskMaxChannels: number;
  asteriskLiveCallEnabled: boolean;
  asteriskBulkCallEnabled: boolean;
};

export type TelephonyHealth = {
  checkedAt: string;
  gatewayMode: string;
  asteriskDeploymentMode: string;
  voiceGatewayProfile: VoiceGatewayProfile;
  configured: boolean;
  liveCallEnabled: boolean;
  bulkCallEnabled: boolean;
  amiReachable: boolean;
  authenticated: boolean;
  pingOk: boolean;
  trunkConfigured: boolean;
  trunkReachable: boolean | null;
  trunkStatus: string;
  maxChannels: number;
  readyForTestCall: boolean;
  errors: string[];
};

export type TelephonyPreflightStep = {
  key: string;
  label: string;
  status: "pass" | "warn" | "fail" | string;
  detail: string;
  action: string;
};

export type TelephonyPreflight = {
  checkedAt: string;
  voiceGatewayProfile: VoiceGatewayProfile;
  readyForDeviceTest: boolean;
  readyForSingleNumberTest: boolean;
  readyForBulkTasks: boolean;
  nextStep: string;
  health: TelephonyHealth;
  steps: TelephonyPreflightStep[];
};

export type TelephonyCellularDiagnostic = {
  status: "pass" | "warn" | "fail" | string;
  stage: string;
  title: string;
  summary: string;
  detail: string;
  actionItems: string[];
  technicalDetail: string;
  canRetry: boolean;
  customerActionRequired: boolean;
};

export type TelephonyRecoveryCommand = {
  command: string;
  ok: boolean;
  message: string;
  output: string;
};

export type TelephonyLineRecovery = {
  checkedAt: string;
  status: "pass" | "warn" | "fail" | string;
  summary: string;
  commands: TelephonyRecoveryCommand[];
  health: TelephonyHealth;
  nextStep: string;
};

export type TelephonyTestCallResult = {
  accepted: boolean;
  actionId: string;
  channel: string;
  requestedRoute: "pipeline" | "omni" | "livekit" | string;
  actualBridgeRoute: "pipeline" | "omni" | "livekit" | string;
  effectiveRoute: "pipeline" | "omni" | "livekit" | string;
  routeFallbackReason: string;
  routeMatched: boolean;
  gatewayStatus: string;
  message: string;
  rawPayload: string;
  verificationStage: string;
  cellularConfirmed: boolean;
  mediaLoopConfirmed: boolean;
  humanSpeechConfirmed: boolean;
  aiSpeechConfirmed: boolean;
  callScreeningDetected: boolean;
  bridgeError: string;
  conversationConfirmed: boolean;
  acceptanceReady: boolean;
  acceptanceNote: string;
  cellularDiagnostic: TelephonyCellularDiagnostic;
  autoRecovery?: TelephonyLineRecovery | null;
};

export type RealtimePipelineStep = {
  key: string;
  label: string;
  status: string;
  provider: string;
  latencyMs: number;
  detail: string;
};

export type RealtimeRouteOption = {
  key: "pipeline" | "omni" | "livekit";
  label: string;
  mode: string;
  summary: string;
  estimatedLatencyMs: number;
  estimatedAiCostPerMinute: number;
  readyForAsteriskMedia: boolean;
  isActive: boolean;
};

export type RealtimeRouteBenchmark = {
  key: "pipeline" | "omni" | "livekit" | string;
  label: string;
  status: "pass" | "warn" | "fail" | string;
  qualityScore: number;
  readinessScore: number;
  estimatedLatencyMs: number;
  estimatedAiCostPerMinute: number;
  costRank: number;
  riskLevel: "low" | "medium" | "high" | string;
  strengths: string[];
  risks: string[];
  nextAction: string;
};

export type RealtimeRouteBenchmarkReport = {
  recommendedRoute: "pipeline" | "omni" | "livekit" | string;
  status: "pass" | "warn" | "fail" | string;
  summary: string;
  lowCostFirst: boolean;
  latestScore?: number | null;
  latestTurnResponseMs?: number | null;
  benchmarks: RealtimeRouteBenchmark[];
};

export type RealtimeLearningSummary = {
  recentLessonCount: number;
  activeGuidanceCount: number;
  avoidPhraseCount: number;
  qualityTags: string[];
  latestGuidance: string[];
  avoidPhrases: string[];
  summary: string;
};

export type RealtimePipeline = {
  mode: string;
  bridgeMode: string;
  targetLatencyMs: number;
  estimatedLatencyMs: number;
  estimatedAiCostPerMinute: number;
  readyForMockCall: boolean;
  readyForAsteriskMedia: boolean;
  configuredRoute: "pipeline" | "omni" | "livekit" | string;
  actualBridgeRoute: "pipeline" | "omni" | "livekit" | string;
  routeMatched: boolean;
  nextStep: string;
  routeOptions: RealtimeRouteOption[];
  routeBenchmark?: RealtimeRouteBenchmarkReport | null;
  learning?: RealtimeLearningSummary | null;
  steps: RealtimePipelineStep[];
};

export type RealtimeVoiceSelection = {
  voiceId: string;
  voiceName: string;
  voiceType: string;
  provider: string;
  voiceParam?: string | null;
  externalVoiceId?: string | null;
};

export type RealtimeEvent = {
  id: string;
  at: string;
  type: string;
  actor: string;
  status: string;
  text: string;
  detail: string;
  latencyMs: number;
};

export type RealtimeSession = {
  id: string;
  status: string;
  mode: string;
  bridgeMode: string;
  merchantName: string;
  phone?: string | null;
  voice: RealtimeVoiceSelection;
  currentIntent: string;
  currentNode: string;
  interruptions: number;
  costEstimatePerMinute: number;
  latencyEstimateMs: number;
  startedAt: string;
  updatedAt: string;
  events: RealtimeEvent[];
};

export type RealtimeTurn = {
  session: RealtimeSession;
  asrText: string;
  intent: string;
  reply: string;
  interrupted: boolean;
  ttsChunks: Array<{
    index: number;
    text: string;
    durationMs: number;
    provider: string;
  }>;
};

export type RealtimeLiveEvent = {
  id: string;
  at: string;
  type: string;
  callId?: string | null;
  text?: string | null;
  reply?: string | null;
  strategy?: string | null;
  latencyMs: number;
  detail?: string | null;
  raw: Record<string, unknown>;
};

export type RealtimeLiveScoreMetric = {
  name: string;
  score: number;
  status: "pass" | "warn" | "fail" | string;
  weight: number;
  detail: string;
};

export type RealtimeLiveScore = {
  callId?: string | null;
  score: number;
  status: "pass" | "warn" | "fail" | string;
  summary: string;
  metrics: RealtimeLiveScoreMetric[];
};

export type RealtimeLiveState = {
  callId?: string | null;
  state: string;
  label: string;
  status: "active" | "closed" | "attention" | "unknown" | string;
  closeReason?: string | null;
  canAutoClose: boolean;
  autoCloseScheduled: boolean;
  humanSpeechConfirmed: boolean;
  callScreeningDetected: boolean;
  voicemailDetected: boolean;
  silenceDetected: boolean;
  noResponseDetected: boolean;
  hangupDetected: boolean;
  aiSpeechConfirmed: boolean;
  customerSpeechConfirmed: boolean;
  interruptionDetected: boolean;
  turnTakingStatus: "pass" | "warn" | "fail" | "unknown" | string;
  latestTurnResponseMs?: number | null;
  currentPhase?: string;
  phaseLabel?: string;
  turnAction?: string;
  latencyBreakdown?: Record<string, number | null | undefined>;
  lastCustomerText?: string | null;
  lastAiReply?: string | null;
  lastEventAt?: string | null;
  issues: string[];
};

export type RealtimeLiveEvents = {
  logPath: string;
  hasEvents: boolean;
  latestAt?: string | null;
  score?: RealtimeLiveScore | null;
  state?: RealtimeLiveState | null;
  events: RealtimeLiveEvent[];
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

export type DmDesktopLoginEvidence = {
  url: string;
  title: string;
  hasCookieEvidence: boolean;
  hasStorageEvidence: boolean;
  hasPageLoginSignal: boolean;
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

export type CommentInterceptOverview = {
  sources: number;
  comments: number;
  highIntentComments: number;
  convertedLeads: number;
};

export type CommentInterceptSource = {
  id: string;
  platform: string;
  sourceType: string;
  name: string;
  keyword: string;
  videoUrl: string;
  videoTitle: string;
  ownerAccountId?: string | null;
  syncStatus: string;
  syncFrequencyMinutes: number;
  keywordRules: string;
  autoReplyEnabled: boolean;
  humanConfirmRequired: boolean;
  lastSyncAt?: string | null;
  lastError?: string | null;
  createdAt: string;
};

export type SocialComment = {
  id: string;
  sourceId: string;
  platform: string;
  externalCommentId: string;
  videoUrl: string;
  authorName: string;
  authorProfileUrl: string;
  content: string;
  city: string;
  category: string;
  likeCount: number;
  replyCount: number;
  intentScore: number;
  intentLevel: string;
  status: string;
  riskStatus: string;
  commentedAt?: string | null;
  createdAt: string;
};

export type CommentSyncResult = {
  sourceId: string;
  imported: number;
  skipped: number;
  totalComments: number;
  message: string;
};

export type BrowserDmAction = {
  authorName: string;
  profileUrl?: string;
  status: string;
  sent: boolean;
  sendClicked?: boolean;
  sentConfirmed?: boolean;
  receiptStatus?: string;
  receiptMessage?: string;
  outgoingContent?: string;
  message?: string;
  url?: string;
  rawPayload?: Record<string, unknown> | null;
};

export type BrowserDmActionRecordResult = {
  sourceId: string;
  taskId?: string | null;
  recorded: number;
  sent: number;
  drafts: number;
  failed: number;
  leadIds: string[];
  conversationIds: string[];
  message: string;
};

export type CommentAutomationQueueItem = {
  sourceId: string;
  sourceName: string;
  platform: string;
  sourceType: string;
  keyword: string;
  videoUrl: string;
  syncStatus: string;
  lastSyncAt?: string | null;
  nextRunAt?: string | null;
  due: boolean;
  status: string;
  blockedReason: string;
  nextAccountId?: string | null;
  nextAccountName?: string | null;
  eligibleAccountCount: number;
  remainingQuota: number;
  riskStatus: string;
  selectorProfile: string;
  liveSendSupported: boolean;
};

export type CommentAutomationQueueOverview = {
  items: CommentAutomationQueueItem[];
  dueCount: number;
  readyCount: number;
  pausedCount: number;
  blockedCount: number;
  message: string;
};

export type CommentAutomationRiskReport = {
  platform?: string;
  accountId?: string | null;
  status: string;
  reason?: string;
  step?: string;
  url?: string;
  rawPayload?: Record<string, unknown> | null;
};

export type CommentAutomationRiskResult = {
  sourceId: string;
  accountId?: string | null;
  paused: boolean;
  sourceStatus: string;
  accountStatus?: string | null;
  riskStatus?: string | null;
  message: string;
};

export type BrowserCapturedComment = {
  externalCommentId?: string;
  authorName: string;
  authorProfileUrl?: string;
  content: string;
  videoUrl?: string;
  city?: string;
  category?: string;
  likeCount?: number;
  replyCount?: number;
  commentedAt?: string | null;
  rawPayload?: Record<string, unknown> | null;
};

export type CommentConvertResult = {
  converted: number;
  skipped: number;
  leadIds: string[];
  message: string;
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
  cloneTrainingEnabled: boolean;
  cloneEngineName: string;
  cloneEngineStatus: string;
  cloneEngineMessage: string;
};

export type SystemVoice = {
  id: string;
  name: string;
  provider: string;
  voiceParam: string;
  gender: string;
  style: string;
  scenario: string;
  status: string;
  isDefault: boolean;
  sampleText: string;
};

export type SystemVoicePreview = {
  voiceId: string;
  voiceParam: string;
  audioUrl: string;
  previewText: string;
  message: string;
};

export type VoiceDefaultSelection = {
  voiceId: string;
  voiceName: string;
  voiceType: "system" | "clone" | string;
  provider: string;
  voiceParam?: string | null;
  externalVoiceId?: string | null;
};

export type VoiceDefaultSelectionResult = VoiceDefaultSelection & {
  message: string;
  effectiveWithoutRestart: boolean;
};

export type VoiceCacheStatus = {
  enabled: boolean;
  root: string;
  profile: string;
  displayName: string;
  assetVersion: string;
  openingSeq?: string;
  manifestLoaded: boolean;
  itemCount: number;
  intentCount: number;
  minConfidence: number;
};

export type VoiceProviderStatus = {
  provider: string;
  configured: boolean;
  ready: boolean;
  status: string;
  message: string;
  engineName: string;
  cloneModel: string;
  ttsModel: string;
  samplePublicBaseUrlConfigured: boolean;
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
  externalVoiceId: string;
  previewAudioUrl: string;
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

function readApiError(data: unknown, status: number): string {
  if (data && typeof data === "object") {
    const body = data as { detail?: unknown; errors?: unknown };
    if (Array.isArray(body.errors) && body.errors.length > 0) {
      return body.errors.map(String).join("；");
    }
    if (typeof body.detail === "string" && body.detail.trim()) {
      return body.detail;
    }
  }
  return `请求失败，请稍后再试（${status}）`;
}

async function readResponseError(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) return `请求失败，请稍后再试（${response.status}）`;
  try {
    return readApiError(JSON.parse(text), response.status);
  } catch {
    return `请求失败，请稍后再试（${response.status}）`;
  }
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function fetchWithRetry(input: RequestInfo | URL, init?: RequestInit, retries = 1): Promise<Response> {
  let lastError: unknown = null;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await fetch(input, init);
    } catch (error) {
      lastError = error;
      if (attempt >= retries) break;
      await wait(600);
    }
  }

  const detail =
    lastError instanceof Error && lastError.message
      ? `（${lastError.message}）`
      : "";
  throw new Error(`无法连接服务器，请确认后端服务已启动或刷新页面后重试。${detail}`);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), DEFAULT_API_TIMEOUT_MS);
  const upstreamSignal = options?.signal;
  const abortFromUpstream = () => controller.abort();
  upstreamSignal?.addEventListener("abort", abortFromUpstream, { once: true });

  let response: Response;
  try {
    response = await fetchWithRetry(`${API_BASE_URL}${path}`, {
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...authHeaders(),
        ...options?.headers,
      },
      signal: controller.signal,
      ...options,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`请求超时，请检查网络或服务器状态后重试：${path}`);
    }
    if (error instanceof Error) throw error;
    throw new Error("无法连接服务器，请确认后端服务已启动或刷新页面后重试。");
  } finally {
    window.clearTimeout(timeout);
    upstreamSignal?.removeEventListener("abort", abortFromUpstream);
  }

  if (!response.ok) {
    throw new Error(await readResponseError(response));
  }

  return response.json() as Promise<T>;
}

type LeadListParams = {
  source?: string;
  platform?: string;
  city?: string;
  category?: string;
  status?: string;
};

function buildQuery(params: Record<string, string | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () => request<{ status: string; service: string }>("/health"),
  login: (payload: { identifier: string; password: string }) =>
    request<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  me: () => request<AuthUser>("/auth/me"),
  createRegistrationRequest: (payload: RegistrationRequestCreate) =>
    request<RegistrationRequestRead>("/auth/registration-requests", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  modules: () => request<ModuleSummary[]>("/modules"),
  // 2026-07-09：记录列表类接口后端已改分页信封 {items,total,page,pageSize}。
  // 旧函数保持返回数组（解包 items，一次拿全量 ≤1000），列表 UI 用客户端分页渲染。
  leads: (params: LeadListParams = {}) => request<PageResp<Lead>>(`/leads${buildQuery(params)}`).then((r) => r.items),
  importLeadsExcel: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ total: number; inserted: number; duplicated: number; invalid: number }>("/leads/import-excel", {
      method: "POST",
      body: form,
    });
  },
  leadsPage: (params: LeadListParams & { page?: number; pageSize?: number } = {}) => {
    const { page, pageSize, ...rest } = params;
    return request<PageResp<Lead>>(
      `/leads${buildQuery({ ...rest, page: page ? String(page) : undefined, pageSize: pageSize ? String(pageSize) : undefined })}`,
    );
  },
  createLead: (lead: Omit<Lead, "id" | "intentScore" | "status">) =>
    request<Lead>("/leads", {
      method: "POST",
      body: JSON.stringify(lead),
    }),
  collectionTasks: () => request<LeadCollectionTask[]>("/collections/tasks"),
  createCollectionTask: (
    task: Pick<LeadCollectionTask, "name" | "provider" | "cities" | "categories" | "keywords" | "targetPerKeyword"> & {
      collectionMode?: string | null;
      remark?: string | null;
    },
  ) =>
    request<LeadCollectionTask>("/collections/tasks", {
      method: "POST",
      body: JSON.stringify(task),
    }),
  runCollectionTask: (taskId: string) =>
    request<LeadCollectionRun>(`/collections/tasks/${taskId}/run`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  collectionRuns: () => request<PageResp<LeadCollectionRun>>("/collections/runs").then((r) => r.items),
  rawLeadRecords: () => request<PageResp<RawLeadRecord>>("/collections/raw-records").then((r) => r.items),
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
  callRecords: () => request<PageResp<CallRecord>>("/outbound/records").then((r) => r.items),
  liveCalls: () => request<CallRecord[]>("/outbound/live"),
  callScripts: () => request<CallScript[]>("/outbound/scripts"),
  createCallScript: (script: Omit<CallScript, "id" | "createdAt">) =>
    request<CallScript>("/outbound/scripts", {
      method: "POST",
      body: JSON.stringify(script),
    }),
  updateCallScript: (scriptId: string, script: Omit<CallScript, "id" | "createdAt">) =>
    request<CallScript>(`/outbound/scripts/${scriptId}`, {
      method: "PATCH",
      body: JSON.stringify(script),
    }),
  recallRules: () => request<RecallRule[]>("/outbound/recall-rules"),
  updateRecallRule: (ruleId: string, rule: Omit<RecallRule, "id">) =>
    request<RecallRule>(`/outbound/recall-rules/${ruleId}`, {
      method: "PATCH",
      body: JSON.stringify(rule),
    }),
  telephonyConfig: () => request<TelephonyConfig>("/outbound/telephony/config"),
  telephonyHealth: () => request<TelephonyHealth>("/outbound/telephony/health"),
  telephonyPreflight: (phone?: string) => {
    const query = phone?.trim() ? `?phone=${encodeURIComponent(phone.trim())}` : "";
    return request<TelephonyPreflight>(`/outbound/telephony/preflight${query}`);
  },
  voiceGatewayLines: () => request<VoiceGatewayLine[]>("/delivery/voice-gateway-lines"),
  voiceGatewayDeviceDiscoveries: () => request<VoiceGatewayDeviceDiscovery[]>("/delivery/voice-gateway-device-discoveries"),
  createVoiceGatewayDeviceDiscovery: (payload: VoiceGatewayDeviceDiscoveryCreate) =>
    request<VoiceGatewayDeviceDiscovery>("/delivery/voice-gateway-device-discoveries", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  reportVoiceGatewayDeviceDiscovery: (lineId: string, payload: VoiceGatewayDeviceDiscoveryUpdate) =>
    request<VoiceGatewayLine>(`/delivery/voice-gateway-lines/${lineId}/device-discovery`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createTelephonyTestCall: (payload: {
    phone: string;
    callerId?: string | null;
    merchantName?: string | null;
    conversationRoute?: "pipeline" | "omni" | "livekit";
  }) =>
    request<TelephonyTestCallResult>("/outbound/telephony/test-call", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  recoverTelephonyLine: () =>
    request<TelephonyLineRecovery>("/outbound/telephony/recover-line", {
      method: "POST",
    }),
  realtimePipeline: () => request<RealtimePipeline>("/outbound/realtime/pipeline"),
  realtimeLiveEvents: (limit = 80, callId?: string | null) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (callId?.trim()) params.set("call_id", callId.trim());
    return request<RealtimeLiveEvents>(`/outbound/realtime/live-events?${params.toString()}`);
  },
  createRealtimeSession: (payload: {
    merchantName: string;
    phone?: string | null;
    voice: RealtimeVoiceSelection;
    conversationRoute?: "pipeline" | "omni" | "livekit";
  }) =>
    request<RealtimeSession>("/outbound/realtime/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  realtimeUtterance: (sessionId: string, payload: { text: string; bargeIn?: boolean }) =>
    request<RealtimeTurn>(`/outbound/realtime/sessions/${sessionId}/utterances`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  interruptRealtimeSession: (sessionId: string) =>
    request<RealtimeSession>(`/outbound/realtime/sessions/${sessionId}/interrupt`, {
      method: "POST",
    }),
  completeRealtimePlayback: (sessionId: string) =>
    request<RealtimeSession>(`/outbound/realtime/sessions/${sessionId}/playback-complete`, {
      method: "POST",
    }),
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
  completeDmDesktopLoginCheck: (accountId: string, evidence: DmDesktopLoginEvidence) =>
    request<DmAccount>(`/direct-messages/accounts/${accountId}/desktop-login-check`, {
      method: "POST",
      body: JSON.stringify(evidence),
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
  commentInterceptOverview: () => request<CommentInterceptOverview>("/direct-messages/intercepts/overview"),
  commentInterceptAutomationQueue: () =>
    request<CommentAutomationQueueOverview>("/direct-messages/intercepts/automation/queue"),
  preflightCommentInterceptAutomation: (sourceId: string) =>
    request<CommentAutomationQueueItem>(`/direct-messages/intercepts/sources/${sourceId}/automation-preflight`, {
      method: "POST",
    }),
  reportCommentInterceptAutomationRisk: (sourceId: string, payload: CommentAutomationRiskReport) =>
    request<CommentAutomationRiskResult>(`/direct-messages/intercepts/sources/${sourceId}/automation-risk`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  commentInterceptSources: () => request<CommentInterceptSource[]>("/direct-messages/intercepts/sources"),
  createCommentInterceptSource: (source: {
    platform: string;
    sourceType: string;
    name: string;
    keyword: string;
    videoUrl: string;
    videoTitle: string;
    ownerAccountId?: string | null;
    syncFrequencyMinutes: number;
    keywordRules: string;
    autoReplyEnabled: boolean;
    humanConfirmRequired: boolean;
  }) =>
    request<CommentInterceptSource>("/direct-messages/intercepts/sources", {
      method: "POST",
      body: JSON.stringify(source),
    }),
  syncCommentInterceptSource: (sourceId: string) =>
    request<CommentSyncResult>(`/direct-messages/intercepts/sources/${sourceId}/sync`, {
      method: "POST",
    }),
  captureCommentInterceptFromBrowser: (
    sourceId: string,
    payload: {
      platform: string;
      pageUrl: string;
      pageTitle: string;
      comments: BrowserCapturedComment[];
    },
  ) =>
    request<CommentSyncResult>(`/direct-messages/intercepts/sources/${sourceId}/browser-capture`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  recordCommentInterceptDmActions: (
    sourceId: string,
    payload: {
      platform: string;
      accountId?: string | null;
      messageContent: string;
      actions: BrowserDmAction[];
    },
  ) =>
    request<BrowserDmActionRecordResult>(`/direct-messages/intercepts/sources/${sourceId}/browser-dm-actions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  socialComments: (params?: { sourceId?: string; platform?: string; status?: string; intentLevel?: string }) => {
    const query = new URLSearchParams();
    if (params?.sourceId) query.set("sourceId", params.sourceId);
    if (params?.platform) query.set("platform", params.platform);
    if (params?.status) query.set("status", params.status);
    if (params?.intentLevel) query.set("intentLevel", params.intentLevel);
    return request<SocialComment[]>(`/direct-messages/intercepts/comments${query.toString() ? `?${query.toString()}` : ""}`);
  },
  convertCommentsToLeads: (payload: { commentIds: string[]; city?: string; category?: string; status?: string }) =>
    request<CommentConvertResult>("/direct-messages/intercepts/comments/convert", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
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
  voiceProviderStatus: (probe = false) => request<VoiceProviderStatus>(`/voice/provider/status${probe ? "?probe=true" : ""}`),
  systemVoices: () => request<SystemVoice[]>("/voice/system-voices"),
  systemVoicePreview: (voiceId: string) => request<SystemVoicePreview>(`/voice/system-voices/${voiceId}/preview`, { method: "POST" }),
  voiceCacheStatus: () => request<VoiceCacheStatus>("/voice/cache/status"),
  saveVoiceCacheStatus: (payload: { enabled: boolean }) =>
    request<VoiceCacheStatus>("/voice/cache/status", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  defaultVoice: () => request<VoiceDefaultSelectionResult>("/voice/default-voice"),
  saveDefaultVoice: (payload: VoiceDefaultSelection) =>
    request<VoiceDefaultSelectionResult>("/voice/default-voice", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
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
