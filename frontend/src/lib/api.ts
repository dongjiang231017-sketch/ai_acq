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

function readStoredAccessToken(): string | null {
  try {
    const auth = JSON.parse(window.localStorage.getItem("ai_acq_client_auth") || "null") as {
      accessToken?: string;
    } | null;
    return auth?.accessToken || null;
  } catch {
    return null;
  }
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

export type OutreachTask = {
  id: string;
  name: string;
  channel: "collector" | "call" | "dm";
  status: string;
  targetCount: number;
  scheduledAt?: string | null;
};

export type LeadCollectionTask = {
  id: string;
  name: string;
  provider: string;
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
  status: string;
  requestedCount: number;
  fetchedCount: number;
  insertedCount: number;
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

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
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
  modules: () => request<ModuleSummary[]>("/modules"),
  leads: (params: LeadListParams = {}) => request<Lead[]>(`/leads${buildQuery(params)}`),
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
  collectionTasks: () => request<LeadCollectionTask[]>("/collections/tasks"),
  createCollectionTask: (
    task: Pick<LeadCollectionTask, "name" | "provider" | "cities" | "categories" | "keywords" | "targetPerKeyword"> & {
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
  collectionRuns: () => request<LeadCollectionRun[]>("/collections/runs"),
  rawLeadRecords: () => request<RawLeadRecord[]>("/collections/raw-records"),
};
