/// <reference types="vite/client" />

type AiAcqDesktopLoginEvidence = {
  url: string;
  title: string;
  hasCookieEvidence: boolean;
  hasStorageEvidence: boolean;
  hasPageLoginSignal: boolean;
};

interface Window {
  aiAcqDesktop?: {
    isDesktopClient: boolean;
    inspectDmLogin: (payload: { webContentsId: number; platform: string }) => Promise<AiAcqDesktopLoginEvidence>;
  };
}
