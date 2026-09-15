"""Validated user-defined Work IQ workflow profiles."""

from __future__ import annotations

import json
import os
import re
import string
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import WorkIqError

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_INPUT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_FIELDS = {"format", "name", "description", "prompt", "inputs"}
_MAX_PROMPT_LENGTH = 12_000
_MAX_NAME_LENGTH = 64


@dataclass(frozen=True)
class WorkflowProfile:
    """A named, parameterized read-only Work IQ workflow."""

    format: int
    name: str
    description: str
    prompt: str
    inputs: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any) -> "WorkflowProfile":
        if not isinstance(value, dict) or set(value) != _FIELDS:
            raise WorkIqError(
                "invalid_profile",
                "A workflow profile must contain exactly format, name, "
                "description, prompt, and inputs.",
                "Correct the profile JSON and retry.",
            )
        if value["format"] != 1:
            raise WorkIqError(
                "unsupported_profile_format",
                "Only workflow profile format 1 is supported.",
                "Set the profile format field to 1.",
            )

        name = value["name"]
        if (
            not isinstance(name, str)
            or len(name) > _MAX_NAME_LENGTH
            or not _NAME_RE.fullmatch(name)
        ):
            raise WorkIqError(
                "invalid_profile_name",
                f"Workflow names must contain at most {_MAX_NAME_LENGTH} "
                "lowercase letters, numbers, and single hyphens.",
                "Choose a name such as 'project-status' or 'customer-briefing'.",
            )

        description = value["description"]
        if not isinstance(description, str) or not description.strip():
            raise WorkIqError(
                "invalid_profile",
                "Workflow descriptions must be nonempty strings.",
                "Add a concise description of when to use the workflow.",
            )

        prompt = value["prompt"]
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or len(prompt) > _MAX_PROMPT_LENGTH
        ):
            raise WorkIqError(
                "invalid_profile",
                f"Workflow prompts must contain 1-{_MAX_PROMPT_LENGTH} characters.",
                "Provide a focused read-only workplace analysis prompt.",
            )

        raw_inputs = value["inputs"]
        if (
            not isinstance(raw_inputs, list)
            or any(
                not isinstance(item, str) or not _INPUT_RE.fullmatch(item)
                for item in raw_inputs
            )
            or len(set(raw_inputs)) != len(raw_inputs)
        ):
            raise WorkIqError(
                "invalid_profile_inputs",
                "Workflow inputs must be a unique list of lowercase identifiers.",
                "Use input names such as project, customer, or review_date.",
            )

        placeholders = _template_fields(prompt)
        declared = set(raw_inputs)
        if placeholders != declared:
            raise WorkIqError(
                "profile_input_mismatch",
                "Prompt placeholders must exactly match the declared inputs.",
                f"Declared inputs: {sorted(declared)}; prompt placeholders: "
                f"{sorted(placeholders)}.",
            )

        return cls(
            format=1,
            name=name,
            description=description.strip(),
            prompt=prompt.strip(),
            inputs=tuple(raw_inputs),
        )

    @classmethod
    def read(cls, path: Path) -> "WorkflowProfile":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise WorkIqError(
                "profile_file_not_found",
                f"Workflow profile file '{path}' does not exist.",
                "Provide an existing UTF-8 JSON file.",
            ) from error
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WorkIqError(
                "invalid_profile_json",
                f"Workflow profile file '{path}' is not valid UTF-8 JSON.",
                "Correct the file and retry.",
            ) from error
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["inputs"] = list(self.inputs)
        return value

    def render(self, values: dict[str, str]) -> str:
        expected = set(self.inputs)
        supplied = set(values)
        if expected != supplied:
            raise WorkIqError(
                "workflow_input_mismatch",
                "Workflow input values do not match the profile.",
                f"Required inputs: {sorted(expected)}; supplied inputs: "
                f"{sorted(supplied)}.",
            )
        return self.prompt.format_map(values)


class WorkflowStore:
    """Persist profiles in the conventional per-user configuration directory."""

    def __init__(self, root: Path | None = None):
        self.root = root or default_workflow_directory()

    def create(self, profile: WorkflowProfile, *, replace: bool = False) -> Path:
        destination = self.root / f"{profile.name}.json"
        temporary: Path | None = None
        payload = json.dumps(profile.to_dict(), indent=2, sort_keys=True) + "\n"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.root,
                prefix=f".{profile.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payload)
                temporary = Path(handle.name)

            if replace:
                os.replace(temporary, destination)
                temporary = None
            else:
                try:
                    os.link(temporary, destination)
                except FileExistsError as error:
                    raise WorkIqError(
                        "workflow_exists",
                        f"Workflow '{profile.name}' already exists.",
                        "Choose another name or explicitly use --replace "
                        "--confirmed.",
                    ) from error
        except WorkIqError:
            raise
        except OSError as error:
            raise WorkIqError(
                "workflow_write_failed",
                f"Could not persist workflow '{profile.name}': {error}",
                "Check permissions on the user configuration directory.",
            ) from error
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)
        return destination

    def list(self) -> list[WorkflowProfile]:
        if not self.root.exists():
            return []
        profiles = [self._read_stored(path) for path in self.root.glob("*.json")]
        return sorted(profiles, key=lambda profile: profile.name)

    def get(self, name: str) -> WorkflowProfile:
        if len(name) > _MAX_NAME_LENGTH or not _NAME_RE.fullmatch(name):
            raise WorkIqError(
                "invalid_profile_name",
                "Workflow names must use lowercase letters, numbers, and "
                "single hyphens.",
                "Provide a valid workflow name.",
            )
        path = self.root / f"{name}.json"
        if not path.is_file():
            raise WorkIqError(
                "workflow_not_found",
                f"Workflow '{name}' does not exist.",
                "Run 'workiq-smart-tool workflow list' to see saved workflows.",
            )
        return self._read_stored(path)

    def delete(self, name: str) -> None:
        self.get(name)
        path = self.root / f"{name}.json"
        try:
            path.unlink()
        except OSError as error:
            raise WorkIqError(
                "workflow_delete_failed",
                f"Could not delete workflow '{name}': {error}",
                "Check permissions on the user configuration directory.",
            ) from error

    @staticmethod
    def _read_stored(path: Path) -> WorkflowProfile:
        if path.is_symlink():
            raise WorkIqError(
                "invalid_stored_workflow",
                f"Stored workflow '{path.name}' must not be a symbolic link.",
                "Remove the link and recreate the workflow through the CLI.",
            )
        profile = WorkflowProfile.read(path)
        if path.stem != profile.name:
            raise WorkIqError(
                "invalid_stored_workflow",
                f"Stored workflow filename '{path.name}' does not match its "
                f"declared name '{profile.name}'.",
                "Rename or recreate the workflow so its filename and name match.",
            )
        return profile


def parse_input_values(items: list[str]) -> dict[str, str]:
    """Parse repeated key=value CLI arguments without shell evaluation."""
    values: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not _INPUT_RE.fullmatch(key) or key in values:
            raise WorkIqError(
                "invalid_workflow_input",
                f"Invalid workflow input '{item}'.",
                "Pass each input once using --input name=value.",
            )
        values[key] = value
    return values


def default_workflow_directory() -> Path:
    """Return a platform-appropriate user configuration directory."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    elif os.environ.get("XDG_CONFIG_HOME"):
        base = Path(os.environ["XDG_CONFIG_HOME"])
    else:
        base = Path.home() / ".config"
    return base / "amplifier-smart-tool-workiq" / "workflows"


def _template_fields(template: str) -> set[str]:
    fields: set[str] = set()
    try:
        parsed = string.Formatter().parse(template)
        for _literal, field_name, format_spec, conversion in parsed:
            if field_name is None:
                continue
            if (
                not _INPUT_RE.fullmatch(field_name)
                or format_spec
                or conversion
            ):
                raise ValueError
            fields.add(field_name)
    except ValueError as error:
        raise WorkIqError(
            "invalid_profile_template",
            "Workflow prompts contain an invalid placeholder.",
            "Use simple placeholders such as {project} with no conversions or "
            "format specifiers. Escape literal braces as {{ and }}.",
        ) from error
    return fields
