from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.collection import GithubRepoDiscovery
from app.models.repo import GithubRepo
from app.models.score import GithubRepoDailyScore
from app.models.snapshot import GithubRepoDailySnapshot
from app.services.github_client import GitHubClient, build_default_queries
from app.services.job_status import update_daily_job_progress
from app.services.repo_mapper import map_repo_payload, map_snapshot_payload


class GithubCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def collect_daily(self, db: Session, snapshot_date: date | None = None) -> dict[str, int]:
        current_date = snapshot_date or date.today()
        client = GitHubClient(self.settings)
        seen: set[int] = set()
        refreshed_existing = 0
        skipped_existing = 0
        discovered = 0
        created = 0
        updated = 0
        failed = 0

        try:
            for repo_id, github_id, full_name in self._existing_repositories(db, current_date):
                if refreshed_existing >= self.settings.github_daily_refresh_limit:
                    skipped_existing += 1
                    continue
                try:
                    payload = client.get_repository(full_name)
                except Exception:
                    failed += 1
                    continue

                seen.add(github_id)
                repo_id, was_created = self._upsert_and_commit_with_retry(db, payload, current_date)
                refreshed_existing += 1
                updated += int(not was_created)
                update_daily_job_progress(
                    stage_detail="refresh_existing",
                    refreshed_existing=refreshed_existing,
                    skipped_existing=skipped_existing,
                    discovered=discovered,
                    created=created,
                    updated=updated,
                    failed=failed,
                    collected=refreshed_existing + discovered,
                    repo=full_name,
                )

            for source_key, query, sort in build_default_queries(current_date):
                try:
                    search_results = client.search_repositories(query=query, sort=sort)
                except Exception:
                    failed += 1
                    update_daily_job_progress(
                        stage_detail="discover_hot",
                        refreshed_existing=refreshed_existing,
                        skipped_existing=skipped_existing,
                        discovered=discovered,
                        created=created,
                        updated=updated,
                        failed=failed,
                        collected=refreshed_existing + discovered,
                        query=query,
                        query_failed=True,
                    )
                    continue

                for payload in search_results:
                    if discovered >= self.settings.github_daily_repo_limit:
                        update_daily_job_progress(
                            stage_detail="discover_hot",
                            refreshed_existing=refreshed_existing,
                            skipped_existing=skipped_existing,
                            discovered=discovered,
                            created=created,
                            updated=updated,
                            failed=failed,
                            collected=refreshed_existing + discovered,
                            query=query,
                            limited=True,
                        )
                        return {
                            "refreshed_existing": refreshed_existing,
                            "skipped_existing": skipped_existing,
                            "discovered": discovered,
                            "created": created,
                            "updated": updated,
                            "failed": failed,
                        }

                    github_id = payload["id"]
                    if github_id in seen:
                        existing_repo_id = db.scalar(
                            select(GithubRepo.id).where(GithubRepo.github_id == github_id)
                        )
                        if existing_repo_id is not None:
                            try:
                                self._record_discovery(
                                    db, existing_repo_id, source_key, query, current_date
                                )
                            except Exception:
                                db.rollback()
                                failed += 1
                        continue
                    seen.add(github_id)

                    try:
                        repo_id, was_created = self._upsert_and_commit_with_retry(
                            db, payload, current_date
                        )
                        self._record_discovery(db, repo_id, source_key, query, current_date)
                    except Exception:
                        db.rollback()
                        failed += 1
                        continue

                    discovered += 1
                    created += int(was_created)
                    updated += int(not was_created)
                    update_daily_job_progress(
                        stage_detail="discover_hot",
                        refreshed_existing=refreshed_existing,
                        skipped_existing=skipped_existing,
                        discovered=discovered,
                        collected=refreshed_existing + discovered,
                        created=created,
                        updated=updated,
                        failed=failed,
                        query=query,
                    )
        finally:
            client.close()

        return {
            "refreshed_existing": refreshed_existing,
            "skipped_existing": skipped_existing,
            "discovered": discovered,
            "created": created,
            "updated": updated,
            "failed": failed,
        }

    def _existing_repositories(
        self, db: Session, current_date: date
    ) -> list[tuple[int, int, str]]:
        seven_days_ago = current_date - timedelta(days=7)
        snapshot_count = (
            select(func.count(GithubRepoDailySnapshot.id))
            .where(GithubRepoDailySnapshot.repo_id == GithubRepo.id)
            .correlate(GithubRepo)
            .scalar_subquery()
        )
        latest_snapshot = (
            select(func.max(GithubRepoDailySnapshot.snapshot_date))
            .where(GithubRepoDailySnapshot.repo_id == GithubRepo.id)
            .correlate(GithubRepo)
            .scalar_subquery()
        )
        recent_delta = (
            select(func.coalesce(func.max(GithubRepoDailyScore.star_delta_7d), 0))
            .where(
                GithubRepoDailyScore.repo_id == GithubRepo.id,
                GithubRepoDailyScore.score_date >= seven_days_ago,
            )
            .correlate(GithubRepo)
            .scalar_subquery()
        )
        priority = case(
            (snapshot_count == 0, 0),
            (latest_snapshot < current_date - timedelta(days=1), 1),
            (recent_delta > 0, 2),
            (GithubRepo.pushed_at >= datetime.combine(seven_days_ago, datetime.min.time()), 3),
            else_=4,
        )
        rows = db.execute(
            select(GithubRepo.id, GithubRepo.github_id, GithubRepo.full_name)
            .where(GithubRepo.is_archived.is_(False))
            .order_by(priority, GithubRepo.last_seen_at.desc(), GithubRepo.id)
            .limit(self.settings.github_daily_refresh_limit)
        ).all()
        return [(repo_id, github_id, full_name) for repo_id, github_id, full_name in rows]

    def _upsert_and_commit_with_retry(
        self, db: Session, payload: dict, snapshot_date: date, retries: int = 2
    ) -> tuple[int, bool]:
        last_error: OperationalError | None = None
        for _ in range(retries + 1):
            try:
                repo, was_created = self._upsert_repo(db, payload)
                self._upsert_snapshot(db, repo, payload, snapshot_date)
                repo_id = repo.id
                db.commit()
                return repo_id, was_created
            except OperationalError as exc:
                last_error = exc
                db.rollback()
        raise last_error

    def _upsert_repo(self, db: Session, payload: dict, /) -> tuple[GithubRepo, bool]:
        mapped = map_repo_payload(payload)
        repo = db.scalar(select(GithubRepo).where(GithubRepo.github_id == mapped["github_id"]))
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        if repo is None:
            repo = GithubRepo(**mapped, first_seen_at=now)
            db.add(repo)
            db.flush()
            return repo, True

        for key, value in mapped.items():
            setattr(repo, key, value)
        db.flush()
        return repo, False

    def _upsert_snapshot(
        self, db: Session, repo: GithubRepo, payload: dict, snapshot_date: date
    ) -> GithubRepoDailySnapshot:
        mapped = map_snapshot_payload(payload)
        snapshot = db.scalar(
            select(GithubRepoDailySnapshot).where(
                GithubRepoDailySnapshot.repo_id == repo.id,
                GithubRepoDailySnapshot.snapshot_date == snapshot_date,
            )
        )
        if snapshot is None:
            snapshot = GithubRepoDailySnapshot(repo_id=repo.id, snapshot_date=snapshot_date, **mapped)
            db.add(snapshot)
        else:
            for key, value in mapped.items():
                setattr(snapshot, key, value)
        db.flush()
        return snapshot

    def _record_discovery(
        self, db: Session, repo_id: int, source_key: str, source_query: str, seen_date: date
    ) -> None:
        payload = {
            "repo_id": repo_id,
            "source_key": source_key,
            "source_query": source_query,
            "first_seen_date": seen_date,
            "last_seen_date": seen_date,
            "seen_count": 1,
        }
        insert_stmt = postgres_insert(GithubRepoDiscovery).values(**payload)
        db.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=["repo_id", "source_key"],
                set_={
                    "source_query": insert_stmt.excluded.source_query,
                    "last_seen_date": insert_stmt.excluded.last_seen_date,
                    "seen_count": GithubRepoDiscovery.seen_count + 1,
                },
            )
        )
        db.commit()
