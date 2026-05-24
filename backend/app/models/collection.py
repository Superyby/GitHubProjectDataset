from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class GithubCollectionRun(Base):
    __tablename__ = "github_collection_run"
    __table_args__ = (Index("idx_collection_run_date", "run_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    refreshed_existing: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_existing: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class GithubRepoDiscovery(Base):
    __tablename__ = "github_repo_discovery"
    __table_args__ = (
        UniqueConstraint("repo_id", "source_key", name="uk_repo_discovery_source"),
        Index("idx_discovery_source", "source_key"),
        Index("idx_discovery_first_seen", "first_seen_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_query: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen_date: Mapped[date] = mapped_column(Date, nullable=False)
    seen_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
