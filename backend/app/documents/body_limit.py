"""Authenticated multipart body cap before bytes reach the form parser."""
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

MAX_BODY_BYTES = 2_097_152


class BodyTooLarge(Exception):
    pass


class UploadBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('path', '').rstrip('/') != '/documents' or scope['method'] != 'POST':
            return await self.app(scope, receive, send)
        response = JSONResponse({'detail': 'Multipart body exceeds the 2 MiB limit'}, status_code=413)
        declared = Headers(scope=scope).get('content-length', '')
        if declared.isascii() and declared.isdecimal() and (len(declared.lstrip('0')) > 7 or int(declared.lstrip('0') or '0') > MAX_BODY_BYTES):
            return await response(scope, receive, send)
        size = 0
        exceeded = False
        replaced = False

        async def bounded_receive():
            nonlocal size, exceeded
            message = await receive()
            if message['type'] == 'http.request':
                size += len(message.get('body', b''))
                if size > MAX_BODY_BYTES:
                    exceeded = True
                    # Starlette closes partial multipart files on stream errors.
                    raise BodyTooLarge()
            return message

        async def bounded_send(message):
            nonlocal replaced
            if exceeded:
                # FastAPI may translate a parser exception into 400; enforce 413.
                if not replaced:
                    replaced = True
                    await response(scope, receive, send)
                return
            await send(message)

        try:
            await self.app(scope, bounded_receive, bounded_send)
        except BodyTooLarge:
            if not replaced:
                await response(scope, receive, send)
