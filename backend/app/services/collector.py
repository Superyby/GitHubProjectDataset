from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.repo import GithubRepo
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
        discovered = 0
        created = 0
        updated = 0

        try:
            for repo_id, github_id, full_name in self._existing_repositories(db):
                try:
                    payload = client.get_repository(full_name)
                except Exception:
                    continue

                seen.add(github_id)
                was_created = self._upsert_and_commit_with_retry(db, payload, current_date)
                refreshed_existing += 1
                updated += int(not was_created)
                update_daily_job_progress(
                    stage_detail="refresh_existing",
                    refreshed_existing=refreshed_existing,
                    discovered=discovered,
                    created=created,
                    updated=updated,
                    collected=refreshed_existing + discovered,
                    repo=full_name,
                )

            for query, sort in build_default_queries(current_date):
                for payload in client.search_repositories(query=query, sort=sort):
                    if discovered >= self.settings.github_daily_repo_limit:
                        update_daily_job_progress(
                            stage_detail="discover_hot",
                            refreshed_existing=refreshed_existing,
                            discovered=discovered,
                            created=created,
                            updated=updated,
                            collected=refreshed_existing + discovered,
                            query=query,
                            limited=True,
                        )
                        return {
                            "refreshed_existing": refreshed_existing,
                            "discovered": discovered,
                            "created": created,
                            "updated": updated,
                        }

                    github_id = payload["id"]
                    if github_id in seen:
                        continue
                    seen.add(github_id)

                    was_created = self._upsert_and_commit_with_retry(db, payload, current_date)

                    discovered += 1
                    created += int(was_created)
                    updated += int(not was_created)
                    update_daily_job_progress(
                        stage_detail="discover_hot",
                        refreshed_existing=refreshed_existing,
                        discovered=discovered,
                        collected=refreshed_existing + discovered,
                        created=created,
                        updated=updated,
                        query=query,
                    )
        finally:
            client.close()

        return {
            "refreshed_existing": refreshed_existing,
            "discovered": discovered,
            "created": created,
            "updated": updated,
        }

    def _existing_repositories(self, db: Session) -> list[tuple[int, int, str]]:
        rows = db.execute(
            select(GithubRepo.id, GithubRepo.github_id, GithubRepo.full_name).order_by(GithubRepo.id)
        ).all()
        db.close()
        return [(repo_id, github_id, full_name) for repo_id, github_id, full_name in rows]

    def _upsert_and_commit_with_retry(
        self, db: Session, payload: dict, snapshot_date: date, retries: int = 2
    ) -> bool:
        last_error: OperationalError | None = None
        for _ in range(retries + 1):
            try:
                repo, was_created = self._upsert_repo(db, payload)
                self._upsert_snapshot(db, repo, payload, snapshot_date)
                db.commit()
                db.close()
                return was_created
            except OperationalError as exc:
                last_error = exc
                db.rollback()
                db.close()
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
