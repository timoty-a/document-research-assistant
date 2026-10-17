"""Small JSON auth contract; synchronous services always run in workers."""
import json

from email_validator import EmailNotValidError
from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from app.auth import service
from app.auth.security import Credentials

router = APIRouter(prefix="/auth", tags=["authentication"])


def arguments(request):
    state = request.app.state
    return state.engine, state.settings


def cookie(response, raw, identity, clock):
    response.set_cookie(service.COOKIE, raw, max_age=max(0, int((identity.expires_at - clock()).total_seconds())),
                        httponly=True, secure=False, samesite="lax", path="/")


def user_response(identity):
    return {"user": {"id": str(identity.user_id), "email": identity.email},
            "expires_at": identity.expires_at.isoformat(), "session_context": str(identity.session_context)}


@router.get("/csrf")
async def csrf(request: Request):
    await run_in_threadpool(service.throttle, *arguments(request),
                           [("csrf_ip", request.client.host, 60, 60)], request.app.state.clock)
    raw, identity = await run_in_threadpool(service.bootstrap, *arguments(request),
                                          request.cookies.get(service.COOKIE), request.app.state.clock)
    response = JSONResponse({"csrf_token": identity.csrf_token})
    if raw:
        cookie(response, raw, identity, request.app.state.clock)
    if identity.user_id:
        response.headers["X-Session-Context"] = str(identity.session_context)
    return response


async def credentials(request):
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise service.AuthError(415, "unsupported_media_type", "Use application/json.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 8192:
            raise service.AuthError(413, "request_too_large", "Credential request exceeds 8 KiB.")
        body.extend(chunk)
    try:
        value = Credentials.model_validate(json.loads(body))
        value.identity()
        return value
    except (ValueError, ValidationError, EmailNotValidError, UnicodeError, RecursionError):
        raise service.AuthError(422, "invalid_credentials_input",
                                "Provide a valid email and a password of 15–128 characters (at most 512 UTF-8 bytes).") from None
    finally:
        # Minimize retained request data; Python cannot guarantee memory erasure.
        body.clear()


@router.post("/register", status_code=202)
async def register(request: Request):
    await run_in_threadpool(service.throttle, *arguments(request),
                           [("register_ip", request.client.host, 5, 3600)], request.app.state.clock)
    value = await credentials(request)
    await run_in_threadpool(service.register, *arguments(request), value, request.cookies.get(service.COOKIE),
                           request.headers.get("x-csrf-token"), request.app.state.clock)
    return {"message": "Registration request processed. Try signing in with your credentials."}


@router.post("/login")
async def login(request: Request):
    await run_in_threadpool(service.throttle, *arguments(request),
                           [("login_ip", request.client.host, 20, 300)], request.app.state.clock)
    value = await credentials(request)
    _, key = value.identity()
    await run_in_threadpool(service.throttle, *arguments(request), [("login_email", key, 5, 900)], request.app.state.clock)
    raw, identity = await run_in_threadpool(service.login, *arguments(request), value,
                                          request.cookies.get(service.COOKIE), request.headers.get("x-csrf-token"), request.app.state.clock)
    response = JSONResponse({**user_response(identity), "csrf_token": identity.csrf_token})
    response.headers["X-Session-Context"] = str(identity.session_context)
    cookie(response, raw, identity, request.app.state.clock)
    return response


@router.post("/logout", status_code=204)
async def logout(request: Request):
    await run_in_threadpool(service.logout, *arguments(request), request.cookies.get(service.COOKIE),
                           request.headers.get("x-csrf-token"), request.app.state.clock)
    response = Response(status_code=204)
    response.delete_cookie(service.COOKIE, path="/", httponly=True, secure=False, samesite="lax")
    return response


@router.get("/me")
async def me(request: Request):
    identity = await run_in_threadpool(service.authenticate, *arguments(request),
                                      request.cookies.get(service.COOKIE), request.app.state.clock)
    return JSONResponse(user_response(identity), headers={"X-Session-Context": str(identity.session_context)})
