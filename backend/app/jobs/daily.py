from datetime import date
from threading import Lock

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.collection_log import fail_collection_run, finish_collection_run, start_collection_run
from app.services.collector import GithubCollector
from app.services.db_lock import acquire_daily_collection_lock, release_daily_collection_lock
from app.services.job_status import (
    mark_daily_job_failed,
    mark_daily_job_finished,
    mark_daily_job_skipped,
    mark_daily_job_stage,
    mark_daily_job_started,
)
from app.services.scoring import ScoreService

_daily_run_lock = Lock()


def run_daily(snapshot_date: date | None = None) -> dict[str, dict[str, int]]:
    if not _daily_run_lock.acquire(blocking=False):
        current_date = snapshot_date or date.today()
        result = {"skipped": 1, "reason": "daily_job_already_running"}
        mark_daily_job_skipped(current_date, "daily_job_already_running", result)
        return {"collection": result, "scoring": {"skipped": 1}, "analysis": {"skipped": 1}}

    settings = get_settings()
    current_date = snapshot_date or date.today()
    try:
        mark_daily_job_started(current_date)
        with SessionLocal() as db:
            if not acquire_daily_collection_lock(db):
                result = {"skipped": 1, "reason": "daily_job_database_lock_busy"}
                mark_daily_job_skipped(current_date, "daily_job_database_lock_busy", result)
                return {"collection": result, "scoring": {"skipped": 1}, "analysis": {"skipped": 1}}
            run = start_collection_run(db, current_date)
            try:
                mark_daily_job_stage("collecting")
                collection = GithubCollector(settings).collect_daily(db, current_date)
                finish_collection_run(db, run, collection)
                mark_daily_job_stage("scoring")
                scoring = ScoreService().calculate_daily_scores(db, current_date)
                mark_daily_job_stage("done")
                analysis = {"skipped": 1, "reason": "manual_repo_ai_only"}
            except Exception as exc:
                fail_collection_run(db, run, exc)
                mark_daily_job_failed(exc)
                raise
            finally:
                try:
                    release_daily_collection_lock(db)
                except Exception:
                    db.rollback()
        result = {"collection": collection, "scoring": scoring, "analysis": analysis}
        mark_daily_job_finished(result)
        return result
    finally:
        _daily_run_lock.release()
