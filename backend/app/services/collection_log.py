from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.collection import GithubCollectionRun


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def start_collection_run(db: Session, run_date: date) -> GithubCollectionRun:
    run = GithubCollectionRun(run_date=run_date, status="running", started_at=_now())
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_collection_run(
    db: Session, run: GithubCollectionRun, collection: dict[str, Any], status: str = "success"
) -> None:
    run = db.merge(run)
    run.status = status
    run.finished_at = _now()
    run.refreshed_existing = int(collection.get("refreshed_existing") or 0)
    run.skipped_existing = int(collection.get("skipped_existing") or 0)
    run.discovered = int(collection.get("discovered") or 0)
    run.created = int(collection.get("created") or 0)
    run.updated = int(collection.get("updated") or 0)
    run.failed = int(collection.get("failed") or 0)
    db.commit()


def fail_collection_run(db: Session, run: GithubCollectionRun, error: BaseException) -> None:
    run = db.merge(run)
    run.status = "failed"
    run.finished_at = _now()
    run.error = f"{type(error).__name__}: {error}"
    db.commit()


def latest_collection_run(db: Session) -> GithubCollectionRun | None:
    return db.scalar(
        select(GithubCollectionRun).order_by(GithubCollectionRun.started_at.desc()).limit(1)
    )


def serialize_collection_run(run: GithubCollectionRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "run_date": run.run_date.isoformat(),
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "refreshed_existing": run.refreshed_existing,
        "skipped_existing": run.skipped_existing,
        "discovered": run.discovered,
        "created": run.created,
        "updated": run.updated,
        "failed": run.failed,
        "error": run.error,
    }
