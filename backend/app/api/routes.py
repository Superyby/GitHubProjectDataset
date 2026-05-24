from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.analysis import RepoAiAnalysis
from app.models.repo import GithubRepo
from app.models.score import GithubRepoDailyScore
from app.models.snapshot import GithubRepoDailySnapshot
from app.schemas.repo import JobResult, RepoAiAnalysisResult, RepoDetail, RepoRankingItem
from app.services.ai_analyzer import AiAnalyzer
from app.services.collector import GithubCollector
from app.services.job_status import (
    get_daily_job_status,
    mark_daily_job_failed,
    mark_daily_job_finished,
    mark_daily_job_skipped,
    mark_daily_job_started,
)
from app.services.scoring import ScoreService

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/rankings/{kind}", response_model=list[RepoRankingItem])
def rankings(
    kind: Literal["hot", "rising", "momentum"],
    ranking_date: date | None = Query(default=None, alias="date"),
    category: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[RepoRankingItem]:
    current_date = ranking_date or date.today()
    score_attr = {
        "hot": GithubRepoDailyScore.hot_score,
        "rising": GithubRepoDailyScore.rising_score,
        "momentum": GithubRepoDailyScore.momentum_score,
    }[kind]
    rank_attr = {
        "hot": GithubRepoDailyScore.rank_hot,
        "rising": GithubRepoDailyScore.rank_rising,
        "momentum": GithubRepoDailyScore.rank_momentum,
    }[kind]

    stmt: Select = (
        select(GithubRepo, GithubRepoDailySnapshot, GithubRepoDailyScore, RepoAiAnalysis)
        .join(GithubRepoDailySnapshot, GithubRepoDailySnapshot.repo_id == GithubRepo.id)
        .join(GithubRepoDailyScore, GithubRepoDailyScore.repo_id == GithubRepo.id)
        .outerjoin(RepoAiAnalysis, RepoAiAnalysis.repo_id == GithubRepo.id)
        .where(
            GithubRepoDailySnapshot.snapshot_date == current_date,
            GithubRepoDailyScore.score_date == current_date,
        )
        .order_by(score_attr.desc())
        .limit(limit)
    )
    if category:
        stmt = stmt.where(RepoAiAnalysis.category == category)

    items = []
    for repo, snapshot, score, analysis in db.execute(stmt).all():
        items.append(
            RepoRankingItem(
                full_name=repo.full_name,
                html_url=repo.html_url,
                description=repo.description,
                language=repo.language,
                topics=repo.topics,
                created_at=repo.created_at,
                pushed_at=repo.pushed_at,
                stars=snapshot.stars,
                forks=snapshot.forks,
                star_delta_1d=score.star_delta_1d,
                star_delta_7d=score.star_delta_7d,
                star_delta_30d=score.star_delta_30d,
                history_days=score.history_days,
                growth_rate_7d=score.growth_rate_7d,
                score=getattr(score, score_attr.key) or Decimal("0"),
                rank=getattr(score, rank_attr.key),
                category=analysis.category if analysis else None,
                summary_zh=analysis.summary_zh if analysis else None,
                trend_summary_zh=analysis.trend_summary_zh if analysis else None,
                trend_label=analysis.trend_label if analysis else None,
                trend_points=[],
            )
        )
    return items


@router.get("/repos", response_model=list[RepoRankingItem])
def all_repos(
    list_date: date | None = Query(default=None, alias="date"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    q: str | None = None,
    db: Session = Depends(get_db),
) -> list[RepoRankingItem]:
    current_date = list_date or date.today()
    stmt: Select = (
        select(GithubRepo, GithubRepoDailySnapshot, GithubRepoDailyScore, RepoAiAnalysis)
        .join(GithubRepoDailySnapshot, GithubRepoDailySnapshot.repo_id == GithubRepo.id)
        .outerjoin(
            GithubRepoDailyScore,
            (GithubRepoDailyScore.repo_id == GithubRepo.id)
            & (GithubRepoDailyScore.score_date == current_date),
        )
        .outerjoin(RepoAiAnalysis, RepoAiAnalysis.repo_id == GithubRepo.id)
        .where(GithubRepoDailySnapshot.snapshot_date == current_date)
        .order_by(GithubRepoDailySnapshot.stars.desc())
        .offset(offset)
        .limit(limit)
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            (GithubRepo.full_name.like(pattern))
            | (GithubRepo.description.like(pattern))
            | (GithubRepo.language.like(pattern))
        )

    rows = db.execute(stmt).all()
    trend_map = _trend_points_map(db, [repo.id for repo, *_ in rows], current_date)
    items = []
    for index, (repo, snapshot, score, analysis) in enumerate(rows, start=offset + 1):
        items.append(
            RepoRankingItem(
                full_name=repo.full_name,
                html_url=repo.html_url,
                description=repo.description,
                language=repo.language,
                topics=repo.topics,
                created_at=repo.created_at,
                pushed_at=repo.pushed_at,
                stars=snapshot.stars,
                forks=snapshot.forks,
                star_delta_1d=score.star_delta_1d if score else 0,
                star_delta_7d=score.star_delta_7d if score else 0,
                star_delta_30d=score.star_delta_30d if score else 0,
                history_days=score.history_days if score else 0,
                growth_rate_7d=score.growth_rate_7d if score else None,
                score=score.hot_score if score else Decimal("0"),
                rank=index,
                category=analysis.category if analysis else None,
                summary_zh=analysis.summary_zh if analysis else None,
                trend_summary_zh=analysis.trend_summary_zh if analysis else None,
                trend_label=analysis.trend_label if analysis else None,
                trend_points=trend_map.get(repo.id, []),
            )
        )
    return items


def _trend_points_map(
    db: Session, repo_ids: list[int], current_date: date, days: int = 14
) -> dict[int, list[int]]:
    if not repo_ids:
        return {}
    start_date = current_date - timedelta(days=days - 1)
    rows = db.execute(
        select(GithubRepoDailySnapshot.repo_id, GithubRepoDailySnapshot.stars)
        .where(
            GithubRepoDailySnapshot.repo_id.in_(repo_ids),
            GithubRepoDailySnapshot.snapshot_date >= start_date,
            GithubRepoDailySnapshot.snapshot_date <= current_date,
        )
        .order_by(GithubRepoDailySnapshot.repo_id, GithubRepoDailySnapshot.snapshot_date)
    ).all()
    result: dict[int, list[int]] = {}
    for repo_id, stars in rows:
        result.setdefault(repo_id, []).append(stars)
    return result


@router.get("/summary")
def daily_summary(
    summary_date: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict:
    current_date = summary_date or date.today()

    snapshot_count = db.scalar(
        select(func.count(GithubRepoDailySnapshot.id)).where(
            GithubRepoDailySnapshot.snapshot_date == current_date
        )
    ) or 0
    scored_count = db.scalar(
        select(func.count(GithubRepoDailyScore.id)).where(
            GithubRepoDailyScore.score_date == current_date
        )
    ) or 0
    analyzed_count = db.scalar(select(func.count(RepoAiAnalysis.id))) or 0
    total_repos = db.scalar(select(func.count(GithubRepo.id))) or 0
    total_stars = db.scalar(
        select(func.coalesce(func.sum(GithubRepoDailySnapshot.stars), 0)).where(
            GithubRepoDailySnapshot.snapshot_date == current_date
        )
    ) or 0
    total_star_delta_7d = db.scalar(
        select(func.coalesce(func.sum(GithubRepoDailyScore.star_delta_7d), 0)).where(
            GithubRepoDailyScore.score_date == current_date
        )
    ) or 0

    language_rows = db.execute(
        select(GithubRepo.language, func.count(GithubRepo.id))
        .join(GithubRepoDailySnapshot, GithubRepoDailySnapshot.repo_id == GithubRepo.id)
        .where(
            GithubRepoDailySnapshot.snapshot_date == current_date,
            GithubRepo.language.is_not(None),
        )
        .group_by(GithubRepo.language)
        .order_by(func.count(GithubRepo.id).desc())
        .limit(8)
    ).all()

    category_rows = db.execute(
        select(RepoAiAnalysis.category, func.count(RepoAiAnalysis.id))
        .where(RepoAiAnalysis.category.is_not(None))
        .group_by(RepoAiAnalysis.category)
        .order_by(func.count(RepoAiAnalysis.id).desc())
        .limit(8)
    ).all()

    return {
        "date": current_date.isoformat(),
        "total_repos": total_repos,
        "snapshot_count": snapshot_count,
        "scored_count": scored_count,
        "analyzed_count": analyzed_count,
        "total_stars": int(total_stars),
        "total_star_delta_7d": int(total_star_delta_7d),
        "ai_enabled": get_settings().ai_enabled,
        "languages": [{"name": name, "count": count} for name, count in language_rows],
        "categories": [{"name": name, "count": count} for name, count in category_rows],
        "job": get_daily_job_status(),
    }


@router.get("/repos/{owner}/{name}", response_model=RepoDetail)
def repo_detail(owner: str, name: str, db: Session = Depends(get_db)) -> RepoDetail:
    full_name = f"{owner}/{name}"
    repo = db.scalar(select(GithubRepo).where(GithubRepo.full_name == full_name))
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepoDetail.model_validate(repo)


@router.post("/repos/{owner}/{name}/ai", response_model=RepoAiAnalysisResult)
def analyze_repo(
    owner: str,
    name: str,
    analysis_date: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not settings.ai_enabled:
        raise HTTPException(status_code=403, detail="AI analysis is disabled")
    if not settings.deepseek_api_key:
        raise HTTPException(status_code=403, detail="DeepSeek API key is not configured")
    try:
        return AiAnalyzer(settings).analyze_selected_repo(db, f"{owner}/{name}", analysis_date)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/daily", response_model=JobResult)
def run_daily_job(
    snapshot_date: date | None = None,
    force: bool = False,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobResult:
    current_date = snapshot_date or date.today()
    snapshot_state = _snapshot_state(db, current_date)
    if not force and snapshot_state != "missing":
        return JobResult(
            snapshot_date=current_date,
            collection={"skipped": 1, "reason": snapshot_state},
            scoring={"skipped": 1, "reason": "collection_skipped"},
            analysis={"skipped": 1, "reason": "collection_skipped"},
        )
    collection = GithubCollector(settings).collect_daily(db, current_date)
    scoring = ScoreService().calculate_daily_scores(db, current_date)
    analysis = {"skipped": 1, "reason": "manual_repo_ai_only"}
    return JobResult(snapshot_date=current_date, collection=collection, scoring=scoring, analysis=analysis)


@router.post("/jobs/daily/async")
def run_daily_job_async(
    background_tasks: BackgroundTasks,
    snapshot_date: date | None = None,
    force: bool = False,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    current_status = get_daily_job_status()
    if current_status.get("status") == "running":
        return {
            "status": "already_running",
            "snapshot_date": current_status.get("snapshot_date") or "",
        }

    current_date = snapshot_date or date.today()
    snapshot_state = _snapshot_state(db, current_date)
    if not force and snapshot_state != "missing":
        result = {
            "collection": {"skipped": 1, "reason": snapshot_state},
            "scoring": {"skipped": 1, "reason": "collection_skipped"},
            "analysis": {"skipped": 1, "reason": "collection_skipped"},
        }
        mark_daily_job_skipped(current_date, snapshot_state, result)
        return {"status": "skipped", "snapshot_date": current_date.isoformat()}

    mark_daily_job_started(current_date)
    background_tasks.add_task(_run_daily_background, current_date)
    return {"status": "started", "snapshot_date": current_date.isoformat()}


@router.get("/jobs/daily/status")
def daily_job_status() -> dict:
    return get_daily_job_status()


@router.post("/jobs/score")
def run_score_job(
    score_date: date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    current_date = score_date or date.today()
    return ScoreService().calculate_daily_scores(db, current_date)


def _run_daily_background(snapshot_date: date) -> None:
    from app.jobs.daily import run_daily

    try:
        result = run_daily(snapshot_date)
    except Exception as exc:
        mark_daily_job_failed(exc)
        raise
    mark_daily_job_finished(result)


def _snapshot_state(db: Session, snapshot_date: date) -> str:
    for _ in range(2):
        try:
            count = db.scalar(
                select(func.count(GithubRepoDailySnapshot.id)).where(
                    GithubRepoDailySnapshot.snapshot_date == snapshot_date
                )
            )
            return "snapshots_already_exist" if count else "missing"
        except Exception:
            db.rollback()
            db.close()
    return "snapshot_check_failed"
