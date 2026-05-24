from datetime import datetime, timezone
from typing import Any


_daily_job_status: dict[str, Any] = {
    "status": "idle",
    "snapshot_date": None,
    "started_at": None,
    "finished_at": None,
    "stage": None,
    "error": None,
    "result": None,
}

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_daily_job_status() -> dict[str, Any]:
    return dict(_daily_job_status)


def mark_daily_job_started(snapshot_date) -> None:
    _daily_job_status.update(
        {
            "status": "running",
            "snapshot_date": snapshot_date.isoformat(),
            "started_at": _now(),
            "finished_at": None,
            "stage": "collecting",
            "error": None,
            "result": None,
            "progress": {},
        }
    )


def mark_daily_job_stage(stage: str) -> None:
    _daily_job_status["stage"] = stage


def update_daily_job_progress(**values: Any) -> None:
    progress = dict(_daily_job_status.get("progress") or {})
    progress.update(values)
    _daily_job_status["progress"] = progress


def mark_daily_job_finished(result: dict[str, Any]) -> None:
    _daily_job_status.update(
        {
            "status": "success",
            "finished_at": _now(),
            "stage": "done",
            "error": None,
            "result": result,
        }
    )


def mark_daily_job_skipped(snapshot_date, reason: str, result: dict[str, Any] | None = None) -> None:
    _daily_job_status.update(
        {
            "status": "success",
            "snapshot_date": snapshot_date.isoformat(),
            "started_at": _now(),
            "finished_at": _now(),
            "stage": "done",
            "error": None,
            "result": result or {"skipped": True, "reason": reason},
            "progress": {"skipped": True, "reason": reason},
        }
    )


def mark_daily_job_failed(error: BaseException) -> None:
    _daily_job_status.update(
        {
            "status": "failed",
            "finished_at": _now(),
            "stage": "failed",
            "error": f"{type(error).__name__}: {error}",
        }
    )
