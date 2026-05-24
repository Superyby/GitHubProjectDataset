import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.analysis import RepoAiAnalysis
from app.models.repo import GithubRepo
from app.models.score import GithubRepoDailyScore
from app.models.snapshot import GithubRepoDailySnapshot


class AiAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze_selected_repo(
        self, db: Session, full_name: str, analysis_date: date | None = None
    ) -> dict:
        if not self.settings.ai_enabled or not self.settings.deepseek_api_key:
            return {"skipped": 1, "reason": "ai_disabled"}

        current_date = analysis_date or date.today()
        repo = db.scalar(select(GithubRepo).where(GithubRepo.full_name == full_name))
        if repo is None:
            raise LookupError("Repository not found")

        score = db.scalar(
            select(GithubRepoDailyScore).where(
                GithubRepoDailyScore.repo_id == repo.id,
                GithubRepoDailyScore.score_date == current_date,
            )
        )
        if score is None:
            raise ValueError("Repository has no score for the selected date")

        trend_points = self._recent_star_trend(db, repo.id, current_date)
        result = self._analyze_repo(repo, score, trend_points)
        self._save_analysis(db, repo.id, result)
        return {
            "full_name": repo.full_name,
            "trend_points": trend_points,
            **result,
        }

    def _recent_star_trend(
        self, db: Session, repo_id: int, current_date: date, days: int = 14
    ) -> list[dict[str, int | str]]:
        start_date = current_date - timedelta(days=days - 1)
        rows = db.execute(
            select(GithubRepoDailySnapshot.snapshot_date, GithubRepoDailySnapshot.stars)
            .where(
                GithubRepoDailySnapshot.repo_id == repo_id,
                GithubRepoDailySnapshot.snapshot_date >= start_date,
                GithubRepoDailySnapshot.snapshot_date <= current_date,
            )
            .order_by(GithubRepoDailySnapshot.snapshot_date)
        ).all()
        return [{"date": row_date.isoformat(), "stars": stars} for row_date, stars in rows]

    def _analyze_repo(
        self,
        repo: GithubRepo,
        score: GithubRepoDailyScore,
        trend_points: list[dict[str, int | str]],
    ) -> dict:
        has_trend = score.history_days > 0 and len(trend_points) >= 2
        prompt = {
            "repo": {
                "full_name": repo.full_name,
                "description": repo.description,
                "language": repo.language,
                "topics": repo.topics,
                "homepage": repo.homepage,
                "created_at": repo.created_at.isoformat() if repo.created_at else None,
                "first_seen_at": repo.first_seen_at.isoformat() if repo.first_seen_at else None,
            },
            "growth": {
                "has_trend": has_trend,
                "history_days": score.history_days,
                "star_delta_1d": score.star_delta_1d,
                "star_delta_7d": score.star_delta_7d,
                "star_delta_30d": score.star_delta_30d,
                "growth_rate_1d": str(score.growth_rate_1d or 0),
                "growth_rate_7d": str(score.growth_rate_7d or 0),
                "hot_score": str(score.hot_score or 0),
                "rising_score": str(score.rising_score or 0),
                "momentum_score": str(score.momentum_score or 0),
                "recent_star_points": trend_points,
                "recent_star_values": [point["stars"] for point in trend_points],
            },
            "instruction": (
                "Analyze only this selected repository's recent star trend. "
                "Use recent_star_points and recent_star_values as the primary evidence. "
                "If has_trend is false or recent_star_points has fewer than 2 points, say there "
                "is no reliable growth trend yet. Do not invent trend conclusions."
            ),
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an open-source project and growth-trend analyst. "
                    "Return only JSON with these fields: category, subcategory, summary_zh, "
                    "summary_en, trend_summary_zh, trend_label, highlights, use_cases, "
                    "target_users, risk_flags, quality_score. "
                    "trend_label should be one of: first_seen, stable, rising, accelerating, cooling, unknown."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        with httpx.Client(base_url=self.settings.deepseek_base_url, timeout=60) as client:
            response = client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
                json={
                    "model": self.settings.deepseek_model,
                    "messages": messages,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    def _save_analysis(self, db: Session, repo_id: int, result: dict) -> None:
        payload = {
            "repo_id": repo_id,
            "model": self.settings.deepseek_model,
            "category": result.get("category"),
            "subcategory": result.get("subcategory"),
            "summary_zh": result.get("summary_zh"),
            "summary_en": result.get("summary_en"),
            "trend_summary_zh": result.get("trend_summary_zh"),
            "trend_label": result.get("trend_label"),
            "highlights": result.get("highlights") or [],
            "use_cases": result.get("use_cases") or [],
            "target_users": result.get("target_users") or [],
            "risk_flags": result.get("risk_flags") or [],
            "quality_score": Decimal(str(result.get("quality_score", 0))),
            "analyzed_at": datetime.now(timezone.utc).replace(tzinfo=None),
        }
        insert_stmt = postgres_insert(RepoAiAnalysis).values(**payload)
        update_payload = {
            key: insert_stmt.excluded[key] for key in payload if key not in {"repo_id", "model"}
        }
        last_error: OperationalError | None = None
        for _ in range(3):
            try:
                db.execute(
                    insert_stmt.on_conflict_do_update(
                        index_elements=["repo_id", "model"],
                        set_=update_payload,
                    )
                )
                db.commit()
                return
            except OperationalError as exc:
                last_error = exc
                db.rollback()
                db.close()
        raise last_error
