"""Translation of exceptions into HTTP responses.

Every error — ours, FastAPI's, or an unhandled crash — leaves through here in
one shape:

    {"error": {"code": ..., "message": ..., "details": {...}}}
"""

from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from resumecraft.core.exceptions import AuthenticationError, ResumeCraftError

logger = structlog.get_logger(__name__)

INTERNAL_ERROR = {
    "code": "internal_error",
    "message": "An unexpected error occurred",
}


def _response(
    *,
    status_code: int,
    error: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


async def handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ResumeCraftError)

    # 4xx is the caller's problem and expected traffic — logging it as an error
    # would bury the failures that actually need attention. 5xx is ours, with a
    # traceback.
    if exc.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        logger.exception("request_error", code=exc.code, status_code=exc.status_code)
    else:
        logger.warning(
            "request_rejected",
            code=exc.code,
            status_code=exc.status_code,
            message=exc.message,
            details=exc.details or None,
        )

    headers = None
    if isinstance(exc, AuthenticationError):
        # RFC 7235: a 401 must say which scheme the client should authenticate with.
        headers = {"WWW-Authenticate": "Bearer"}

    return _response(status_code=exc.status_code, error=exc.to_dict(), headers=headers)


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    logger.warning("request_validation_failed", error_count=len(exc.errors()))

    return _response(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        error={
            "code": "invalid_input",
            "message": "The request body or parameters are invalid",
            # Pydantic's own per-field report, minus the internal input echo.
            "details": {
                "fields": [
                    {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
                    for err in exc.errors()
                ]
            },
        },
    )


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """Normalizes FastAPI/Starlette's own errors (404 routing, 405) into our envelope."""
    assert isinstance(exc, StarletteHTTPException)

    # Not every status code is in the IANA enum — 499 from nginx, or anything a
    # proxy invents. `HTTPStatus(499)` raises, which would drop the whole
    # response to a bare 500, so fall back to a generic phrase instead.
    try:
        phrase = HTTPStatus(exc.status_code).phrase
    except ValueError:
        phrase = "Error"

    return _response(
        status_code=exc.status_code,
        error={
            "code": phrase.lower().replace(" ", "_"),
            "message": exc.detail if isinstance(exc.detail, str) else phrase,
        },
        headers=getattr(exc, "headers", None),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Last resort: return a 500 that tells the client nothing about internals."""
    logger.exception("unhandled_exception", exc_type=type(exc).__name__)
    return _response(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, error=INTERNAL_ERROR)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ResumeCraftError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
