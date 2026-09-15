from __future__ import annotations

import json
from typing import Any


class LCUError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        candidates: list[Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.candidates = candidates
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.candidates is not None:
            data["candidates"] = self.candidates
        if self.details:
            data["details"] = self.details
        return data


def format_success(action: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "action": action,
    }
    if result is not None:
        payload["result"] = result
    return payload


def format_error(action: str, exc: Exception | LCUError) -> dict[str, Any]:
    if isinstance(exc, LCUError):
        error_dict = exc.to_dict()
    else:
        error_dict = {
            "code": "unexpected_error",
            "message": str(exc) or exc.__class__.__name__,
        }
    return {
        "ok": False,
        "action": action,
        "error": error_dict,
    }


def output_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
