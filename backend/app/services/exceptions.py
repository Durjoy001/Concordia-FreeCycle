"""Domain errors raised by the service layer.

Routers stay thin: services raise these, and a single handler registered in
app.main translates them into HTTP responses.
"""

from __future__ import annotations

from http import HTTPStatus


class ServiceError(Exception):
    """Base class for all expected (non-bug) service-layer failures."""

    status_code: int = HTTPStatus.BAD_REQUEST
    default_detail: str = "Request could not be processed."

    def __init__(self, detail: str | None = None, *, headers: dict[str, str] | None = None) -> None:
        self.detail = detail or self.default_detail
        self.headers = headers
        super().__init__(self.detail)


class AuthenticationError(ServiceError):
    status_code = HTTPStatus.UNAUTHORIZED
    default_detail = "Could not validate credentials."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail, headers={"WWW-Authenticate": "Bearer"})


class PermissionDenied(ServiceError):
    status_code = HTTPStatus.FORBIDDEN
    default_detail = "You do not have permission to perform this action."


class NotFound(ServiceError):
    status_code = HTTPStatus.NOT_FOUND
    default_detail = "Resource not found."


class Conflict(ServiceError):
    status_code = HTTPStatus.CONFLICT
    default_detail = "Request conflicts with the current state of the resource."


class UnprocessableEntity(ServiceError):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    default_detail = "Request could not be processed."


class BudgetExceeded(ServiceError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    default_detail = "Daily AI assistant budget exhausted. Try again tomorrow."


class AgentUnavailable(ServiceError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    default_detail = "The AI assistant is unavailable right now. You can still fill the form in manually."
