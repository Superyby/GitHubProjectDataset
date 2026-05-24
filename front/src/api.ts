export type RankingKind = "hot" | "rising" | "momentum";
export type ListKind = RankingKind | "all";

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

export async function fetchRanking(kind: RankingKind, date?: string): Promise<RepoRankingItem[]> {
  const params = new URLSearchParams({ limit: "50" });
  if (date) {
    params.set("date", date);
  }

  const response = await fetch(`${API_BASE_URL}/api/rankings/${kind}?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch ranking: ${response.status}`);
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

  const response = await fetch(`${API_BASE_URL}/api/repos?${params.toString()}`);
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
  const response = await fetch(`${API_BASE_URL}/api/summary${suffix}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch summary: ${response.status}`);
  }
  return response.json();
}

export async function runScoreJob(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/jobs/score`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Failed to calculate scores: ${response.status}`);
  }
}

export async function analyzeRepo(fullName: string): Promise<RepoAiAnalysisResult> {
  const [owner, name] = fullName.split("/");
  const response = await fetch(
    `${API_BASE_URL}/api/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/ai`,
    { method: "POST" }
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Failed to analyze repo: ${response.status}`);
  }
  return response.json();
}
