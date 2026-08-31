"""
mcma.app.api.errors -- typed, non-sensitive error responses with a
correlation id (INC-17, F19/F20). No raw `str(exc)` ever reaches a
client; an unexpected exception is logged server-side (INC-20 owns real
structured logging) and returned as a fixed, generic message plus a
correlation id an operator can use to find the real detail server-side.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Raise this from any route/dependency for a truthful, typed error.
    `message` MUST be a fixed, non-sensitive string -- never interpolate
    a raw exception, request body, or portal/DB detail into it."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _problem(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": code, "message": message, "correlation_id": uuid.uuid4().hex},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError):
        return _problem(exc.status_code, exc.code, exc.message)

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception):
        # Never str(exc) here -- it could contain a raw portal URL, a
        # DB detail, or other internal information (F19).
        return _problem(500, "INTERNAL_ERROR", "an unexpected error occurred")
