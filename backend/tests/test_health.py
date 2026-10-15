import asyncio

from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine


def test_health_is_liveness_without_database(monkeypatch):
    def forbidden_connection(*args, **kwargs):
        raise AssertionError("Health must not access PostgreSQL")

    monkeypatch.setattr(Engine, "connect", forbidden_connection)
    from app.main import create_app

    async def check():
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
            # These routes now exist; inspecting OpenAPI needs no database.
            paths = (await client.get("/openapi.json")).json()["paths"]
            assert {"get", "post"} <= paths["/documents"].keys()

    asyncio.run(check())
