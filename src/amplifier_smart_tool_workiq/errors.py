"""Error types and safe diagnostics."""

from __future__ import annotations

import re

_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_TOKEN_FIELD_RE = re.compile(
    r'(?i)("?(?:access|refresh|id)[_-]?token"?\s*[:=]\s*)("[^"]+"|\S+)'
)


def sanitize(text: str) -> str:
    """Remove credential-shaped values from external diagnostics."""
    sanitized = _BEARER_RE.sub("Bearer [REDACTED]", text)
    return _TOKEN_FIELD_RE.sub(r"\1[REDACTED]", sanitized)


class WorkIqError(RuntimeError):
    """Actionable failure returned by the Work IQ integration."""

    def __init__(self, code: str, message: str, remedy: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = sanitize(message)
        self.remedy = remedy
        self.retryable = retryable

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "remedy": self.remedy,
            "retryable": self.retryable,
        }
