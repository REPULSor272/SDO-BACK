from http import HTTPStatus

from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.jwt_handler import decode_access_token


PUBLIC_PATHS = {
    "/docs",
    "/openapi.json",
    "/login",
    "/register",
    "/api/groups",
    "/health",
}


class AuthMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)

        # Пропускаем CORS preflight и публичные пути без авторизации
        if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        auth_header = request.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            response = JSONResponse(
                status_code=HTTPStatus.UNAUTHORIZED,
                content={"detail": "Not authenticated"},
            )
            await response(scope, receive, send)
            return

        token = auth_header[len("Bearer "):]
        decoded_token = decode_access_token(token)
        if isinstance(decoded_token, str):
            response = JSONResponse(
                status_code=HTTPStatus.UNAUTHORIZED,
                content={"error": decoded_token},
            )
            await response(scope, receive, send)
            return

        # Прокидываем user_id в scope так, чтобы request.state.user_id работал как раньше
        scope.setdefault("state", {})
        scope["state"]["user_id"] = decoded_token.get("user_id")

        await self.app(scope, receive, send)