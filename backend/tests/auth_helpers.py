"""Synthetic browser-like HTTP clients and controlled clock for backend tests."""
import asyncio
from datetime import datetime, timedelta, timezone
from httpx import ASGITransport, AsyncClient, Cookies
from app.auth import service

ORIGIN = "http://127.0.0.1:8000"
PASSWORD = "Synthetic secure password 123!"


class APIClient:
    def __init__(self, app):
        self.app = app
        self.cookies = Cookies()

    def request(self, method, path, **kwargs):
        async def run():
            async with AsyncClient(transport=ASGITransport(app=self.app), base_url=ORIGIN, cookies=self.cookies) as client:
                response = await client.request(method, path, **kwargs)
                self.cookies = client.cookies
                return response
        return asyncio.run(run())

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def close(self):
        pass


class Clock:
    def __init__(self):
        self.now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class Browser:
    def __init__(self, database, clock):
        self.app = database.make_app()
        self.app.state.clock = clock
        self.client = APIClient(self.app)
        self.csrf = None

    def bootstrap(self):
        response = self.client.get("/auth/csrf", headers={"Origin": ORIGIN})
        assert response.status_code == 200
        self.csrf = response.json()["csrf_token"]
        return response

    def post(self, path, **kwargs):
        headers = {"Origin": ORIGIN, "X-CSRF-Token": self.csrf or "", **kwargs.pop("headers", {})}
        return self.client.post(path, headers=headers, **kwargs)

    def account(self, email="student@example.com"):
        self.bootstrap()
        assert self.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code == 202
        return self.login(email)

    def login(self, email="student@example.com", password=PASSWORD):
        response = self.post("/auth/login", json={"email": email, "password": password})
        if response.status_code == 200:
            self.csrf = response.json()["csrf_token"]
        return response

    def upload(self, text=b"synthetic text", filename="same.txt", **kwargs):
        return self.post("/documents", files={"file": (filename, text)}, **kwargs)
