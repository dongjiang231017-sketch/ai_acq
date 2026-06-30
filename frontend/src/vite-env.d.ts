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
  message: string;
  url?: string;
};

type AiAcqDesktopCommentAutomationResult = AiAcqDesktopCommentCaptureResult & {
  steps: AiAcqDesktopAutomationStep[];
  dmActions: AiAcqDesktopDmAction[];
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
      dmMessage?: string;
      allowSend?: boolean;
    }) => Promise<AiAcqDesktopCommentAutomationResult>;
  };
}
