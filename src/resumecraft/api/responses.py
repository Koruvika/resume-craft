"""OpenAPI `responses=` entries for the error envelope.

Documentation only — what goes on the wire is decided by `api/errors.py`.
Each route lists the statuses it can return, so the schema shows our envelope
instead of FastAPI's default `HTTPValidationError` for 422.
"""

from typing import Any

from resumecraft.schemas.error import ErrorResponse

Responses = dict[int | str, dict[str, Any]]


def error(
    description: str, code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One `responses=` entry: the envelope model plus an example body."""
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return {
        "model": ErrorResponse,
        "description": description,
        "content": {"application/json": {"example": {"error": body}}},
    }


def not_found(resource: str) -> dict[str, Any]:
    resource_id = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    return error(
        f"No {resource} with this id belongs to the current user (`{resource}_not_found`)",
        f"{resource}_not_found",
        f"{resource} {resource_id} not found",
        {"resource": resource, "id": resource_id},
    )


UNAUTHENTICATED = error(
    "Missing, malformed or expired bearer token (`unauthenticated`)",
    "unauthenticated",
    "Not authenticated",
)

INVALID_INPUT = error(
    "Body, path or query parameters failed validation (`invalid_input`)",
    "invalid_input",
    "The request body or parameters are invalid",
    {"fields": [{"loc": ["query", "limit"], "msg": "Input should be ...", "type": "..."}]},
)

INTERNAL_ERROR = error(
    "Unexpected server error; no internals are exposed (`internal_error`)",
    "internal_error",
    "An unexpected error occurred",
)
