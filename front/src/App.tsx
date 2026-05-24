import { BarChart3, Bot, Flame, Github, Languages, Moon, Rocket, Search, Star, Sun, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  analyzeRepo,
  DailyJobStatus,
  DailySummary,
  fetchAllRepos,
  fetchRanking,
  fetchSummary,
  ListKind,
  RankingKind,
  RepoAiAnalysisResult,
  RepoRankingItem,
  runScoreJob
} from "./api";

type Locale = "zh" | "en";
type Theme = "light" | "dark";

const text = {
  zh: {
    title: "\u6bcf\u65e5\u5f00\u6e90\u9879\u76ee\u96f7\u8fbe",
    score: "\u8ba1\u7b97\u8bc4\u5206",
    aiAnalyze: "AI \u5206\u6790",
    aiAnalyzingRepo: "AI \u5206\u6790\u4e2d",
    aiDisabled: "AI \u672a\u542f\u7528",
    aiRepoDone: "AI \u5206\u6790\u5b8c\u6210\u3002",
    aiRepoFailed: "AI \u5206\u6790\u5931\u8d25\u3002",
    aiTrend: "AI \u8d8b\u52bf",
    highlights: "\u4eae\u70b9",
    risks: "\u98ce\u9669",
    lightMode: "\u4eae\u8272",
    darkMode: "\u6697\u8272",
    hot: "\u70ed\u95e8",
    rising: "\u65b0\u661f",
    momentum: "\u52a0\u901f",
    all: "\u5168\u90e8",
    search: "\u641c\u7d22\u9879\u76ee\u3001\u8bed\u8a00\u3001\u4e3b\u9898\u3001\u8d8b\u52bf",
    loading: "\u6b63\u5728\u52a0\u8f7d\u699c\u5355...",
    noRanking: "\u6682\u65e0\u699c\u5355\u3002\u5982\u679c\u5df2\u6709\u5feb\u7167\uff0c\u8bf7\u5148\u8ba1\u7b97\u8bc4\u5206\u3002",
    snapshots: "\u4eca\u65e5\u5feb\u7167",
    scored: "\u5df2\u8bc4\u5206",
    totalStars: "\u603b Stars",
    languages: "\u8bed\u8a00\u5206\u5e03",
    categories: "AI \u5206\u7c7b",
    none: "\u6682\u65e0",
    status: "\u72b6\u6001",
    refreshed: "\u5df2\u5237\u65b0",
    existing: "\u4e2a\u5df2\u5165\u5e93",
    discovered: "\u65b0\u53d1\u73b0",
    hotRepos: "\u4e2a\u70ed\u95e8\u9879\u76ee",
    firstSeen: "\u9996\u6b21\u5165\u5e93",
    trendPending: "\u8d8b\u52bf\u5f85\u5206\u6790",
    noDescription: "\u6682\u65e0\u63cf\u8ff0",
    delta7d: "7 \u65e5\u589e\u957f",
    scoreMetric: "\u8bc4\u5206",
    trend: "\u8d8b\u52bf",
    scoring: "\u6b63\u5728\u8ba1\u7b97\u589e\u957f\u8bc4\u5206...",
    scoredDone: "\u8bc4\u5206\u8ba1\u7b97\u5b8c\u6210\u3002",
    idle: "\u7a7a\u95f2",
    collectingRepos: "\u6b63\u5728\u91c7\u96c6 GitHub \u9879\u76ee",
    scoringRepos: "\u6b63\u5728\u8ba1\u7b97\u589e\u957f\u8bc4\u5206",
    analyzingRepos: "\u6b63\u5728 AI \u5206\u6790",
    done: "\u5b8c\u6210",
    failed: "\u5931\u8d25"
  },
  en: {
    title: "Daily Open Source Radar",
    score: "Score",
    aiAnalyze: "AI Analyze",
    aiAnalyzingRepo: "AI analyzing",
    aiDisabled: "AI disabled",
    aiRepoDone: "AI analysis finished.",
    aiRepoFailed: "AI analysis failed.",
    aiTrend: "AI Trend",
    highlights: "Highlights",
    risks: "Risks",
    lightMode: "Light",
    darkMode: "Dark",
    hot: "Hot",
    rising: "Rising",
    momentum: "Momentum",
    all: "All",
    search: "Search repo, language, topic, trend",
    loading: "Loading rankings...",
    noRanking: "No ranking yet. If snapshots exist, run Score first.",
    snapshots: "Today Snapshots",
    scored: "Scored",
    totalStars: "Total Stars",
    languages: "Languages",
    categories: "AI Categories",
    none: "None",
    status: "Status",
    refreshed: "refreshed",
    existing: "existing",
    discovered: "discovered",
    hotRepos: "hot repos",
    firstSeen: "first seen",
    trendPending: "trend pending",
    noDescription: "No description",
    delta7d: "7d Delta",
    scoreMetric: "Score",
    trend: "Trend",
    scoring: "Calculating growth scores...",
    scoredDone: "Scores calculated.",
    idle: "Idle",
    collectingRepos: "Collecting GitHub repos",
    scoringRepos: "Calculating growth scores",
    analyzingRepos: "AI analyzing",
    done: "Done",
    failed: "Failed"
  }
} satisfies Record<Locale, Record<string, string>>;

export function App() {
  const [locale, setLocale] = useState<Locale>("zh");
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = window.localStorage.getItem("theme");
    return saved === "dark" ? "dark" : "light";
  });
  const t = text[locale];
  const tabs: Array<{ kind: ListKind; label: string; icon: ReactNode }> = [
    { kind: "hot", label: t.hot, icon: <Flame size={16} /> },
    { kind: "rising", label: t.rising, icon: <Rocket size={16} /> },
    { kind: "momentum", label: t.momentum, icon: <TrendingUp size={16} /> },
    { kind: "all", label: t.all, icon: <Github size={16} /> }
  ];

  const [activeKind, setActiveKind] = useState<ListKind>("hot");
  const [items, setItems] = useState<RepoRankingItem[]>([]);
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [analyzingRepo, setAnalyzingRepo] = useState<string | null>(null);
  const [analysisByRepo, setAnalysisByRepo] = useState<Record<string, RepoAiAnalysisResult>>({});
  const [jobStatus, setJobStatus] = useState<DailyJobStatus | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("theme", theme);
  }, [theme]);

  async function refreshData(kind = activeKind, searchQuery = query) {
    const listPromise = kind === "all" ? fetchAllRepos(searchQuery) : fetchRanking(kind);
    const [rankingData, summaryData] = await Promise.all([listPromise, fetchSummary()]);
    setItems(rankingData);
    setSummary(summaryData);
    setJobStatus(summaryData.job);
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNotice(null);

    refreshData(activeKind)
      .catch((err: Error) => {
        if (!cancelled) {
          setNotice(err.message);
          setItems([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeKind]);

  useEffect(() => {
    if (activeKind !== "all") {
      return;
    }
    const timer = window.setTimeout(() => {
      refreshData("all", query).catch((err: Error) => setNotice(err.message));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, activeKind]);

  const filteredItems = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) {
      return items;
    }
    return items.filter((item) => {
      const haystack = [
        item.full_name,
        item.description || "",
        item.language || "",
        item.category || "",
        item.trend_label || "",
        ...(item.topics || [])
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(keyword);
    });
  }, [items, query]);

  async function handleScore() {
    setNotice(t.scoring);
    await runScoreJob();
    await refreshData();
    setNotice(t.scoredDone);
  }

  async function handleAnalyzeRepo(fullName: string) {
    if (!summary?.ai_enabled) {
      setNotice(t.aiDisabled);
      return;
    }
    setAnalyzingRepo(fullName);
    setNotice(null);
    try {
      const result = await analyzeRepo(fullName);
      setAnalysisByRepo((current) => ({ ...current, [fullName]: result }));
      setItems((current) =>
        current.map((item) =>
          item.full_name === fullName
            ? {
                ...item,
                category: result.category,
                summary_zh: result.summary_zh,
                trend_summary_zh: result.trend_summary_zh,
                trend_label: result.trend_label
              }
            : item
        )
      );
      setNotice(t.aiRepoDone);
      await fetchSummary().then(setSummary).catch(() => undefined);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : t.aiRepoFailed);
    } finally {
      setAnalyzingRepo(null);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">GitHub Project Radar</p>
          <h1>{t.title}</h1>
        </div>
        <div className="actions">
          <button
            className="ghost-button icon-button"
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            aria-label={theme === "light" ? t.darkMode : t.lightMode}
            title={theme === "light" ? t.darkMode : t.lightMode}
          >
            {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
            {theme === "light" ? t.darkMode : t.lightMode}
          </button>
          <button className="ghost-button" onClick={() => setLocale(locale === "zh" ? "en" : "zh")}>
            <Languages size={16} />
            {locale === "zh" ? "EN" : "\u4e2d\u6587"}
          </button>
          <button className="ghost-button" onClick={handleScore}>
            <BarChart3 size={16} />
            {t.score}
          </button>
        </div>
      </header>

      <SummaryPanel summary={summary} jobStatus={jobStatus} t={t} />

      <section className="toolbar" aria-label="Ranking filters">
        <div className="tabs">
          {tabs.map((tab) => (
            <button
              key={tab.kind}
              className={tab.kind === activeKind ? "tab active" : "tab"}
              onClick={() => setActiveKind(tab.kind)}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>
        <label className="search">
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t.search}
          />
        </label>
      </section>

      {notice && <div className="notice">{notice}</div>}
      {loading && <div className="notice">{t.loading}</div>}

      <section className="repo-list">
        {filteredItems.map((item) => (
          <RepoRow
            key={item.full_name}
            item={item}
            t={t}
            analysis={analysisByRepo[item.full_name]}
            analyzing={analyzingRepo === item.full_name}
            aiEnabled={summary?.ai_enabled ?? false}
            onAnalyze={() => handleAnalyzeRepo(item.full_name)}
          />
        ))}
        {!loading && filteredItems.length === 0 && (
          <div className="empty">
            <Github size={28} />
            <p>{t.noRanking}</p>
          </div>
        )}
      </section>
    </main>
  );
}

function SummaryPanel({
  summary,
  jobStatus,
  t
}: {
  summary: DailySummary | null;
  jobStatus: DailyJobStatus | null;
  t: Record<string, string>;
}) {
  const job = jobStatus || summary?.job;
  return (
    <section className="summary-grid">
      <Stat icon={<Github size={18} />} label={t.snapshots} value={formatNumber(summary?.snapshot_count ?? 0)} />
      <Stat icon={<BarChart3 size={18} />} label={t.scored} value={formatNumber(summary?.scored_count ?? 0)} />
      <Stat icon={<Star size={18} />} label={t.totalStars} value={formatNumber(summary?.total_stars ?? 0)} />
      <div className="summary-wide">
        <strong>{stageLabel(job?.stage || null, t)}</strong>
        <span>
          {job?.status || "idle"} - {t.refreshed} {job?.progress?.refreshed_existing ?? 0},{" "}
          {t.discovered} {job?.progress?.discovered ?? 0} / 1000
        </span>
      </div>
      <Distribution title={t.languages} items={summary?.languages ?? []} noneText={t.none} />
      <Distribution title={t.categories} items={summary?.categories ?? []} noneText={t.none} />
    </section>
  );
}

function Stat({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="stat">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Distribution({
  title,
  items,
  noneText
}: {
  title: string;
  items: Array<{ name: string; count: number }>;
  noneText: string;
}) {
  return (
    <div className="distribution">
      <strong>{title}</strong>
      <div className="chips">
        {items.length === 0 && <span>{noneText}</span>}
        {items.map((item) => (
          <span key={item.name}>
            {item.name} {item.count}
          </span>
        ))}
      </div>
    </div>
  );
}

function RepoRow({
  item,
  t,
  analysis,
  analyzing,
  aiEnabled,
  onAnalyze
}: {
  item: RepoRankingItem;
  t: Record<string, string>;
  analysis?: RepoAiAnalysisResult;
  analyzing: boolean;
  aiEnabled: boolean;
  onAnalyze: () => void;
}) {
  const summary = analysis?.trend_summary_zh || item.trend_summary_zh || item.summary_zh;
  const highlights = analysis?.highlights ?? [];
  const risks = analysis?.risk_flags ?? [];
  return (
    <article className="repo-row">
      <div className="rank">#{item.rank ?? "-"}</div>
      <div className="repo-main">
        <div className="repo-title">
          <a href={item.html_url} target="_blank" rel="noreferrer">
            {item.full_name}
          </a>
          <span className="category">{trendLabel(item, t)}</span>
          {item.category && <span className="category muted">{item.category}</span>}
        </div>
        <p className="description">
          {summary || item.description || t.noDescription}
        </p>
        <div className="meta">
          {item.language && <span>{item.language}</span>}
          {(item.topics || []).slice(0, 4).map((topic) => (
            <span key={topic}>{topic}</span>
          ))}
        </div>
        {analysis && (
          <div className="analysis-panel">
            <div className="analysis-head">
              <strong>{t.aiTrend}</strong>
              <span>{analysis.trend_label || trendLabel(item, t)}</span>
              {analysis.quality_score && <span>{Number(analysis.quality_score).toFixed(1)}</span>}
            </div>
            {analysis.trend_summary_zh && <p>{analysis.trend_summary_zh}</p>}
            <AnalysisList title={t.highlights} items={highlights} />
            <AnalysisList title={t.risks} items={risks} />
          </div>
        )}
      </div>
      <div className="metrics">
        <Metric label="Stars" value={formatNumber(item.stars)} />
        <Metric label={t.delta7d} value={item.history_days > 0 ? `+${formatNumber(item.star_delta_7d)}` : "N/A"} highlight />
        <Metric label={t.scoreMetric} value={Number(item.score || 0).toFixed(2)} />
        <div className="spark-cell" aria-label={t.trend}>
          <Sparkline points={item.trend_points} />
        </div>
        <button className="ai-row-button" onClick={onAnalyze} disabled={analyzing || !aiEnabled}>
          <Bot size={15} />
          {!aiEnabled ? t.aiDisabled : analyzing ? t.aiAnalyzingRepo : t.aiAnalyze}
        </button>
      </div>
    </article>
  );
}

function AnalysisList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="analysis-list">
      <span>{title}</span>
      {items.slice(0, 3).map((item) => (
        <em key={item}>{item}</em>
      ))}
    </div>
  );
}

function Sparkline({ points }: { points: number[] }) {
  const width = 104;
  const height = 38;
  const pad = 4;
  if (!points || points.length < 2) {
    return (
      <svg className="sparkline neutral" viewBox={`0 0 ${width} ${height}`} role="img">
        <line x1={pad} y1={height / 2} x2={width - pad} y2={height / 2} />
      </svg>
    );
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = Math.max(max - min, 1);
  const d = points
    .map((value, index) => {
      const x = pad + (index / (points.length - 1)) * (width - pad * 2);
      const y = height - pad - ((value - min) / range) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const direction = points[points.length - 1] >= points[0] ? "up" : "down";
  return (
    <svg className={`sparkline ${direction}`} viewBox={`0 0 ${width} ${height}`} role="img">
      <polyline points={d} />
    </svg>
  );
}

function Metric({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className={highlight ? "metric highlight" : "metric"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function trendLabel(item: RepoRankingItem, t: Record<string, string>) {
  if (item.history_days === 0) {
    return t.firstSeen;
  }
  return item.trend_label || t.trendPending;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("zh-CN", { notation: value > 9999 ? "compact" : "standard" }).format(value);
}

function stageLabel(stage: string | null, t: Record<string, string>) {
  const labels: Record<string, string> = {
    collecting: t.collectingRepos,
    scoring: t.scoringRepos,
    analyzing: t.analyzingRepos,
    done: t.done,
    failed: t.failed
  };
  return labels[stage || ""] || t.idle;
}
