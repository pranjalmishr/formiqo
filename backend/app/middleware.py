"""Enforce bounded request bodies before FastAPI parses multipart uploads."""
from fastapi.responses import JSONResponse
from .config import settings


class RequestSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] in ('GET', 'HEAD', 'OPTIONS'):
            return await self.app(scope, receive, send)
        maximum = settings.max_upload_mb * 1024 * 1024 + 65536 if scope['path'] in ('/api/resumes/upload', '/api/converter/jobs','/api/tools/prepare') else 1024 * 1024
        headers = dict(scope.get('headers', []))
        try:
            declared = int(headers.get(b'content-length', b'0'))
        except ValueError:
            return await JSONResponse({'detail': 'Invalid content length.'}, status_code=400)(scope, receive, send)
        if declared < 0 or declared > maximum:
            return await JSONResponse({'detail': 'Request exceeds the configured size limit.'}, status_code=413)(scope, receive, send)
        total = 0
        exceeded = False
        started = False

        async def limited_receive():
            nonlocal total, exceeded
            message = await receive()
            if message['type'] == 'http.request':
                total += len(message.get('body', b''))
                if total > maximum:
                    exceeded = True
                    # Returning disconnect stops multipart processing without buffering the rest.
                    return {'type': 'http.disconnect'}
            return message

        async def bounded_send(message):
            nonlocal started
            if exceeded:
                if not started:
                    started = True
                    await JSONResponse({'detail': 'Request exceeds the configured size limit.'}, status_code=413)(scope, receive, send)
                return
            if message['type'] == 'http.response.start':
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, bounded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not started:
            await JSONResponse({'detail': 'Request exceeds the configured size limit.'}, status_code=413)(scope, receive, send)
