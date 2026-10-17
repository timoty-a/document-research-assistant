"""Application entry point. Liveness deliberately does not query PostgreSQL."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.auth.security import dummy_hash
from app.auth import service as auth_service
from app.auth.middleware import AuthBoundary, error_response
from app.auth.router import router as auth_router
from app.config import Settings
from app.db import create_db_engine
from app.documents.router import router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await run_in_threadpool(dummy_hash)
            yield
        finally:
            await run_in_threadpool(app.state.engine.dispose)

    app = FastAPI(title="Document Research Assistant", lifespan=lifespan)
    app.state.clock = auth_service.utcnow
    app.add_middleware(AuthBoundary)
    app.include_router(auth_router)

    @app.exception_handler(auth_service.AuthError)
    async def auth_error(request, error):
        return error_response(error)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        # Keep missing-file status/shape, never echo a supplied credential/body.
        safe = [
            {"loc": e["loc"], "type": e["type"],
             "msg": "Field required" if e["type"] == "missing" else "Invalid input"}
            for e in error.errors()
        ]
        return JSONResponse({"detail": safe}, status_code=422)

    app.state.settings = settings
    app.state.engine = create_db_engine(settings)
    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
