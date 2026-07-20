from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


def envelope(
    request: Request,
    data: Any,
    *,
    status_code: int = 200,
    meta: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": "OK",
            "message": "success",
            "data": data,
            "meta": meta or {},
            "request_id": request.state.request_id,
        },
        headers=headers,
    )

