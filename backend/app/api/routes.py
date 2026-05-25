from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, aliased

from app.core.config import Settings, get_settings
from app.core.dates import shanghai_today
from app.db.session import get_db
from app.models.analysis import RepoAiAnalysis
from app.models.auth import User
from app.models.repo import GithubRepo
from app.models.score import GithubRepoDailyScore
from app.models.snapshot import GithubRepoDailySnapshot
from app.schemas.repo import (
    AuthResult,
    EmailCodeLoginRequest,
    JobResult,
    PasswordLoginRequest,
    RegisterRequest,
    RepoAiAnalysisResult,
    RepoDetail,
    RepoRankingItem,
    SendEmailCodeRequest,
    UserPublic,
)
from app.services.ai_analyzer import AiAnalyzer
from app.services.auth import AuthService, get_current_user
from app.services.collection_log import (
    latest_collection_run_for_date,
    latest_collection_run,
    latest_successful_collection_run,
    serialize_collection_run,
)
from app.services.job_status import (
    get_daily_job_status,
    mark_daily_job_failed,
    mark_daily_job_skipped,
)
from app.services.scoring import ScoreService

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/auth/register", response_model=AuthResult)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthResult:
    service = AuthService(settings)
    user = service.register_user(db, payload.username, str(payload.email), payload.password)
    token = service.create_token(db, user)
    return AuthResult(token=token, user=UserPublic.model_validate(user))


@router.post("/auth/login", response_model=AuthResult)
def login_with_password(
    payload: PasswordLoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthResult:
    user, token = AuthService(settings).login_with_password(db, payload.account, payload.password)
    return AuthResult(token=token, user=UserPublic.model_validate(user))


@router.post("/auth/email-code")
def send_email_code(
    payload: SendEmailCodeRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    AuthService(settings).send_email_code(db, str(payload.email))
    return {"status": "sent"}


@router.post("/auth/email-login", response_model=AuthResult)
def login_with_email_code(
    payload: EmailCodeLoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthResult:
    user, token = AuthService(settings).login_with_email_code(db, str(payload.email), payload.code)
    return AuthResult(token=token, user=UserPublic.model_validate(user))


@router.post("/auth/logout")
def logout(
    authorization: str | None = Header(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    del current_user
    if authorization and authorization.lower().startswith("bearer "):
        AuthService(settings).revoke_token(db, authorization.split(" ", 1)[1].strip())
    return {"status": "ok"}


@router.get("/auth/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(current_user)


@router.get("/rankings/trends", response_model=list[RepoRankingItem])
def trend_rankings(
    days: int = Query(default=7),
    ranking_date: date | None = Query(default=None, alias="date"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RepoRankingItem]:
    del current_user
    current_date = ranking_date or _default_read_date(db)
    if days not in {3, 7, 30}:
        raise HTTPException(status_code=400, detail="days must be one of: 3, 7, 30")
    start_date = current_date - timedelta(days=days)
    current_snapshot = aliased(GithubRepoDailySnapshot)
    previous_snapshot = aliased(GithubRepoDailySnapshot)
    latest_previous = (
        select(
            GithubRepoDailySnapshot.repo_id,
            func.max(GithubRepoDailySnapshot.snapshot_date).label("snapshot_date"),
        )
        .where(GithubRepoDailySnapshot.snapshot_date <= start_date)
        .group_by(GithubRepoDailySnapshot.repo_id)
        .subquery()
    )
    earliest_snapshot = (
        select(
            GithubRepoDailySnapshot.repo_id,
            func.min(GithubRepoDailySnapshot.snapshot_date).label("snapshot_date"),
        )
        .where(GithubRepoDailySnapshot.snapshot_date < current_date)
        .group_by(GithubRepoDailySnapshot.repo_id)
        .subquery()
    )
    baseline = (
        select(
            current_snapshot.repo_id.label("repo_id"),
            func.coalesce(
                latest_previous.c.snapshot_date,
                earliest_snapshot.c.snapshot_date,
            ).label("snapshot_date"),
        )
        .outerjoin(latest_previous, latest_previous.c.repo_id == current_snapshot.repo_id)
        .outerjoin(earliest_snapshot, earliest_snapshot.c.repo_id == current_snapshot.repo_id)
        .where(current_snapshot.snapshot_date == current_date)
        .subquery()
    )
    delta = current_snapshot.stars - previous_snapshot.stars
    stmt: Select = (
        select(
            GithubRepo,
            current_snapshot,
            GithubRepoDailyScore,
            RepoAiAnalysis,
            delta.label("trend_delta"),
        )
        .join(current_snapshot, current_snapshot.repo_id == GithubRepo.id)
        .join(baseline, baseline.c.repo_id == GithubRepo.id)
        .join(
            previous_snapshot,
            (previous_snapshot.repo_id == GithubRepo.id)
            & (previous_snapshot.snapshot_date == baseline.c.snapshot_date),
        )
        .outerjoin(
            GithubRepoDailyScore,
            (GithubRepoDailyScore.repo_id == GithubRepo.id)
            & (GithubRepoDailyScore.score_date == current_date),
        )
        .outerjoin(RepoAiAnalysis, RepoAiAnalysis.repo_id == GithubRepo.id)
        .where(current_snapshot.snapshot_date == current_date)
        .order_by(delta.desc(), current_snapshot.stars.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    trend_map = _trend_points_map(db, [repo.id for repo, *_ in rows], current_date, days + 1)
    items = []
    for rank, (repo, snapshot, score, analysis, trend_delta) in enumerate(rows, start=1):
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
                star_delta_7d=int(trend_delta or 0),
                star_delta_30d=score.star_delta_30d if score else 0,
                history_days=score.history_days if score else 0,
                growth_rate_7d=score.growth_rate_7d if score else None,
                score=Decimal(trend_delta or 0),
                rank=rank,
                category=analysis.category if analysis else None,
                summary_zh=analysis.summary_zh if analysis else None,
                trend_summary_zh=analysis.trend_summary_zh if analysis else None,
                trend_label=analysis.trend_label if analysis else None,
                trend_points=trend_map.get(repo.id, []),
            )
        )
    return items


@router.get("/rankings/{kind}", response_model=list[RepoRankingItem])
def rankings(
    kind: Literal["hot", "rising", "momentum"],
    ranking_date: date | None = Query(default=None, alias="date"),
    category: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RepoRankingItem]:
    del current_user
    current_date = ranking_date or _default_read_date(db)
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
    current_user: User = Depends(get_current_user),
) -> list[RepoRankingItem]:
    del current_user
    current_date = list_date or _default_read_date(db)
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


def _latest_snapshot_date(db: Session) -> date | None:
    return db.scalar(select(func.max(GithubRepoDailySnapshot.snapshot_date)))


def _default_read_date(db: Session) -> date:
    latest_complete_date = _latest_complete_date(db)
    if latest_complete_date is not None:
        return latest_complete_date
    return _latest_snapshot_date(db) or shanghai_today()


def _latest_complete_date(db: Session) -> date | None:
    latest_success = _latest_complete_collection_run(db)
    return latest_success.run_date if latest_success is not None else None


def _latest_complete_collection_run(db: Session):
    for run in latest_successful_collection_run(db):
        snapshot_count = _snapshot_count(db, run.run_date)
        expected_count = run.discovered
        if expected_count == 0 or snapshot_count >= expected_count:
            return run
    return None


def _snapshot_count(db: Session, snapshot_date: date) -> int:
    return db.scalar(
        select(func.count(GithubRepoDailySnapshot.id)).where(
            GithubRepoDailySnapshot.snapshot_date == snapshot_date
        )
    ) or 0


@router.get("/summary")
def daily_summary(
    summary_date: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    del current_user
    current_date = summary_date or _default_read_date(db)
    settings = get_settings()
    latest_snapshot_date = _latest_snapshot_date(db)
    latest_complete_date = _latest_complete_date(db)

    snapshot_count = _snapshot_count(db, current_date)
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
        "ai_enabled": settings.ai_enabled,
        "latest_snapshot_date": latest_snapshot_date.isoformat() if latest_snapshot_date else None,
        "latest_complete_date": latest_complete_date.isoformat() if latest_complete_date else None,
        "github_daily_repo_limit": settings.github_daily_repo_limit,
        "languages": [{"name": name, "count": count} for name, count in language_rows],
        "categories": [{"name": name, "count": count} for name, count in category_rows],
        "job": get_daily_job_status(),
        "latest_collection": serialize_collection_run(latest_collection_run(db)),
    }


@router.get("/repos/{owner}/{name}", response_model=RepoDetail)
def repo_detail(
    owner: str,
    name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RepoDetail:
    del current_user
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
    current_user: User = Depends(get_current_user),
) -> dict:
    del current_user
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
    current_user: User = Depends(get_current_user),
) -> JobResult:
    del current_user
    current_date = snapshot_date or shanghai_today()
    snapshot_state = _snapshot_state(db, current_date)
    if not force and snapshot_state in {"snapshots_already_exist", "snapshot_check_failed"}:
        return JobResult(
            snapshot_date=current_date,
            collection={"skipped": 1, "reason": snapshot_state},
            scoring={"skipped": 1, "reason": "collection_skipped"},
            analysis={"skipped": 1, "reason": "collection_skipped"},
        )
    result = run_daily(current_date)
    return JobResult(snapshot_date=current_date, **result)


@router.post("/jobs/daily/async")
def run_daily_job_async(
    background_tasks: BackgroundTasks,
    snapshot_date: date | None = None,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    del current_user
    current_status = get_daily_job_status()
    if current_status.get("status") == "running":
        return {
            "status": "already_running",
            "snapshot_date": current_status.get("snapshot_date") or "",
        }

    current_date = snapshot_date or shanghai_today()
    snapshot_state = _snapshot_state(db, current_date)
    if not force and snapshot_state in {"snapshots_already_exist", "snapshot_check_failed"}:
        result = {
            "collection": {"skipped": 1, "reason": snapshot_state},
            "scoring": {"skipped": 1, "reason": "collection_skipped"},
            "analysis": {"skipped": 1, "reason": "collection_skipped"},
        }
        mark_daily_job_skipped(current_date, snapshot_state, result)
        return {"status": "skipped", "snapshot_date": current_date.isoformat()}

    background_tasks.add_task(_run_daily_background, current_date)
    return {"status": "started", "snapshot_date": current_date.isoformat()}


@router.get("/jobs/daily/status")
def daily_job_status(current_user: User = Depends(get_current_user)) -> dict:
    del current_user
    return get_daily_job_status()


@router.post("/jobs/score")
def run_score_job(
    score_date: date | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    del current_user
    current_date = score_date or shanghai_today()
    return ScoreService().calculate_daily_scores(db, current_date)


def _run_daily_background(snapshot_date: date) -> None:
    from app.jobs.daily import run_daily

    try:
        run_daily(snapshot_date)
    except Exception as exc:
        mark_daily_job_failed(exc)
        raise


def _snapshot_state(db: Session, snapshot_date: date) -> str:
    for _ in range(2):
        try:
            count = _snapshot_count(db, snapshot_date)
            if not count:
                return "missing"
            latest_run = latest_collection_run_for_date(db, snapshot_date)
            if latest_run is None or latest_run.status != "success":
                return "partial_snapshots_exist"
            expected_count = latest_run.discovered
            if expected_count > 0 and count < expected_count:
                return "partial_snapshots_exist"
            return "snapshots_already_exist"
        except Exception:
            db.rollback()
            db.close()
    return "snapshot_check_failed"
