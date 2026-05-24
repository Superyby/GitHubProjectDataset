from datetime import date, timedelta
from typing import Any

import httpx

from app.core.config import Settings


class GitHubClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-project-dataset",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        self.client = httpx.Client(base_url="https://api.github.com", headers=headers, timeout=30)

    def search_repositories(self, query: str, sort: str = "stars") -> list[dict[str, Any]]:
        repos: list[dict[str, Any]] = []
        for page in range(1, self.settings.github_max_pages_per_query + 1):
            response = self.client.get(
                "/search/repositories",
                params={
                    "q": query,
                    "sort": sort,
                    "order": "desc",
                    "per_page": self.settings.github_per_page,
                    "page": page,
                },
            )
            response.raise_for_status()
            items = response.json().get("items", [])
            if not items:
                break
            repos.extend(items)
        return repos

    def get_repository(self, full_name: str) -> dict[str, Any]:
        response = self.client.get(f"/repos/{full_name}")
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.client.close()


def build_default_queries(today: date) -> list[tuple[str, str]]:
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    quarter_ago = today - timedelta(days=90)

    base_queries = [
        (f"stars:>100 pushed:>={week_ago.isoformat()} fork:false archived:false", "stars"),
        (f"created:>={month_ago.isoformat()} stars:>20 fork:false archived:false", "stars"),
        (f"created:>={quarter_ago.isoformat()} stars:>50 fork:false archived:false", "stars"),
    ]

    topic_queries = []
    topics = [
        "ai",
        "llm",
        "agent",
        "machine-learning",
        "developer-tools",
        "database",
        "security",
        "devops",
        "kubernetes",
        "frontend",
        "rust",
        "golang",
        "typescript",
    ]
    for topic in topics:
        topic_queries.append(
            (f"topic:{topic} stars:>30 pushed:>={month_ago.isoformat()} fork:false archived:false", "stars")
        )

    language_queries = []
    for language in ["Python", "TypeScript", "Go", "Rust", "Java", "C++"]:
        language_queries.append(
            (
                f"language:{language} stars:>100 pushed:>={month_ago.isoformat()} fork:false archived:false",
                "stars",
            )
        )

    return base_queries + topic_queries + language_queries
