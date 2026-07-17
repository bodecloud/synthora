// Typed client for the Synthora REST + WebSocket API.

const TOKEN_KEY = "synthora_token";

export interface PipelineSpec {
  id: string;
  name: string;
  description: string;
  tags: string[];
}

export interface SessionSummary {
  id: string;
  title: string;
  tags: string[];
  workspace_id: string;
  created_at: string;
}

export interface RunSummary {
  id: string;
  question: string;
  pipeline_id: string;
  session_id: string | null;
  status: string;
  created_at: string;
  finished_at: string | null;
}

export interface RunDetail extends RunSummary {
  brief: string | null;
  error: string | null;
  config: Record<string, unknown>;
  started_at: string | null;
}

export interface RunEvent {
  run_id: string;
  type: string;
  message: string;
  node: string | null;
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface Citation {
  id: string;
  url: string;
  title: string;
  snippet: string;
  confidence: number;
  index: number | null;
  verified: boolean;
}

export interface KnowledgeNode {
  id: string;
  name: string;
  summary: string;
  parent_id: string | null;
  infos: Citation[];
}

export interface KnowledgeEdge {
  id: string;
  source_id: string;
  target_id: string;
  relation: string;
}

export interface DiscourseTurn {
  id: string;
  run_id: string | null;
  speaker: string;
  role: string;
  utterance: string;
  intent: string;
  citations: Citation[];
  created_at: string;
}

export interface NewsSubscription {
  id: string;
  workspace_id: string;
  query: string;
  cadence: string;
  last_run_at: string | null;
  created_at: string;
}

export interface NewsItem {
  id: string;
  subscription_id: string;
  title: string;
  url: string;
  summary: string;
  created_at: string;
}

export interface DocumentSummary {
  id: string;
  title: string;
  url: string;
  workspace_id: string;
  created_at: string;
}

export interface RunMetrics {
  run_id: string;
  llm_calls: number;
  prompt_chars: number;
  completion_chars: number;
  search_calls: number;
  created_at: string;
}

export interface Providers {
  llm_providers: string[];
  search_engines: string[];
  search_strategies: string[];
}

export interface ResearchConfig {
  search_engines?: string[];
  search_strategy?: string;
  allow_clarification?: boolean;
  planner_model?: string;
  researcher_model?: string;
  compressor_model?: string;
  writer_model?: string;
  critic_model?: string;
  num_perspectives?: number;
  max_discourse_turns?: number;
  max_autonomous_cycles?: number;
  extra?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface StartResearchOptions {
  session_id?: string | null;
  config?: ResearchConfig;
}

let authToken: string | null = null;

/** Set the in-memory Bearer token and persist (or clear) localStorage. */
export function setToken(token: string | null) {
  authToken = token;
  if (typeof localStorage !== "undefined") {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  }
}

/** Load a previously stored token into memory and return it. */
export function loadStoredToken(): string | null {
  if (typeof localStorage === "undefined") return null;
  const token = localStorage.getItem(TOKEN_KEY);
  authToken = token;
  return token;
}

export function getToken(): string | null {
  return authToken;
}

export function clearToken() {
  setToken(null);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  const resp = await fetch(path, { ...init, headers });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status}: ${body}`);
  }
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export function exportUrl(
  runId: string,
  format: "markdown" | "html" | "pdf" = "markdown",
): string {
  return `/api/v1/research/${runId}/export?format=${format}`;
}

/** Fetch an export file with auth and trigger a browser download. */
export async function downloadExport(
  runId: string,
  format: "markdown" | "html" | "pdf",
): Promise<void> {
  const headers: Record<string, string> = {};
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  const resp = await fetch(exportUrl(runId, format), { headers });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status}: ${body}`);
  }
  const blob = await resp.blob();
  const ext = format === "html" ? "html" : format === "pdf" ? "pdf" : "md";
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = `synthora-${runId}.${ext}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

export const api = {
  register: (username: string, password: string) =>
    request<{ token: string; user_id: string }>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  login: (username: string, password: string) =>
    request<{ token: string; user_id: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  listSessions: () =>
    request<{ sessions: SessionSummary[] }>("/api/v1/sessions").then(
      (d) => d.sessions,
    ),
  createSession: (title: string, tags: string[] = []) =>
    request<SessionSummary>("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ title, tags }),
    }),
  getSession: (id: string) =>
    request<SessionSummary & { runs: RunSummary[] }>(`/api/v1/sessions/${id}`),
  deleteSession: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/api/v1/sessions/${id}`, {
      method: "DELETE",
    }),

  listPipelines: () =>
    request<{ pipelines: PipelineSpec[] }>("/api/v1/pipelines").then(
      (d) => d.pipelines,
    ),
  listProviders: () => request<Providers>("/api/v1/providers"),
  listSettings: () =>
    request<{
      settings: Array<{ key: string; value: Record<string, unknown> }>;
    }>("/api/v1/settings").then((d) => d.settings),
  getSetting: (key: string) =>
    request<{ key: string; value: Record<string, unknown> }>(
      `/api/v1/settings/${encodeURIComponent(key)}`,
    ),
  putSetting: (key: string, value: Record<string, unknown>) =>
    request<{ key: string; value: Record<string, unknown> }>(
      `/api/v1/settings/${encodeURIComponent(key)}`,
      {
        method: "PUT",
        body: JSON.stringify({ value }),
      },
    ),
  listRuns: (sessionId?: string) => {
    const q = sessionId
      ? `?session_id=${encodeURIComponent(sessionId)}`
      : "";
    return request<{ runs: RunSummary[] }>(`/api/v1/research${q}`).then(
      (d) => d.runs,
    );
  },
  getRun: (id: string) => request<RunDetail>(`/api/v1/research/${id}`),
  startResearch: (
    question: string,
    pipelineId: string,
    options?: StartResearchOptions,
  ) =>
    request<{ run_id: string; status: string; session_id: string | null }>(
      "/api/v1/research",
      {
        method: "POST",
        body: JSON.stringify({
          question,
          pipeline_id: pipelineId,
          session_id: options?.session_id ?? null,
          config: options?.config,
        }),
      },
    ),
  resumeResearch: (id: string, answer: string) =>
    request<{ run_id: string; status: string; resumed: boolean }>(
      `/api/v1/research/${id}/resume`,
      {
        method: "POST",
        body: JSON.stringify({ answer }),
      },
    ),
  deleteRun: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/api/v1/research/${id}`, {
      method: "DELETE",
    }),
  cancelRun: (id: string) =>
    request(`/api/v1/research/${id}/cancel`, { method: "POST", body: "{}" }),
  steerRun: (id: string, message: string) =>
    request(`/api/v1/research/${id}/steer`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  getReport: (id: string) =>
    request<{
      report_markdown: string;
      citations: Citation[];
      status: string;
    }>(`/api/v1/research/${id}/report`),
  getEvents: (id: string) =>
    request<{ events: RunEvent[] }>(`/api/v1/research/${id}/events`).then(
      (d) => d.events,
    ),
  getKnowledgeMap: (id: string) =>
    request<{ nodes: KnowledgeNode[]; edges: KnowledgeEdge[] }>(
      `/api/v1/research/${id}/knowledge-map`,
    ),
  getDiscourse: (id: string) =>
    request<{ turns: DiscourseTurn[] }>(
      `/api/v1/research/${id}/discourse`,
    ).then((d) => d.turns),

  followupResearch: (runId: string, question: string, pipelineId?: string) =>
    request<{
      run_id: string;
      status: string;
      session_id: string | null;
      parent_run_id: string;
    }>(`/api/v1/research/${runId}/followup`, {
      method: "POST",
      body: JSON.stringify({
        question,
        pipeline_id: pipelineId ?? null,
      }),
    }),

  getRunMetrics: (id: string) =>
    request<RunMetrics>(`/api/v1/research/${id}/metrics`),
  metricsSummary: () =>
    request<{
      runs: number;
      llm_calls: number;
      prompt_chars: number;
      completion_chars: number;
      search_calls: number;
    }>("/api/v1/metrics/summary"),

  chat: (message: string, sessionId?: string | null) =>
    request<{ run_id: string; status: string; session_id: string }>(
      "/api/v1/chat",
      {
        method: "POST",
        body: JSON.stringify({
          message,
          session_id: sessionId ?? null,
        }),
      },
    ),

  listNewsSubscriptions: () =>
    request<{ subscriptions: NewsSubscription[] }>(
      "/api/v1/news/subscriptions",
    ).then((d) => d.subscriptions),
  createNewsSubscription: (query: string, cadence = "daily") =>
    request<NewsSubscription>("/api/v1/news/subscriptions", {
      method: "POST",
      body: JSON.stringify({ query, cadence }),
    }),
  deleteNewsSubscription: (id: string) =>
    request<{ deleted: boolean; id: string }>(
      `/api/v1/news/subscriptions/${id}`,
      { method: "DELETE" },
    ),
  updateNewsSubscription: (
    id: string,
    patch: { query?: string; cadence?: string },
  ) =>
    request<NewsSubscription>(`/api/v1/news/subscriptions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  fetchNewsSubscription: (id: string) =>
    request<{
      subscription_id: string;
      fetched: number;
      items: NewsItem[];
    }>(`/api/v1/news/subscriptions/${id}/fetch`, {
      method: "POST",
      body: "{}",
    }),
  listNewsItems: (subscriptionId?: string) => {
    const q = subscriptionId
      ? `?subscription_id=${encodeURIComponent(subscriptionId)}`
      : "";
    return request<{ items: NewsItem[] }>(`/api/v1/news/items${q}`).then(
      (d) => d.items,
    );
  },

  clearHistory: () =>
    request<{ deleted: number }>("/api/v1/research/clear", {
      method: "POST",
      body: "{}",
    }),

  listDocuments: () =>
    request<{ documents: DocumentSummary[] }>("/api/v1/documents").then(
      (d) => d.documents,
    ),
  createDocument: (title: string, content: string, url?: string) =>
    request<DocumentSummary>("/api/v1/documents", {
      method: "POST",
      body: JSON.stringify({ title, content, url: url || null }),
    }),
  uploadDocument: async (file: File, title?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (title?.trim()) form.append("title", title.trim());
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const resp = await fetch("/api/v1/documents/upload", {
      method: "POST",
      headers,
      body: form,
    });
    if (!resp.ok) {
      const body = await resp.text();
      throw new Error(`${resp.status}: ${body}`);
    }
    return (await resp.json()) as DocumentSummary;
  },
  deleteDocument: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/api/v1/documents/${id}`, {
      method: "DELETE",
    }),
  searchDocuments: (query: string) =>
    request<{ results: Array<Record<string, unknown>> }>(
      "/api/v1/documents/search",
      {
        method: "POST",
        body: JSON.stringify({ query }),
      },
    ),
};

export function eventsSocketUrl(runId: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const token =
    authToken ||
    (typeof localStorage !== "undefined"
      ? localStorage.getItem(TOKEN_KEY)
      : null);
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${proto}://${window.location.host}/api/v1/research/${runId}/events/ws${q}`;
}

export const TERMINAL_STATUSES = ["completed", "failed", "cancelled"];
