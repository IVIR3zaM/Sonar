"""Request-body parsing shared by the API modules."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

_JSON_CONTENT_TYPE = "application/json"


class _StrictModel(BaseModel):
    """Every field optional text or null; an unknown field is a typo, not data."""

    model_config = ConfigDict(extra="forbid")


def _numeric_as_text(value: object) -> object:
    # JSON senders may write position/amount as a number; pass it on as the
    # text `categorization.service` already parses, so both shapes work the same.
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int | float):
        return str(value)
    return value


async def _parse_body(request: Request, model_cls: type[BaseModel]) -> BaseModel | JSONResponse:
    """The body as a `model_cls` instance, or the 415/422 response to return in its place."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != _JSON_CONTENT_TYPE:
        return JSONResponse({"error": "Content-Type must be application/json"}, status_code=415)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "Body is not valid JSON"}, status_code=422)
    if not isinstance(payload, dict):
        return JSONResponse(
            {"error": "Invalid request body", "details": "expected a JSON object"}, status_code=422
        )
    try:
        return model_cls(**payload)
    except ValidationError as error:
        return JSONResponse(
            {"error": "Invalid request body", "details": error.errors()}, status_code=422
        )
