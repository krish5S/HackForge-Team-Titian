"""Bound multipart bodies even when Content-Length is omitted or dishonest."""
from starlette.responses import JSONResponse


class BodyTooLarge(Exception):
    pass


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'POST' or scope['path'].rstrip('/') != '/api/employee/submissions':
            return await self.app(scope, receive, send)
        total = 0

        async def bounded_receive():
            nonlocal total
            message = await receive()
            total += len(message.get('body', b''))
            if total > 11 * 1024 * 1024:
                raise BodyTooLarge()
            return message

        try:
            await self.app(scope, bounded_receive, send)
        except BodyTooLarge:
            response = JSONResponse({'error': {'code': 'HTTP_413', 'message': 'Upload exceeds the 10 MiB file limit.', 'details': {}}}, status_code=413)
            await response(scope, receive, send)
