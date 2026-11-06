"""Data update coordinator for Viacqua."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import VolumeConverter

from .api import (
    Contract,
    ContractDetail,
    Invoice,
    MeterReading,
    SelfReadingInfo,
    ViacquaAuthError,
    ViacquaClient,
    ViacquaError,
)
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type ViacquaConfigEntry = ConfigEntry[ViacquaCoordinator]


@dataclass
class ViacquaData:
    """Everything fetched in one refresh."""

    contract: Contract
    contract_detail: ContractDetail
    readings: list[MeterReading]  # oldest first
    invoices: list[Invoice]  # newest first
    self_reading: SelfReadingInfo | None


def water_statistic_id(contract_number: str) -> str:
    """External statistic id holding the cumulative m³ for a contract."""
    return f"{DOMAIN}:water_{contract_number}".lower()


def build_water_statistics(readings: list[MeterReading]) -> list[StatisticData]:
    """Turn meter readings (oldest first) into cumulative statistics rows.

    `state` is the meter index, `sum` is a monotonic total that survives meter
    replacements (index restarting from a lower value / new serial).
    """
    rows: list[StatisticData] = []
    total = 0.0
    prev: MeterReading | None = None
    by_start: dict[datetime, StatisticData] = {}
    for r in readings:
        if prev is not None:
            if r.meter_serial != prev.meter_serial or r.reading_m3 < prev.reading_m3:
                total += r.reading_m3  # new meter: count from its own zero
            else:
                total += r.reading_m3 - prev.reading_m3
        else:
            total = float(r.reading_m3)
        prev = r
        start = dt_util.as_utc(
            datetime.combine(r.reading_date, time(0), tzinfo=dt_util.get_default_time_zone())
        )
        by_start[start] = StatisticData(start=start, state=float(r.reading_m3), sum=total)
    rows = [by_start[k] for k in sorted(by_start)]
    return rows


class ViacquaCoordinator(DataUpdateCoordinator[ViacquaData]):
    """Fetch data from the Viacqua portal."""

    config_entry: ViacquaConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ViacquaConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = ViacquaClient(
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            session=async_create_clientsession(hass),
        )

    async def _async_update_data(self) -> ViacquaData:
        try:
            contracts = await self.client.get_contracts()
            if not contracts:
                raise UpdateFailed("No contracts found on the Viacqua account")
            contract = contracts[0]
            detail = await self.client.get_contract_detail(contract)
            readings = await self.client.get_readings()
            invoices = await self.client.get_invoices()
            try:
                self_reading: SelfReadingInfo | None = await self.client.get_self_reading_info()
            except ViacquaError as err:  # not essential
                _LOGGER.debug("Self reading info unavailable: %s", err)
                self_reading = None
        except ViacquaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (ViacquaError, TimeoutError, OSError) as err:
            raise UpdateFailed(f"Error talking to Viacqua: {err}") from err

        readings = sorted(readings, key=lambda r: r.reading_date)
        data = ViacquaData(
            contract=contract,
            contract_detail=detail,
            readings=readings,
            invoices=invoices,
            self_reading=self_reading,
        )
        self._import_statistics(data)
        return data

    def _import_statistics(self, data: ViacquaData) -> None:
        """(Re)import the whole reading history; rows are upserted by start time."""
        stats = build_water_statistics(data.readings)
        if not stats:
            return
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Viacqua acqua {data.contract.contract_number}",
            source=DOMAIN,
            statistic_id=water_statistic_id(data.contract.contract_number),
            unit_class=VolumeConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        )
        async_add_external_statistics(self.hass, metadata, stats)
