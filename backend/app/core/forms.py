"""Helpers for hand-declared multipart forms.

A Pydantic model annotated with ``Form()`` is only flattened by FastAPI when it is
the *sole* body parameter; alongside ``File()`` uploads it gets embedded under its
own key instead. Endpoints that take both therefore declare their form fields
explicitly and validate them through the model here, so the response body for a
validation failure is identical to a JSON endpoint's.
"""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)


def validate_form(model: type[ModelT], values: dict[str, Any]) -> ModelT:
    """Validate form values, re-raising as FastAPI's standard 422 body error."""
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        raise RequestValidationError(
            [
                {
                    "type": error["type"],
                    "loc": ("body", *error["loc"]),
                    "msg": error["msg"],
                    "input": error.get("input"),
                }
                for error in exc.errors(include_url=False)
            ]
        ) from exc
