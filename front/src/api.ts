export type RankingKind = "hot" | "rising" | "momentum";
export type TrendDays = 3 | 7 | 30;
export type ListKind = RankingKind | "topn" | "all";

export type RepoRankingItem = {
  full_name: string;
  html_url: string;
  description: string | null;
  language: string | null;
  topics: string[] | null;
  created_at: string | null;
  pushed_at: string | null;
  stars: number;
  forks: number;
  star_delta_1d: number;
  star_delta_7d: number;
  star_delta_30d: number;
  history_days: number;
  growth_rate_7d: string | null;
  score: string | null;
  rank: number | null;
  category: string | null;
  summary_zh: string | null;
  trend_summary_zh: string | null;
  trend_label: string | null;
  trend_points: number[];
};

export type DailyJobStatus = {
  status: "idle" | "running" | "success" | "failed";
  snapshot_date: string | null;
  started_at: string | null;
  finished_at: string | null;
  stage: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
  progress: {
    collected?: number;
    refreshed_existing?: number;
    discovered?: number;
    created?: number;
    updated?: number;
    query?: string;
    repo?: string;
    stage_detail?: string;
    limited?: boolean;
  } | null;
};

export type SummaryItem = {
  name: string;
  count: number;
};

export type DailySummary = {
  date: string;
  total_repos: number;
  snapshot_count: number;
  scored_count: number;
  analyzed_count: number;
  total_stars: number;
  total_star_delta_7d: number;
  ai_enabled: boolean;
  languages: SummaryItem[];
  categories: SummaryItem[];
  job: DailyJobStatus;
};

export type RepoAiAnalysisResult = {
  full_name: string;
  category: string | null;
  subcategory: string | null;
  summary_zh: string | null;
  summary_en: string | null;
  trend_summary_zh: string | null;
  trend_label: string | null;
  highlights: string[];
  use_cases: string[];
  target_users: string[];
  risk_flags: string[];
  quality_score: string | null;
  trend_points: Array<{ date: string; stars: number }>;
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";
const TOKEN_KEY = "github_radar_token";

export type AuthUser = {
  username: string;
  email: string;
};

export type AuthResult = {
  token: string;
  user: AuthUser;
};

export function getStoredToken() {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

async function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  const token = getStoredToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (response.status === 401) {
    clearStoredToken();
    window.dispatchEvent(new Event("auth:expired"));
  }
  return response;
}

async function parseError(response: Response, fallback: string) {
  const body = await response.json().catch(() => null);
  return new Error(body?.detail || fallback);
}

export async function register(username: string, email: string, password: string): Promise<AuthResult> {
  const response = await apiFetch("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, email, password })
  });
  if (!response.ok) {
    throw await parseError(response, `Failed to register: ${response.status}`);
  }
  return response.json();
}

export async function loginWithPassword(account: string, password: string): Promise<AuthResult> {
  const response = await apiFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ account, password })
  });
  if (!response.ok) {
    throw await parseError(response, `Failed to login: ${response.status}`);
  }
  return response.json();
}

export async function sendEmailCode(email: string): Promise<void> {
  const response = await apiFetch("/api/auth/email-code", {
    method: "POST",
    body: JSON.stringify({ email })
  });
  if (!response.ok) {
    throw await parseError(response, `Failed to send email code: ${response.status}`);
  }
}

export async function loginWithEmailCode(email: string, code: string): Promise<AuthResult> {
  const response = await apiFetch("/api/auth/email-login", {
    method: "POST",
    body: JSON.stringify({ email, code })
  });
  if (!response.ok) {
    throw await parseError(response, `Failed to login: ${response.status}`);
  }
  return response.json();
}

export async function fetchMe(): Promise<AuthUser> {
  const response = await apiFetch("/api/auth/me");
  if (!response.ok) {
    throw await parseError(response, `Failed to fetch user: ${response.status}`);
  }
  return response.json();
}

export async function logout(): Promise<void> {
  await apiFetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
  clearStoredToken();
}

export async function fetchRanking(kind: RankingKind, date?: string): Promise<RepoRankingItem[]> {
  const params = new URLSearchParams({ limit: "50" });
  if (date) {
    params.set("date", date);
  }

  const response = await apiFetch(`/api/rankings/${kind}?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch ranking: ${response.status}`);
  }
  return response.json();
}

export async function fetchTrendRanking(days: TrendDays, date?: string): Promise<RepoRankingItem[]> {
  const params = new URLSearchParams({ limit: "50", days: String(days) });
  if (date) {
    params.set("date", date);
  }
  const response = await apiFetch(`/api/rankings/trends?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch trend ranking: ${response.status}`);
  }
  return response.json();
}

export async function fetchAllRepos(query?: string, date?: string): Promise<RepoRankingItem[]> {
  const params = new URLSearchParams({ limit: "200" });
  if (date) {
    params.set("date", date);
  }
  if (query?.trim()) {
    params.set("q", query.trim());
  }

  const response = await apiFetch(`/api/repos?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch all repos: ${response.status}`);
  }
  return response.json();
}

export async function fetchSummary(date?: string): Promise<DailySummary> {
  const params = new URLSearchParams();
  if (date) {
    params.set("date", date);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await apiFetch(`/api/summary${suffix}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch summary: ${response.status}`);
  }
  return response.json();
}

export async function runScoreJob(): Promise<void> {
  const response = await apiFetch("/api/jobs/score", { method: "POST" });
  if (!response.ok) {
    throw new Error(`Failed to calculate scores: ${response.status}`);
  }
}

export async function analyzeRepo(fullName: string): Promise<RepoAiAnalysisResult> {
  const [owner, name] = fullName.split("/");
  const response = await apiFetch(
    `/api/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/ai`,
    { method: "POST" }
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Failed to analyze repo: ${response.status}`);
  }
  return response.json();
}
