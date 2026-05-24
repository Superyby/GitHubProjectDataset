from datetime import datetime, timezone
from typing import Any


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def map_repo_payload(payload: dict[str, Any]) -> dict[str, Any]:
    license_payload = payload.get("license") or {}
    owner = payload.get("owner") or {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    return {
        "github_id": payload["id"],
        "node_id": payload.get("node_id"),
        "full_name": payload["full_name"],
        "owner": owner.get("login") or payload["full_name"].split("/")[0],
        "name": payload["name"],
        "html_url": payload["html_url"],
        "description": payload.get("description"),
        "language": payload.get("language"),
        "license": license_payload.get("spdx_id") or license_payload.get("key"),
        "topics": payload.get("topics") or [],
        "homepage": payload.get("homepage"),
        "default_branch": payload.get("default_branch"),
        "is_fork": bool(payload.get("fork")),
        "is_archived": bool(payload.get("archived")),
        "created_at": parse_github_datetime(payload.get("created_at")),
        "updated_at": parse_github_datetime(payload.get("updated_at")),
        "pushed_at": parse_github_datetime(payload.get("pushed_at")),
        "last_seen_at": now,
    }


def map_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "stars": int(payload.get("stargazers_count") or 0),
        "forks": int(payload.get("forks_count") or 0),
        "watchers": int(payload.get("watchers_count") or 0),
        "open_issues": int(payload.get("open_issues_count") or 0),
        "size_kb": int(payload.get("size") or 0),
        "pushed_at": parse_github_datetime(payload.get("pushed_at")),
    }
