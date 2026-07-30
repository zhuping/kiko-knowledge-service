from __future__ import annotations

import logging
from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import ApiError
from app.core.ids import ulid

request_id_context: ContextVar[str] = ContextVar("request_id", default="")
logger = logging.getLogger(__name__)


def ok(data):
    return {"data": data, "request_id": request_id_context.get()}


def api_error(request: Request, exc: ApiError):
    return JSONResponse(
        {
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
            "request_id": request.state.request_id,
        },
        status_code=exc.status,
    )


def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        jsonable_encoder(
            {
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "请求参数不合法",
                    "details": {"errors": exc.errors()},
                },
                "request_id": request.state.request_id,
            }
        ),
        status_code=422,
    )


def internal_error(request: Request, exc: Exception):
    logger.error(
        "unhandled request error request_id=%s",
        request.state.request_id,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务内部错误",
                "details": {},
            },
            "request_id": request.state.request_id,
        },
        status_code=500,
    )


async def envelope(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or ulid()
    token = request_id_context.set(request.state.request_id)
    try:
        try:
            response = await call_next(request)
        except Exception as exc:  # FastAPI exception middleware is outside this layer.
            response = (
                api_error(request, exc)
                if isinstance(exc, ApiError)
                else internal_error(request, exc)
            )
        response.headers["X-Request-ID"] = request.state.request_id
        return response
    finally:
        request_id_context.reset(token)


def install_http(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, api_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, internal_error)
    app.middleware("http")(envelope)
