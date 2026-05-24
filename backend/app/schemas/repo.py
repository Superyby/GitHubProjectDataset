from datetime import date, datetime
from typing import Any
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    email: EmailStr


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class PasswordLoginRequest(BaseModel):
    account: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class SendEmailCodeRequest(BaseModel):
    email: EmailStr


class EmailCodeLoginRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)


class AuthResult(BaseModel):
    token: str
    user: UserPublic


class RepoRankingItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: str
    html_url: str
    description: str | None
    language: str | None
    topics: list[str] | None
    created_at: datetime | None
    pushed_at: datetime | None
    stars: int
    forks: int
    star_delta_1d: int
    star_delta_7d: int
    star_delta_30d: int
    history_days: int
    growth_rate_7d: Decimal | None
    score: Decimal | None
    rank: int | None
    category: str | None = None
    summary_zh: str | None = None
    trend_summary_zh: str | None = None
    trend_label: str | None = None
    trend_points: list[int] = []


class RepoDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: str
    html_url: str
    description: str | None
    language: str | None
    license: str | None
    topics: list[str] | None
    homepage: str | None
    created_at: datetime | None
    pushed_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime


class JobResult(BaseModel):
    snapshot_date: date
    collection: dict[str, Any]
    scoring: dict[str, Any]
    analysis: dict[str, Any]


class RepoAiAnalysisResult(BaseModel):
    full_name: str
    category: str | None = None
    subcategory: str | None = None
    summary_zh: str | None = None
    summary_en: str | None = None
    trend_summary_zh: str | None = None
    trend_label: str | None = None
    highlights: list[str] = []
    use_cases: list[str] = []
    target_users: list[str] = []
    risk_flags: list[str] = []
    quality_score: Decimal | None = None
    trend_points: list[dict[str, int | str]] = []
