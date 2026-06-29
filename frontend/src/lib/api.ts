const DEFAULT_API_BASE_URL = `${window.location.protocol}//${window.location.hostname}:8001/api`;
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL;

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
  platformHomepageUrl?: string | null;
  province?: string | null;
  district?: string | null;
  address?: string | null;
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

export type OutreachTask = {
  id: string;
  name: string;
  channel: "collector" | "call" | "dm";
  status: string;
  targetCount: number;
  scheduledAt?: string | null;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
      ...options,
    });
  } catch {
    throw new Error("无法连接服务器，请确认后端服务已启动。");
  }

  if (!response.ok) {
    throw new Error(await readResponseError(response));
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
};
