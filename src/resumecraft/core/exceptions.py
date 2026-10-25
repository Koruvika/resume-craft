"""Exception hierarchy for errors resumecraft raises deliberately.

Framework-free on purpose: services and the worker raise these without pulling
in FastAPI. The HTTP translation lives in `api/errors.py`.

Every error carries three things the API contract depends on:

- `code`: a stable machine-readable slug clients can branch on (`file_too_large`).
  Never change one without treating it as a breaking API change.
- `message`: one human-readable sentence, safe to show a user.
- `details`: extra JSON-serializable fields (limits, ids, field errors).
"""

from http import HTTPStatus
from typing import Any

__all__ = [
    "AuthenticationError",
    "ConflictError",
    "EmailAlreadyRegisteredError",
    "FileTooLargeError",
    "InvalidInputError",
    "InvalidRenderOptionError",
    "InvalidResumeFileError",
    "NotFoundError",
    "PdfRenderError",
    "PermissionDeniedError",
    "ResumeCraftError",
    "ResumeNotReadyError",
    "UnsupportedFileTypeError",
]


class ResumeCraftError(Exception):
    """Base class for all deliberate platform errors."""

    code: str = "internal_error"
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    default_message: str = "An unexpected error occurred"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or type(self).default_message
        self.code = code or type(self).code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """The `error` object of the HTTP response body."""
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


class InvalidInputError(ResumeCraftError):
    """Domain-level validation, beyond what the request schema can express.

    Named to avoid colliding with `pydantic.ValidationError`, which covers
    request parsing.
    """

    code = "invalid_input"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    default_message = "The request is not valid"


class AuthenticationError(ResumeCraftError):
    code = "unauthenticated"
    status_code = HTTPStatus.UNAUTHORIZED
    default_message = "Authentication required"


class PermissionDeniedError(ResumeCraftError):
    code = "permission_denied"
    status_code = HTTPStatus.FORBIDDEN
    default_message = "You do not have access to this resource"


class NotFoundError(ResumeCraftError):
    """Raised with the resource name so the code reads `job_not_found`, `user_not_found`."""

    code = "not_found"
    status_code = HTTPStatus.NOT_FOUND
    default_message = "Resource not found"

    def __init__(
        self, resource: str, resource_id: Any = None, *, message: str | None = None
    ) -> None:
        details: dict[str, Any] = {"resource": resource}
        if resource_id is not None:
            details["id"] = str(resource_id)
        label = f"{resource} {resource_id}" if resource_id is not None else resource
        super().__init__(
            message or f"{label} not found",
            code=f"{resource}_not_found",
            details=details,
        )


class ConflictError(ResumeCraftError):
    code = "conflict"
    status_code = HTTPStatus.CONFLICT
    default_message = "The resource is in a conflicting state"


class EmailAlreadyRegisteredError(ConflictError):
    code = "email_already_registered"
    status_code = HTTPStatus.CONFLICT
    default_message = "Email already registered"

    def __init__(self, email: str) -> None:
        super().__init__(details={"email": email})


class ResumeNotReadyError(ConflictError):
    """Render requested for a resume whose parse job has not completed."""

    code = "resume_not_ready"
    status_code = HTTPStatus.CONFLICT
    default_message = "Resume is not ready yet"

    def __init__(self, status: str, *, message: str | None = None) -> None:
        super().__init__(message=message, details={"status": status})


class UnsupportedFileTypeError(ResumeCraftError):
    """The upload's declared content type is not one we accept.

    422 rather than 415: the content type is validated as part of the request,
    alongside the rest of the upload rules, not negotiated beforehand.
    """

    code = "unsupported_file_type"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    default_message = "Unsupported file type"

    def __init__(
        self, mime: str, supported: list[str] | None = None, *, message: str | None = None
    ) -> None:
        super().__init__(
            message or f"Files of type {mime} are not supported",
            details={"mime": mime, "supported": supported or []},
        )


class FileTooLargeError(ResumeCraftError):
    code = "file_too_large"
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    default_message = "File is too large"

    def __init__(self, *, size_bytes: int, max_bytes: int, message: str | None = None) -> None:
        super().__init__(
            message or f"File is {size_bytes} bytes, the limit is {max_bytes}",
            details={"size_bytes": size_bytes, "max_bytes": max_bytes},
        )


class InvalidResumeFileError(InvalidInputError):
    """Uploaded bytes are not JSON or do not validate as a ParsedResume."""

    code = "invalid_resume_file"
    default_message = "File is not a valid ParsedResume"


class InvalidRenderOptionError(InvalidInputError):
    """A theme/locale query parameter is not one rendercv knows."""

    code = "invalid_render_option"
    default_message = "Unknown render option"


class PdfRenderError(ResumeCraftError):
    """The typst/rendercv pipeline failed to produce a PDF.

    500: the inputs were validated, so a failure here is on our side (a theme
    bug, a font problem), not something the client can fix.
    """

    code = "pdf_render_failed"
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    default_message = "Failed to render the resume PDF"
