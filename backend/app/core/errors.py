from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.headers = headers or {}


def not_found(resource: str = "resource") -> AppError:
    return AppError(404, "NOT_FOUND", f"{resource} not found")


def validation(path: list[object], reason: str, value: object | None = None) -> AppError:
    detail: dict[str, Any] = {"path": path, "reason": reason}
    if value is not None:
        detail["value"] = value
    return AppError(422, "VALIDATION_ERROR", "request validation failed", [detail])

