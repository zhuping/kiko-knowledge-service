from __future__ import annotations

from typing import Any


def success(data: Any, request_id: str, release_version: str | None = None) -> dict:
    response = {
        "code": "OK",
        "message": "success",
        "requestId": request_id,
        "data": data,
    }
    if release_version:
        response["meta"] = {"releaseVersion": release_version}
    return response


def failure(code: str, message: str, request_id: str, details: Any = None) -> dict:
    return {
        "code": code,
        "message": message,
        "requestId": request_id,
        "error": {"code": code, "message": message, "details": details or {}},
    }
