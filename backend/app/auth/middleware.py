"""Header/session boundary runs before FastAPI's multipart/body parsing."""
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.auth import service


def error_response(error):
    headers = {"Cache-Control": "no-store"}
    if error.retry_after is not None:
        headers["Retry-After"] = str(error.retry_after)
    return JSONResponse({"error": error.code, "message": error.message}, status_code=error.status, headers=headers)


class AuthBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "").rstrip("/")
        protected = path == "/documents" or path.startswith("/documents/") or path.startswith("/research/")
        private = protected or path.startswith("/auth/")
        if scope["type"] != "http" or not private:
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        state = request.app.state
        identity = None
        try:
            origin = request.headers.get("origin")
            if protected and request.method in {"GET", "POST"}:
                # Authenticate first, including unauthorized POST with a bogus Origin.
                identity = await run_in_threadpool(service.authenticate, state.engine, state.settings,
                                                  request.cookies.get(service.COOKIE), state.clock, touch=False)
                scope.setdefault("state", {})["identity"] = identity
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                if origin not in service.ORIGINS:
                    raise service.forbidden()
                if protected and request.method == "POST":
                    service.check_csrf(identity, request.headers.get("x-csrf-token"))
                elif path in {"/auth/login", "/auth/register"}:
                    def check():
                        with service.transaction(state.engine, state.settings) as connection:
                            service.checked_context(connection, request.cookies.get(service.COOKIE),
                                                    request.headers.get("x-csrf-token"), state.clock)
                    await run_in_threadpool(check)
                # Logout checks the current context inside its revocation transaction.
            if path == "/auth/csrf":
                site = request.headers.get("sec-fetch-site")
                if site == "cross-site" or (origin is not None and origin not in service.ORIGINS):
                    raise service.forbidden()
                if site != "same-origin" and origin not in service.ORIGINS:
                    raise service.forbidden()

            async def private_send(message):
                if message["type"] == "http.response.start":
                    headers = MutableHeaders(scope=message)
                    headers["Cache-Control"] = "no-store"
                    if identity:
                        headers["X-Session-Context"] = str(identity.session_context)
                await send(message)
            await self.app(scope, receive, private_send)
        except service.AuthError as error:
            await error_response(error)(scope, receive, send)
