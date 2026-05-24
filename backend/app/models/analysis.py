from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, DECIMAL, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class RepoAiAnalysis(Base):
    __tablename__ = "github_repo_ai_analysis"
    __table_args__ = (UniqueConstraint("repo_id", "model", name="uk_repo_analysis_model"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("github_repo.id"), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    subcategory: Mapped[str | None] = mapped_column(String(128))
    summary_zh: Mapped[str | None] = mapped_column(Text)
    summary_en: Mapped[str | None] = mapped_column(Text)
    trend_summary_zh: Mapped[str | None] = mapped_column(Text)
    trend_label: Mapped[str | None] = mapped_column(String(64))
    highlights: Mapped[list[str] | None] = mapped_column(JSON)
    use_cases: Mapped[list[str] | None] = mapped_column(JSON)
    target_users: Mapped[list[str] | None] = mapped_column(JSON)
    risk_flags: Mapped[list[str] | None] = mapped_column(JSON)
    quality_score: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2))
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    repo = relationship("GithubRepo", back_populates="analysis")
