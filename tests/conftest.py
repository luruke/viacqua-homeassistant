"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.viacqua.api import parsers

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIX / f"{name}.html").read_text()


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """A ViacquaClient whose methods return data parsed from the fixtures."""
    with (
        patch("custom_components.viacqua.coordinator.ViacquaClient", autospec=True) as cls,
        patch("custom_components.viacqua.config_flow.ViacquaClient", new=cls),
    ):
        client = cls.return_value
        client.login.return_value = None
        client.get_contracts.return_value = parsers.parse_contracts(load("contratti"))
        client.get_contract_detail.return_value = parsers.parse_contract_detail(
            load("contratto_dettaglio")
        )
        client.get_readings.return_value = parsers.parse_readings(
            load("consumi_p1")
        ) + parsers.parse_readings(load("consumi_p2"))
        client.get_invoices.return_value = parsers.parse_invoices(
            load("bollette_p1"), 1
        ) + parsers.parse_invoices(load("bollette_p3"), 3)
        client.get_self_reading_info.return_value = parsers.parse_self_reading(
            load("autolettura")
        )
        client.submit_self_reading.return_value = "ok"
        yield client
