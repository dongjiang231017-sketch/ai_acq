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
};
