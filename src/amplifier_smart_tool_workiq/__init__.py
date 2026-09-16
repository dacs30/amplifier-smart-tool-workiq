"""Amplifier Smart Tool for Microsoft Work IQ."""

from .client import WorkIqMcpClient
from .data_plans import DataPlan, DataRequest
from .errors import WorkIqError
from .workflows import WorkIqService

__all__ = [
    "DataPlan",
    "DataRequest",
    "WorkIqError",
    "WorkIqMcpClient",
    "WorkIqService",
]
__version__ = "0.3.0"
