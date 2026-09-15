"""Locate and invoke the official Work IQ client."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence

from .errors import WorkIqError, sanitize

_PACKAGE = "@microsoft/workiq@latest"


def workiq_command() -> list[str]:
    """Return the installed Work IQ command or its npx fallback."""
    installed = shutil.which("workiq")
    if installed:
        return [installed]

    npx = shutil.which("npx")
    if npx:
        return [npx, "-y", _PACKAGE]

    raise WorkIqError(
        "missing_prerequisite",
        "Neither the Work IQ CLI nor npx is available.",
        "Install Node.js 18 or later from https://nodejs.org/en/download.",
    )


def run_workiq(
    arguments: Sequence[str],
    *,
    timeout: float,
    interactive: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run Work IQ without passing arguments through a shell."""
    command = [*workiq_command(), *arguments]
    try:
        options: dict[str, object] = {
            "check": False,
            "text": True,
            "timeout": timeout,
        }
        if interactive:
            options.update({"stdout": sys.stderr, "stderr": sys.stderr})
        else:
            options["capture_output"] = True
        return subprocess.run(command, **options)
    except subprocess.TimeoutExpired as error:
        raise WorkIqError(
            "workiq_timeout",
            f"Work IQ did not complete within {timeout:g} seconds.",
            "Retry the operation. If authentication was requested, run "
            "'workiq-smart-tool authenticate' first.",
            retryable=True,
        ) from error
    except OSError as error:
        raise WorkIqError(
            "workiq_start_failed",
            sanitize(str(error)),
            "Verify the Work IQ installation with 'npx -y "
            "@microsoft/workiq@latest --help'.",
        ) from error
