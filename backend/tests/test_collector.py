from datetime import date, datetime
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services.collector import GithubCollector


def repo_payload(**overrides):
    payload = {
        "id": 123,
        "node_id": "node-new",
        "full_name": "owner/repo",
        "owner": {"login": "owner"},
        "name": "repo",
        "html_url": "https://github.com/owner/repo",
        "description": "new description",
        "language": "Python",
        "license": {"spdx_id": "MIT"},
        "topics": ["ai"],
        "homepage": "https://example.com",
        "default_branch": "main",
        "fork": False,
        "archived": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-05-25T00:00:00Z",
        "pushed_at": "2026-05-25T00:00:00Z",
        "stargazers_count": 42,
        "forks_count": 3,
        "watchers_count": 42,
        "open_issues_count": 1,
        "size": 100,
    }
    payload.update(overrides)
    return payload


class CollectorTests(TestCase):
    def test_existing_repo_keeps_first_seen_and_created_at_identity(self):
        collector = GithubCollector(SimpleNamespace())
        original_first_seen = datetime(2026, 4, 1)
        original_created_at = datetime(2025, 1, 1)
        repo = SimpleNamespace(
            github_id=123,
            first_seen_at=original_first_seen,
            created_at=original_created_at,
        )

        class FakeDb:
            def scalar(self, _stmt):
                return repo

            def flush(self):
                return None

        saved_repo, was_created = collector._upsert_repo(FakeDb(), repo_payload())

        self.assertFalse(was_created)
        self.assertIs(saved_repo, repo)
        self.assertEqual(repo.first_seen_at, original_first_seen)
        self.assertEqual(repo.created_at, original_created_at)
        self.assertEqual(repo.description, "new description")
        self.assertEqual(repo.pushed_at, datetime(2026, 5, 25))

    def test_collect_daily_uses_only_search_candidates(self):
        settings = SimpleNamespace(github_daily_repo_limit=1)
        collector = GithubCollector(settings)

        class FakeClient:
            def search_repositories(self, query, sort):
                return [repo_payload()]

            def close(self):
                return None

        with (
            patch("app.services.collector.GitHubClient", return_value=FakeClient()),
            patch("app.services.collector.build_default_queries", return_value=[("hot", "q", "stars")]),
            patch.object(
                collector,
                "_upsert_candidates",
                return_value={"created": 1, "updated": 0, "failed": 0},
            ) as upsert_candidates,
        ):
            result = collector.collect_daily(SimpleNamespace(), date(2026, 5, 25))

        self.assertEqual(result["refreshed_existing"], 0)
        self.assertEqual(result["discovered"], 1)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 0)
        upsert_candidates.assert_called_once()
