"""Integration tests: config flow, setup, sensors, statistics, service."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.viacqua.api import ViacquaAuthError, ViacquaError
from custom_components.viacqua.const import DOMAIN
from custom_components.viacqua.coordinator import water_statistic_id


@pytest.fixture(autouse=True)
def _env(recorder_mock, enable_custom_integrations):
    """Recorder must start before hass; then allow custom_components."""
    return


CREDS = {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    e = MockConfigEntry(domain=DOMAIN, unique_id="user@example.com", data=CREDS, title="Viacqua")
    e.add_to_hass(hass)
    return e


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_config_flow_success(
    hass: HomeAssistant, recorder_mock, mock_client: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Viacqua 19000001"
    assert result["data"] == CREDS
    assert result["result"].unique_id == "user@example.com"
    assert "closes the Home Assistant aiohttp session" not in caplog.text


@pytest.mark.parametrize(
    ("exc", "error"),
    [(ViacquaAuthError("bad"), "invalid_auth"), (ViacquaError("down"), "cannot_connect")],
)
async def test_config_flow_errors(
    hass: HomeAssistant, recorder_mock, mock_client: AsyncMock, exc, error
) -> None:
    mock_client.login.side_effect = exc
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    # recovers
    mock_client.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_config_flow_duplicate(
    hass: HomeAssistant, recorder_mock, mock_client: AsyncMock, entry
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_setup_and_sensors(
    hass: HomeAssistant, recorder_mock, mock_client: AsyncMock, entry
) -> None:
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    def st(name: str):
        state = hass.states.get(f"sensor.viacqua_19000001_{name}")
        assert state is not None, name
        return state

    reading = st("meter_reading")
    assert reading.state == "857"
    assert reading.attributes["unit_of_measurement"] == "m³"
    assert reading.attributes["reading_date"] == "2026-07-17"
    assert reading.attributes["self_reading_max"] == 905
    assert st("last_reading_date").state == "2026-07-17"
    assert st("last_period_consumption").state == "78"  # 857 - 779
    # 78 m³ over 26/01/2026 -> 17/07/2026 (172 days)
    assert float(st("daily_average_consumption").state) == pytest.approx(78000 / 172, abs=0.1)
    yearly = st("yearly_consumption")  # 136 m³ over 21/07/2025 -> 17/07/2026 (361 d)
    assert yearly.state == str(round(136 * 365 / 361))
    assert yearly.attributes["measured_m3"] == 136
    assert float(st("latest_bill_amount").state) == 212.65
    assert st("latest_bill_amount").attributes["number"] == "768076"
    assert st("latest_bill_due_date").state == "2026-09-14"
    assert float(st("outstanding_balance").state) == 159.49
    assert st("unpaid_bills").state == "1"
    assert st("contract_annual_volume").state == "84"
    assert st("contract_status").state == "Aperto"


async def test_statistics_imported(
    hass: HomeAssistant, recorder_mock, mock_client: AsyncMock, entry
) -> None:
    await _setup(hass, entry)
    await async_wait_recording_done(hass)
    stat_id = water_statistic_id("19000001")
    assert stat_id == "viacqua:water_19000001"
    stats = await recorder_mock.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.parse_datetime("2019-01-01T00:00:00+00:00"),
        None,
        {stat_id},
        "hour",
        None,
        {"state", "sum"},
    )
    rows = stats[stat_id]
    assert len(rows) == 19
    assert rows[0]["state"] == 0 and rows[0]["sum"] == 0  # Apertura 05/04/2019
    assert rows[-1]["state"] == 857 and rows[-1]["sum"] == 857
    sums = [r["sum"] for r in rows]
    assert sums == sorted(sums)


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, recorder_mock, mock_client: AsyncMock, entry
) -> None:
    mock_client.get_contracts.side_effect = ViacquaAuthError("expired")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_reauth_flow(hass: HomeAssistant, recorder_mock, mock_client: AsyncMock, entry) -> None:
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"


async def test_connection_error_retries(
    hass: HomeAssistant, recorder_mock, mock_client: AsyncMock, entry
) -> None:
    mock_client.get_readings.side_effect = ViacquaError("boom")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_submit_reading_service(
    hass: HomeAssistant, recorder_mock, mock_client: AsyncMock, entry
) -> None:
    await _setup(hass, entry)
    resp = await hass.services.async_call(
        DOMAIN,
        "submit_reading",
        {"config_entry_id": entry.entry_id, "reading": 870},
        blocking=True,
        return_response=True,
    )
    assert resp == {"message": "ok"}
    mock_client.submit_self_reading.assert_awaited_once_with(870, confirm=True)

    mock_client.submit_self_reading.side_effect = ViacquaError("out of range")
    with pytest.raises(HomeAssistantError, match="out of range"):
        await hass.services.async_call(
            DOMAIN,
            "submit_reading",
            {"config_entry_id": entry.entry_id, "reading": 2000},
            blocking=True,
        )


async def test_unload(hass: HomeAssistant, recorder_mock, mock_client: AsyncMock, entry) -> None:
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_redacted(
    hass: HomeAssistant, recorder_mock, mock_client: AsyncMock, entry
) -> None:
    from custom_components.viacqua.diagnostics import async_get_config_entry_diagnostics

    await _setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    for secret in ("secret", "user@example.com", "ROSSI", "VIA ROMA", "0502400000000001", "IT00X"):
        assert secret not in text, secret
