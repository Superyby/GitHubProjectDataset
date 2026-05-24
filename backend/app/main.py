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
        scheduler.add_job(run_daily, "cron", hour=8, minute=0, id="daily_github_radar_morning")
        scheduler.add_job(run_daily, "cron", hour=20, minute=0, id="daily_github_radar_evening")
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
