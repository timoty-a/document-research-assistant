"""Application entry point. Liveness deliberately does not query PostgreSQL."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.db import create_db_engine
from app.documents.router import router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            await run_in_threadpool(app.state.engine.dispose)

    app = FastAPI(title="Document Research Assistant", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = create_db_engine(settings)
    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
