"""Amplifier Smart Tool for Microsoft Work IQ."""

from .client import WorkIqMcpClient
from .errors import WorkIqError
from .workflows import WorkIqService

__all__ = ["WorkIqError", "WorkIqMcpClient", "WorkIqService"]
__version__ = "0.1.0"
