import time

from aiolimiter import AsyncLimiter
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings
from .logger import logger


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using aiolimiter."""

    def __init__(self, app, max_requests: int = None, time_window: int = None):
        super().__init__(app)
        self.max_requests = max_requests or settings.rate_limit_requests
        self.time_window = time_window or settings.rate_limit_window
        self.limiter = AsyncLimiter(self.max_requests, self.time_window)
        self.client_limiters = {}

    async def dispatch(self, request: Request, call_next):
        client_ip = self._get_client_ip(request)

        if client_ip not in self.client_limiters:
            self.client_limiters[client_ip] = AsyncLimiter(
                self.max_requests, self.time_window
            )

        limiter = self.client_limiters[client_ip]
        if not await limiter.acquire(amount=1):
            logger.warning(f"Rate limit exceeded for client: {client_ip}")
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "message": "Rate limit exceeded",
                        "type": "rate_limit_error",
                        "code": "rate_limit_exceeded",
                    }
                },
                headers={
                    "Retry-After": str(self.time_window),
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Window": str(self.time_window),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Window"] = str(self.time_window)
        return response

    def _get_client_ip(self, request: Request) -> str:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        return request.client.host if request.client else "unknown"


class LoggingMiddleware(BaseHTTPMiddleware):
    """Request/response logging middleware."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        logger.info(
            f"Request: {request.method} {request.url.path} "
            f"from {self._get_client_ip(request)}"
        )

        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            logger.info(f"Response: {response.status_code} ({process_time:.3f}s)")
            response.headers["X-Process-Time"] = str(process_time)
            return response
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"Request failed: {e} ({process_time:.3f}s)")
            raise

    def _get_client_ip(self, request: Request) -> str:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        return request.client.host if request.client else "unknown"


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Global error handling middleware."""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "message": "Internal server error",
                        "type": "server_error",
                        "code": "internal_error",
                    }
                },
            )


def create_error_response(
    message: str,
    error_type: str = "server_error",
    code: str = "internal_error",
    status_code: int = 500,
) -> JSONResponse:
    """Create standardized error response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "code": code,
            }
        },
    )
