from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class GithubRepo(Base):
    __tablename__ = "github_repo"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(128))
    full_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    html_url: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(64))
    license: Mapped[str | None] = mapped_column(String(128))
    topics: Mapped[list[str] | None] = mapped_column(JSON)
    homepage: Mapped[str | None] = mapped_column(String(512))
    default_branch: Mapped[str | None] = mapped_column(String(128))
    is_fork: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    snapshots = relationship("GithubRepoDailySnapshot", back_populates="repo")
    scores = relationship("GithubRepoDailyScore", back_populates="repo")
    analysis = relationship("RepoAiAnalysis", back_populates="repo")


Index("idx_github_repo_language", GithubRepo.language)
Index("idx_github_repo_created_at", GithubRepo.created_at)
