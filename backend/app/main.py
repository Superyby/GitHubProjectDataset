from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.jobs.daily import run_daily


def create_inner_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(router)

    if settings.scheduler_enabled:
        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            run_daily,
            "cron",
            hour=settings.scheduler_hour,
            minute=settings.scheduler_minute,
            id="daily_github_radar",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 30,
        )
        scheduler.start()

        @app.on_event("shutdown")
        def shutdown_scheduler() -> None:
            scheduler.shutdown(wait=False)

    return app


def create_app():
    settings = get_settings()
    inner_app = create_inner_app()
    return CORSMiddleware(
        inner_app,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


app = create_app()
