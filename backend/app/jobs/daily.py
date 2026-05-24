from datetime import date

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.collector import GithubCollector
from app.services.job_status import mark_daily_job_stage
from app.services.scoring import ScoreService


def run_daily(snapshot_date: date | None = None) -> dict[str, dict[str, int]]:
    settings = get_settings()
    current_date = snapshot_date or date.today()
    with SessionLocal() as db:
        mark_daily_job_stage("collecting")
        collection = GithubCollector(settings).collect_daily(db, current_date)
        mark_daily_job_stage("scoring")
        scoring = ScoreService().calculate_daily_scores(db, current_date)
        mark_daily_job_stage("done")
        analysis = {"skipped": 1, "reason": "manual_repo_ai_only"}
    return {"collection": collection, "scoring": scoring, "analysis": analysis}
