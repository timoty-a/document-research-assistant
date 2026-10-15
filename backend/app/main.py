"""Application entry point. Liveness deliberately does not query PostgreSQL."""

from fastapi import FastAPI

from app.config import Settings


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(title="Document Research Assistant")
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
