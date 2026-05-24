from app import models  # noqa: F401
from app.db.session import Base, engine
from sqlalchemy import inspect, text


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
    inspector = inspect(engine)
    existing_columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table, _, _ in migrations
        if inspector.has_table(table)
    }
    with engine.begin() as conn:
        for table, column, ddl in migrations:
            if column not in existing_columns.get(table, set()):
                conn.execute(text(ddl))


if __name__ == "__main__":
    main()
