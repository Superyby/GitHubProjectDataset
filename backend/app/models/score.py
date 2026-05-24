from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, DECIMAL, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class GithubRepoDailyScore(Base):
    __tablename__ = "github_repo_daily_score"
    __table_args__ = (
        UniqueConstraint("repo_id", "score_date", name="uk_repo_score_date"),
        Index("idx_score_date_hot", "score_date", "hot_score"),
        Index("idx_score_date_rising", "score_date", "rising_score"),
        Index("idx_score_date_momentum", "score_date", "momentum_score"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("github_repo.id"), nullable=False)
    score_date: Mapped[date] = mapped_column(Date, nullable=False)
    star_delta_1d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    star_delta_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    star_delta_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    history_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    growth_rate_1d: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 6))
    growth_rate_7d: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 6))
    hot_score: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 6))
    rising_score: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 6))
    momentum_score: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 6))
    rank_hot: Mapped[int | None] = mapped_column(Integer)
    rank_rising: Mapped[int | None] = mapped_column(Integer)
    rank_momentum: Mapped[int | None] = mapped_column(Integer)
    created_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    repo = relationship("GithubRepo", back_populates="scores")
