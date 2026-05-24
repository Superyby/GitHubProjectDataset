from app import models  # noqa: F401
from app.db.session import Base, engine
from sqlalchemy import text


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_columns()
    print("Database tables created.")


def ensure_columns() -> None:
    migrations = [
        (
            "github_repo_daily_score",
            "history_days",
            "ALTER TABLE github_repo_daily_score ADD COLUMN history_days INT NOT NULL DEFAULT 0",
        ),
        (
            "github_repo_ai_analysis",
            "trend_summary_zh",
            "ALTER TABLE github_repo_ai_analysis ADD COLUMN trend_summary_zh TEXT NULL",
        ),
        (
            "github_repo_ai_analysis",
            "trend_label",
            "ALTER TABLE github_repo_ai_analysis ADD COLUMN trend_label VARCHAR(64) NULL",
        ),
    ]
    with engine.begin() as conn:
        for table, column, ddl in migrations:
            exists = conn.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = DATABASE()
                      AND table_name = :table
                      AND column_name = :column
                    """
                ),
                {"table": table, "column": column},
            )
            if not exists:
                conn.execute(text(ddl))


if __name__ == "__main__":
    main()
