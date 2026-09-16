"""Validated, bounded read-only Work IQ data plans."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import WorkIqError
from .workflows import validate_fetch_path

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FIELDS = {"format", "name", "description", "requests"}
_REQUEST_FIELDS = {"name", "path"}
_MAX_REQUESTS = 10
_MAX_NAME_LENGTH = 64


@dataclass(frozen=True)
class DataRequest:
    """One named, bounded Work IQ fetch."""

    name: str
    path: str


@dataclass(frozen=True)
class DataPlan:
    """A reviewable collection of read-only Work IQ fetches."""

    format: int
    name: str
    description: str
    requests: tuple[DataRequest, ...]

    @classmethod
    def from_dict(cls, value: Any) -> "DataPlan":
        if not isinstance(value, dict) or set(value) != _FIELDS:
            raise WorkIqError(
                "invalid_data_plan",
                "A data plan must contain exactly format, name, description, "
                "and requests.",
                "Correct the data plan JSON and retry.",
            )
        if value["format"] != 1:
            raise WorkIqError(
                "unsupported_data_plan_format",
                "Only data plan format 1 is supported.",
                "Set the data plan format field to 1.",
            )

        name = _validated_name(value["name"], "data plan")
        description = value["description"]
        if not isinstance(description, str) or not description.strip():
            raise WorkIqError(
                "invalid_data_plan",
                "Data plan descriptions must be nonempty strings.",
                "Describe the information the plan retrieves.",
            )

        raw_requests = value["requests"]
        if (
            not isinstance(raw_requests, list)
            or not raw_requests
            or len(raw_requests) > _MAX_REQUESTS
        ):
            raise WorkIqError(
                "invalid_data_plan_requests",
                f"Data plans must contain 1-{_MAX_REQUESTS} requests.",
                "Add a bounded set of read-only fetch requests.",
            )

        requests: list[DataRequest] = []
        request_names: set[str] = set()
        for raw_request in raw_requests:
            if not isinstance(raw_request, dict) or set(raw_request) != _REQUEST_FIELDS:
                raise WorkIqError(
                    "invalid_data_plan_request",
                    "Each data plan request must contain exactly name and path.",
                    "Correct the request object and retry.",
                )
            request_name = _validated_name(raw_request["name"], "request")
            if request_name in request_names:
                raise WorkIqError(
                    "duplicate_data_plan_request",
                    f"Data plan request '{request_name}' is duplicated.",
                    "Give every request a unique name.",
                )
            request_names.add(request_name)
            path = raw_request["path"]
            if not isinstance(path, str):
                raise WorkIqError(
                    "invalid_data_plan_request",
                    f"Data plan request '{request_name}' has a non-string path.",
                    "Provide a relative Work IQ fetch path.",
                )
            requests.append(
                DataRequest(
                    name=request_name,
                    path=validate_fetch_path(path),
                )
            )

        return cls(
            format=1,
            name=name,
            description=description.strip(),
            requests=tuple(requests),
        )

    @classmethod
    def read(cls, path: Path) -> "DataPlan":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise WorkIqError(
                "data_plan_file_not_found",
                f"Data plan file '{path}' does not exist.",
                "Provide an existing UTF-8 JSON file.",
            ) from error
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WorkIqError(
                "invalid_data_plan_json",
                f"Data plan file '{path}' is not valid UTF-8 JSON.",
                "Correct the file and retry.",
            ) from error
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["requests"] = [asdict(request) for request in self.requests]
        return value

    def paths(self) -> list[str]:
        return [request.path for request in self.requests]


def _validated_name(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_NAME_LENGTH
        or not _NAME_RE.fullmatch(value)
    ):
        raise WorkIqError(
            "invalid_data_plan_name",
            f"{label.capitalize()} names must contain at most "
            f"{_MAX_NAME_LENGTH} lowercase letters, numbers, and single hyphens.",
            "Choose a name such as 'daily-context' or 'recent-project-mail'.",
        )
    return value
