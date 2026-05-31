from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from agent.core.schemas import ProblemDetail
from agent.core.telemetry import get_logger, set_correlation_id

logger = get_logger(__name__)

_OPEN_PATHS = {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}

_CallNext = Callable[[Request], Awaitable[Response]]


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Inject a correlation ID on every request; expose it in the response."""

    async def dispatch(self, request: Request, call_next: _CallNext) -> Response:
        cid = request.headers.get("X-Request-ID", str(uuid4()))
        set_correlation_id(cid)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = cid
        return response


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Validate Bearer JWT on all non-open paths."""

    def __init__(self, app: object, secret_key: str, algorithm: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._secret = secret_key
        self._algorithm = algorithm

    async def dispatch(self, request: Request, call_next: _CallNext) -> Response:
        if request.url.path in _OPEN_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _problem(401, "Unauthorized", "Missing or malformed Authorization header.")

        token = auth_header[7:]
        try:
            jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except JWTError:
            return _problem(401, "Unauthorized", "Invalid or expired token.")

        response: Response = await call_next(request)
        return response


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    body = ProblemDetail(title=title, status=status, detail=detail)
    return JSONResponse(
        status_code=status,
        content=body.model_dump(),
        media_type="application/problem+json",
    )


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    body = ProblemDetail(
        title="Too Many Requests",
        status=429,
        detail=str(exc.detail),
        instance=str(request.url),
    )
    return JSONResponse(
        status_code=429,
        content=body.model_dump(),
        media_type="application/problem+json",
    )
