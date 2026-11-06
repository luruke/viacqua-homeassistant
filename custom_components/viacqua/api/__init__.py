"""Unofficial client for the Viacqua (Vicenza) customer portal."""

from .client import ViacquaAuthError, ViacquaClient, ViacquaError
from .models import (
    Activity,
    Contract,
    ContractDetail,
    Customer,
    Invoice,
    MeterReading,
    SelfReadingInfo,
)

__all__ = [
    "Activity",
    "Contract",
    "ContractDetail",
    "Customer",
    "Invoice",
    "MeterReading",
    "SelfReadingInfo",
    "ViacquaAuthError",
    "ViacquaClient",
    "ViacquaError",
]
