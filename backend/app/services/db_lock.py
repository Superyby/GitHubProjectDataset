from sqlalchemy import text
from sqlalchemy.orm import Session


DAILY_COLLECTION_LOCK_ID = 2026052401


def acquire_daily_collection_lock(db: Session) -> bool:
    return bool(
        db.scalar(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": DAILY_COLLECTION_LOCK_ID},
        )
    )


def release_daily_collection_lock(db: Session) -> None:
    db.rollback()
    db.execute(
        text("SELECT pg_advisory_unlock(:lock_id)"),
        {"lock_id": DAILY_COLLECTION_LOCK_ID},
    )
    db.commit()
