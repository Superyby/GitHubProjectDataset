import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.orm import Session, aliased

from app.core.dates import shanghai_today
from app.models.repo import GithubRepo
from app.models.score import GithubRepoDailyScore
from app.models.snapshot import GithubRepoDailySnapshot


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


class ScoreService:
    def calculate_daily_scores(self, db: Session, score_date: date | None = None) -> dict[str, int]:
        current_date = score_date or shanghai_today()
        try:
            current_rows = db.execute(
                select(
                    GithubRepoDailySnapshot.repo_id,
                    GithubRepoDailySnapshot.stars,
                    GithubRepo.first_seen_at,
                    GithubRepo.created_at,
                    GithubRepo.pushed_at,
                )
                .join(GithubRepo, GithubRepo.id == GithubRepoDailySnapshot.repo_id)
                .where(GithubRepoDailySnapshot.snapshot_date == current_date)
            ).all()

            repo_ids = [row.repo_id for row in current_rows]
            stars_1d = self._previous_stars_map(db, repo_ids, current_date, 1)
            stars_7d = self._previous_stars_map(db, repo_ids, current_date, 7)
            stars_30d = self._previous_stars_map(db, repo_ids, current_date, 30)

            payloads = [
                self._build_score_payload(
                    repo_id=row.repo_id,
                    stars=row.stars,
                    previous_1d=stars_1d.get(row.repo_id),
                    previous_7d=stars_7d.get(row.repo_id),
                    previous_30d=stars_30d.get(row.repo_id),
                    first_seen_at=row.first_seen_at,
                    created_at=row.created_at,
                    pushed_at=row.pushed_at,
                    current_date=current_date,
                )
                for row in current_rows
            ]

            for chunk in self._chunks(payloads, 200):
                self._upsert_scores(db, chunk)

            self._assign_ranks(db, current_date)
            return {"scored": len(payloads)}
        except Exception:
            db.rollback()
            raise

    def _previous_stars_map(
        self, db: Session, repo_ids: list[int], current_date: date, days: int
    ) -> dict[int, int]:
        if not repo_ids:
            return {}

        cutoff = current_date - timedelta(days=days)
        latest = (
            select(
                GithubRepoDailySnapshot.repo_id,
                func.max(GithubRepoDailySnapshot.snapshot_date).label("snapshot_date"),
            )
            .where(
                GithubRepoDailySnapshot.repo_id.in_(repo_ids),
                GithubRepoDailySnapshot.snapshot_date <= cutoff,
            )
            .group_by(GithubRepoDailySnapshot.repo_id)
            .subquery()
        )
        snap = aliased(GithubRepoDailySnapshot)
        rows = db.execute(
            select(snap.repo_id, snap.stars).join(
                latest,
                (snap.repo_id == latest.c.repo_id)
                & (snap.snapshot_date == latest.c.snapshot_date),
            )
        ).all()
        return {repo_id: stars for repo_id, stars in rows}

    def _build_score_payload(
        self,
        repo_id: int,
        stars: int,
        previous_1d: int | None,
        previous_7d: int | None,
        previous_30d: int | None,
        first_seen_at: datetime | None,
        created_at: datetime | None,
        pushed_at: datetime | None,
        current_date: date,
    ) -> dict[str, Any]:
        history_days = (
            max((current_date - first_seen_at.date()).days, 0) if first_seen_at else 0
        )
        star_1d = max(stars - previous_1d, 0) if previous_1d is not None else 0
        star_7d = max(stars - previous_7d, 0) if previous_7d is not None else 0
        star_30d = max(stars - previous_30d, 0) if previous_30d is not None else 0

        age_days = max((current_date - created_at.date()).days, 1) if created_at else 365
        growth_1d = star_1d / max(stars - star_1d, 50)
        growth_7d = star_7d / max(stars - star_7d, 50)
        freshness = max(0.0, 1.0 - age_days / 180)
        activity = self._activity_score(pushed_at, current_date)
        normalized_delta = star_7d / math.sqrt(stars + 100)

        hot_score = (
            0.35 * math.log10(stars + 1)
            + 0.30 * math.log10(star_7d + 1)
            + 0.15 * growth_7d
            + 0.10 * activity
            + 0.10 * normalized_delta
        )
        rising_score = (
            0.45 * math.log10(star_7d + 1)
            + 0.25 * growth_7d
            + 0.15 * freshness
            + 0.15 * normalized_delta
        )
        momentum_score = (
            0.40 * math.log10(star_1d + 1)
            + 0.30 * math.log10(star_7d + 1)
            + 0.20 * growth_7d
            + 0.10 * freshness
        )

        return {
            "repo_id": repo_id,
            "score_date": current_date,
            "star_delta_1d": star_1d,
            "star_delta_7d": star_7d,
            "star_delta_30d": star_30d,
            "history_days": history_days,
            "growth_rate_1d": _decimal(growth_1d),
            "growth_rate_7d": _decimal(growth_7d),
            "hot_score": _decimal(hot_score),
            "rising_score": _decimal(rising_score),
            "momentum_score": _decimal(momentum_score),
        }

    def _upsert_scores(self, db: Session, payloads: list[dict[str, Any]]) -> None:
        if not payloads:
            return
        insert_stmt = postgres_insert(GithubRepoDailyScore).values(payloads)
        update_payload = {
            key: insert_stmt.excluded[key]
            for key in payloads[0]
            if key not in {"repo_id", "score_date"}
        }
        db.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=["repo_id", "score_date"],
                set_=update_payload,
            )
        )
        db.commit()

    def _activity_score(self, pushed_at: datetime | None, current_date: date) -> float:
        if pushed_at is None:
            return 0.0
        days_since_push = max((current_date - pushed_at.date()).days, 0)
        return max(0.0, 1.0 - days_since_push / 30)

    def _assign_ranks(self, db: Session, score_date: date) -> None:
        rank_fields = [
            ("hot_score", "rank_hot"),
            ("rising_score", "rank_rising"),
            ("momentum_score", "rank_momentum"),
        ]
        for score_field, rank_field in rank_fields:
            rows = db.execute(
                select(GithubRepoDailyScore.id)
                .where(GithubRepoDailyScore.score_date == score_date)
                .order_by(getattr(GithubRepoDailyScore, score_field).desc())
            ).all()
            rank_map = {score_id: rank for rank, (score_id,) in enumerate(rows, start=1)}
            for chunk_items in self._chunks(list(rank_map.items()), 300):
                ids = [score_id for score_id, _ in chunk_items]
                db.execute(
                    update(GithubRepoDailyScore)
                    .where(GithubRepoDailyScore.id.in_(ids))
                    .values({rank_field: case(dict(chunk_items), value=GithubRepoDailyScore.id)})
                )
                db.commit()

    def _chunks(self, items: list, size: int):
        for index in range(0, len(items), size):
            yield items[index : index + size]
