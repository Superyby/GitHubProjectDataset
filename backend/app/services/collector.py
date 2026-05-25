from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.dates import shanghai_today
from app.models.collection import GithubRepoDiscovery
from app.models.repo import GithubRepo
from app.models.snapshot import GithubRepoDailySnapshot
from app.services.github_client import GitHubClient, build_default_queries
from app.services.job_status import update_daily_job_progress
from app.services.repo_mapper import map_repo_payload, map_snapshot_payload


EXISTING_REPO_UPDATE_FIELDS = {
    "node_id",
    "full_name",
    "owner",
    "name",
    "html_url",
    "description",
    "language",
    "license",
    "topics",
    "homepage",
    "default_branch",
    "is_fork",
    "is_archived",
    "updated_at",
    "pushed_at",
    "last_seen_at",
}


class GithubCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def collect_daily(self, db: Session, snapshot_date: date | None = None) -> dict[str, int]:
        current_date = snapshot_date or shanghai_today()
        client = GitHubClient(self.settings)
        candidates: dict[int, dict] = {}
        discovery_sources: dict[tuple[int, str], tuple[str, str]] = {}
        refreshed_existing = 0
        skipped_existing = 0
        discovered = 0
        failed = 0
        successful_queries = 0
        failed_queries = 0
        last_error: str | None = None
        limited = False

        try:
            for source_key, query, sort in build_default_queries(current_date):
                if discovered >= self.settings.github_daily_repo_limit:
                    limited = True
                    break
                try:
                    search_results = client.search_repositories(query=query, sort=sort)
                    successful_queries += 1
                except Exception as exc:
                    failed += 1
                    failed_queries += 1
                    last_error = f"query {source_key}: {type(exc).__name__}: {exc}"
                    update_daily_job_progress(
                        stage_detail="discover_hot",
                        refreshed_existing=refreshed_existing,
                        skipped_existing=skipped_existing,
                        discovered=discovered,
                        created=0,
                        updated=0,
                        failed=failed,
                        collected=discovered,
                        query=query,
                        query_failed=True,
                        last_error=last_error,
                    )
                    continue

                for payload in search_results:
                    if discovered >= self.settings.github_daily_repo_limit:
                        limited = True
                        break

                    github_id = payload["id"]
                    if github_id not in candidates:
                        candidates[github_id] = payload
                        discovered += 1
                    discovery_sources[(github_id, source_key)] = (source_key, query)

                    if discovered % 50 == 0:
                        update_daily_job_progress(
                            stage_detail="discover_hot",
                            refreshed_existing=refreshed_existing,
                            skipped_existing=skipped_existing,
                            discovered=discovered,
                            collected=discovered,
                            created=0,
                            updated=0,
                            failed=failed,
                            query=query,
                            limited=limited,
                            last_error=last_error,
                        )
                if limited:
                    break
        finally:
            client.close()

        update_daily_job_progress(
            stage_detail="upsert_candidates",
            refreshed_existing=refreshed_existing,
            skipped_existing=skipped_existing,
            discovered=discovered,
            collected=discovered,
            created=0,
            updated=0,
            failed=failed,
            limited=limited,
            last_error=last_error,
        )

        upsert_result = self._upsert_candidates(
            db,
            list(candidates.values()),
            discovery_sources,
            current_date,
        )
        if upsert_result.get("error"):
            last_error = upsert_result["error"]

        failed += upsert_result["failed"]
        created = upsert_result["created"]
        updated = upsert_result["updated"]
        update_daily_job_progress(
            stage_detail="done_collecting",
            refreshed_existing=refreshed_existing,
            skipped_existing=skipped_existing,
            discovered=discovered,
            collected=discovered,
            created=created,
            updated=updated,
            failed=failed,
            limited=limited,
            last_error=last_error,
        )

        return {
            "refreshed_existing": refreshed_existing,
            "skipped_existing": skipped_existing,
            "discovered": discovered,
            "created": created,
            "updated": updated,
            "failed": failed,
            "successful_queries": successful_queries,
            "failed_queries": failed_queries,
            "error": last_error,
        }

    def _upsert_candidates(
        self,
        db: Session,
        payloads: list[dict],
        discovery_sources: dict[tuple[int, str], tuple[str, str]],
        snapshot_date: date,
        chunk_size: int = 100,
    ) -> dict[str, int | str | None]:
        created = 0
        updated = 0
        failed = 0
        processed = 0
        last_error: str | None = None

        for chunk in self._chunks(payloads, chunk_size):
            try:
                repo_ids, chunk_created, chunk_updated = self._upsert_repo_batch(db, chunk)
                self._upsert_snapshot_batch(db, repo_ids, chunk, snapshot_date)
                self._record_discovery_batch(db, repo_ids, discovery_sources, snapshot_date)
                db.commit()
                created += chunk_created
                updated += chunk_updated
                processed += len(chunk)
                update_daily_job_progress(
                    stage_detail="upsert_candidates",
                    discovered=len(payloads),
                    collected=processed,
                    created=created,
                    updated=updated,
                    failed=failed,
                )
            except Exception as exc:
                db.rollback()
                failed += len(chunk)
                last_error = f"batch chunk: {type(exc).__name__}: {exc}"
        return {"created": created, "updated": updated, "failed": failed, "error": last_error}

    def _upsert_repo_batch(
        self, db: Session, payloads: list[dict]
    ) -> tuple[dict[int, int], int, int]:
        mapped_by_github_id = {}
        for payload in payloads:
            mapped = map_repo_payload(payload)
            mapped_by_github_id[mapped["github_id"]] = mapped
        github_ids = list(mapped_by_github_id)
        existing_repos = db.execute(
            select(GithubRepo).where(GithubRepo.github_id.in_(github_ids))
        ).scalars()
        existing_by_github_id = {repo.github_id: repo for repo in existing_repos}

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        repo_ids: dict[int, int] = {}
        repo_objects: dict[int, GithubRepo] = {}
        created = 0
        updated = 0

        for github_id, mapped in mapped_by_github_id.items():
            repo = existing_by_github_id.get(github_id)
            if repo is None:
                repo = GithubRepo(**mapped, first_seen_at=now)
                db.add(repo)
                created += 1
            else:
                for key in EXISTING_REPO_UPDATE_FIELDS:
                    setattr(repo, key, mapped[key])
                updated += 1
            repo_objects[github_id] = repo

        db.flush()
        for github_id, repo in repo_objects.items():
            repo_ids[github_id] = repo.id
        return repo_ids, created, updated

    def _upsert_snapshot_batch(
        self, db: Session, repo_ids: dict[int, int], payloads: list[dict], snapshot_date: date
    ) -> None:
        values = []
        for payload in payloads:
            github_id = payload["id"]
            repo_id = repo_ids.get(github_id)
            if repo_id is None:
                continue
            values.append(
                {
                    "repo_id": repo_id,
                    "snapshot_date": snapshot_date,
                    **map_snapshot_payload(payload),
                }
            )
        if not values:
            return
        insert_stmt = postgres_insert(GithubRepoDailySnapshot).values(values)
        update_payload = {
            key: insert_stmt.excluded[key]
            for key in values[0]
            if key not in {"repo_id", "snapshot_date"}
        }
        db.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=["repo_id", "snapshot_date"],
                set_=update_payload,
            )
        )

    def _record_discovery_batch(
        self,
        db: Session,
        repo_ids: dict[int, int],
        discovery_sources: dict[tuple[int, str], tuple[str, str]],
        seen_date: date,
    ) -> None:
        values = []
        for (github_id, source_key), (_, source_query) in discovery_sources.items():
            repo_id = repo_ids.get(github_id)
            if repo_id is None:
                continue
            values.append(
                {
                    "repo_id": repo_id,
                    "source_key": source_key,
                    "source_query": source_query,
                    "first_seen_date": seen_date,
                    "last_seen_date": seen_date,
                    "seen_count": 1,
                }
            )
        if not values:
            return
        insert_stmt = postgres_insert(GithubRepoDiscovery).values(values)
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

        for key in EXISTING_REPO_UPDATE_FIELDS:
            value = mapped[key]
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

    def _chunks(self, items: list, size: int):
        for index in range(0, len(items), size):
            yield items[index : index + size]
