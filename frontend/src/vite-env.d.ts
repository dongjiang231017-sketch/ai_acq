/// <reference types="vite/client" />

type AiAcqDesktopLoginEvidence = {
  url: string;
  title: string;
  hasCookieEvidence: boolean;
  hasStorageEvidence: boolean;
  hasPageLoginSignal: boolean;
};

type AiAcqDesktopCapturedComment = {
  externalCommentId?: string;
  authorName: string;
  authorProfileUrl?: string;
  content: string;
  videoUrl?: string;
  likeCount?: number;
  replyCount?: number;
  commentedAt?: string | null;
  rawPayload?: Record<string, unknown> | null;
};

type AiAcqDesktopCommentCaptureResult = {
  url: string;
  title: string;
  platform: string;
  comments: AiAcqDesktopCapturedComment[];
  error?: string;
};

type AiAcqDesktopAutomationStep = {
  name: string;
  status: string;
  message: string;
  [key: string]: unknown;
};

type AiAcqDesktopDmAction = {
  authorName: string;
  profileUrl: string;
  status: string;
  sent: boolean;
  sendClicked?: boolean;
  sentConfirmed?: boolean;
  receiptStatus?: string;
  receiptMessage?: string;
  outgoingContent?: string;
  message: string;
  url?: string;
};

type AiAcqDesktopCommentAutomationResult = AiAcqDesktopCommentCaptureResult & {
  steps: AiAcqDesktopAutomationStep[];
  dmActions: AiAcqDesktopDmAction[];
};

type AiAcqDesktopAsteriskCheck = {
  key: string;
  label: string;
  status: "pass" | "warn" | "fail" | string;
  detail: string;
};

type AiAcqDesktopAsteriskStatus = {
  deliveryMode: string;
  runtimeMode: string;
  runtimeFound: boolean;
  runtimePath: string;
  status: "running" | "starting" | "stopped" | "blocked" | string;
  running: boolean;
  managedPid: number | null;
  amiHost: string;
  amiPort: number;
  sipPort: number;
  trunkName: string;
  voiceGatewayProfile: string;
  voiceGatewayLabel: string;
  voiceGatewayHost: string;
  voiceGatewaySipPort: number;
  voiceGatewayRegisterEnabled: boolean;
  uc100Host: string;
  uc100SipPort: number;
  uc100RegisterEnabled?: boolean;
  asteriskAdvertisedHost?: string;
  asteriskLocalNet?: string;
  maxChannels: number;
  audioSocketHost: string;
  audioSocketPort: number;
  audioSocketReachable: boolean;
  voiceGatewayDiscovery?: {
    status: "current" | "updated" | "not_found" | "disabled" | string;
    host?: string;
    sipPort?: number;
    previousHost?: string;
    previousSipPort?: number;
    source?: string;
    message?: string;
    reload?: {
      attempted: boolean;
      ok: boolean;
      message: string;
    };
  };
  customerDelivery?: {
    status: "pass" | "warn" | "fail" | string;
    title: string;
    message: string;
    gatewayAddress: string;
    previousGatewayAddress?: string;
    discoveryStatus?: string;
    discoverySource?: string;
    actionItems: string[];
  };
  configDir: string;
  stateDir: string;
  backendEnvPath: string;
  backendEnvReady: boolean;
  checks: AiAcqDesktopAsteriskCheck[];
  lastExit: { code: number | null; signal: string | null; at: string } | null;
  nextStep: string;
};

type AiAcqDesktopAppInfo = {
  appName: string;
  version: string;
  remoteFrontendUrl: string;
  manifestUrl: string;
  onlineFrontendEnabled: boolean;
};

type AiAcqDesktopUpdateCheck = {
  currentVersion: string;
  latestVersion: string;
  latestRevision: string;
  updateAvailable: boolean;
  updateUrl: string;
  manifestUrl: string;
  remoteFrontendUrl: string;
  onlineFrontendEnabled: boolean;
  appName: string;
  message: string;
};

interface Window {
  aiAcqDesktop?: {
    isDesktopClient: boolean;
    inspectDmLogin: (payload: { webContentsId: number; platform: string }) => Promise<AiAcqDesktopLoginEvidence>;
    captureCommentIntercept: (payload: {
      webContentsId: number;
      platform: string;
    }) => Promise<AiAcqDesktopCommentCaptureResult>;
    runCommentInterceptAutomation: (payload: {
      webContentsId: number;
      platform: string;
      keyword?: string;
      sourceUrl?: string;
      sourceType?: string;
      scrollRounds?: number;
      maxAuthors?: number;
      sendIntervalSeconds?: number;
      dmMessage?: string;
      allowSend?: boolean;
      selectors?: {
        riskCheckSelector?: string;
        messageButtonSelector?: string;
        inputSelector?: string;
        sendButtonSelector?: string;
        sentSuccessSelector?: string;
      };
    }) => Promise<AiAcqDesktopCommentAutomationResult>;
    getAsteriskSidecarStatus: () => Promise<AiAcqDesktopAsteriskStatus>;
    startAsteriskSidecar: () => Promise<AiAcqDesktopAsteriskStatus>;
    stopAsteriskSidecar: () => Promise<AiAcqDesktopAsteriskStatus>;
    getAppInfo: () => Promise<AiAcqDesktopAppInfo>;
    checkForClientUpdate: (payload?: { prompt?: boolean }) => Promise<AiAcqDesktopUpdateCheck>;
    openClientUpdate: (url: string) => Promise<{ ok: boolean; message?: string }>;
  };
}
