"""Sensors for Viacqua."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Invoice, MeterReading
from .const import DOMAIN, MANUFACTURER
from .coordinator import ViacquaConfigEntry, ViacquaCoordinator, ViacquaData, water_statistic_id

PARALLEL_UPDATES = 0


def _last_reading(d: ViacquaData) -> MeterReading | None:
    return d.readings[-1] if d.readings else None


def _latest_invoice(d: ViacquaData) -> Invoice | None:
    return max(d.invoices, key=lambda i: i.issue_date) if d.invoices else None


def _daily_average_l(d: ViacquaData) -> float | None:
    """Litres/day between the last two readings."""
    if len(d.readings) < 2:
        return None
    prev, last = d.readings[-2], d.readings[-1]
    days = (last.reading_date - prev.reading_date).days
    if days <= 0 or last.reading_m3 < prev.reading_m3:
        return None
    return round((last.reading_m3 - prev.reading_m3) * 1000 / days, 1)


def _yearly_base(d: ViacquaData) -> MeterReading | None:
    """Reading closest to one year before the latest one (same meter)."""
    last = _last_reading(d)
    if last is None:
        return None
    candidates = [
        r
        for r in d.readings
        if r.meter_serial == last.meter_serial and 300 <= (last.reading_date - r.reading_date).days <= 430
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda r: abs((last.reading_date - r.reading_date).days - 365))


def _yearly_consumption(d: ViacquaData) -> int | None:
    """m³ per year, from the readings ~12 months apart, normalised to 365 days."""
    last, base = _last_reading(d), _yearly_base(d)
    if last is None or base is None:
        return None
    days = (last.reading_date - base.reading_date).days
    return round((last.reading_m3 - base.reading_m3) * 365 / days)


def _yearly_attrs(d: ViacquaData) -> dict[str, Any]:
    last, base = _last_reading(d), _yearly_base(d)
    if last is None or base is None:
        return {}
    return {
        "from": base.reading_date.isoformat(),
        "to": last.reading_date.isoformat(),
        "measured_m3": last.reading_m3 - base.reading_m3,
    }


def _invoice_attrs(i: Invoice | None) -> dict[str, Any]:
    if i is None:
        return {}
    return {
        "number": i.number,
        "period": i.period,
        "issue_date": i.issue_date.isoformat(),
        "due_date": i.due_date.isoformat() if i.due_date else None,
        "paid": i.paid,
        "outstanding": float(i.outstanding),
    }


def _reading_attrs(d: ViacquaData) -> dict[str, Any]:
    r = _last_reading(d)
    attrs: dict[str, Any] = {"statistic_id": water_statistic_id(d.contract.contract_number)}
    if r is not None:
        attrs.update(
            {
                "reading_date": r.reading_date.isoformat(),
                "reading_type": r.reading_type,
                "meter_serial": r.meter_serial,
                "pdr": r.pdr,
            }
        )
    if d.self_reading is not None:
        attrs["self_reading_min"] = d.self_reading.allowed_min_m3
        attrs["self_reading_max"] = d.self_reading.allowed_max_m3
    return attrs


@dataclass(frozen=True, kw_only=True)
class ViacquaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ViacquaData], Any]
    attrs_fn: Callable[[ViacquaData], dict[str, Any]] | None = None


def _dec(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


SENSORS: tuple[ViacquaSensorDescription, ...] = (
    ViacquaSensorDescription(
        key="meter_reading",
        translation_key="meter_reading",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=lambda d: r.reading_m3 if (r := _last_reading(d)) else None,
        attrs_fn=_reading_attrs,
    ),
    ViacquaSensorDescription(
        key="last_reading_date",
        translation_key="last_reading_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: r.reading_date if (r := _last_reading(d)) else None,
    ),
    ViacquaSensorDescription(
        key="last_period_consumption",
        translation_key="last_period_consumption",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=lambda d: (
            d.readings[-1].reading_m3 - d.readings[-2].reading_m3
            if len(d.readings) > 1 and d.readings[-1].meter_serial == d.readings[-2].meter_serial
            else None
        ),
        attrs_fn=lambda d: (
            {"from": d.readings[-2].reading_date.isoformat(), "to": d.readings[-1].reading_date.isoformat()}
            if len(d.readings) > 1
            else {}
        ),
    ),
    ViacquaSensorDescription(
        key="daily_average",
        translation_key="daily_average",
        native_unit_of_measurement="L/d",
        suggested_display_precision=0,
        value_fn=_daily_average_l,
    ),
    ViacquaSensorDescription(
        key="yearly_consumption",
        translation_key="yearly_consumption",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=_yearly_consumption,
        attrs_fn=_yearly_attrs,
    ),
    ViacquaSensorDescription(
        key="latest_invoice_amount",
        translation_key="latest_invoice_amount",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        value_fn=lambda d: _dec(i.amount) if (i := _latest_invoice(d)) else None,
        attrs_fn=lambda d: _invoice_attrs(_latest_invoice(d)),
    ),
    ViacquaSensorDescription(
        key="latest_invoice_due_date",
        translation_key="latest_invoice_due_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: i.due_date if (i := _latest_invoice(d)) else None,
    ),
    ViacquaSensorDescription(
        key="outstanding_balance",
        translation_key="outstanding_balance",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        value_fn=lambda d: float(sum((i.outstanding for i in d.invoices), Decimal(0))),
        attrs_fn=lambda d: {
            "unpaid": [_invoice_attrs(i) for i in d.invoices if i.outstanding > 0]
        },
    ),
    ViacquaSensorDescription(
        key="unpaid_invoices",
        translation_key="unpaid_invoices",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: sum(1 for i in d.invoices if i.outstanding > 0),
    ),
    ViacquaSensorDescription(
        key="annual_volume",
        translation_key="annual_volume",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int_or_none(d.contract_detail.contract.get("Volume Annuale")),
    ),
    ViacquaSensorDescription(
        key="contract_status",
        translation_key="contract_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.contract_detail.contract.get("Stato contratto"),
        attrs_fn=lambda d: {
            k: d.contract_detail.contract.get(k)
            for k in ("Periodicità fatturazione", "Uso", "Mercato", "Modalità pagamento")
        },
    ),
)


def _int_or_none(v: str | None) -> int | None:
    try:
        return int(v) if v else None
    except ValueError:
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViacquaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ViacquaSensor(coordinator, desc) for desc in SENSORS)


class ViacquaSensor(CoordinatorEntity[ViacquaCoordinator], SensorEntity):
    """A Viacqua sensor."""

    _attr_has_entity_name = True
    entity_description: ViacquaSensorDescription

    def __init__(self, coordinator: ViacquaCoordinator, description: ViacquaSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        contract = coordinator.data.contract.contract_number
        self._attr_unique_id = f"{contract}_{description.key}"
        serial = coordinator.data.readings[-1].meter_serial if coordinator.data.readings else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, contract)},
            name=f"Viacqua {contract}",
            manufacturer=MANUFACTURER,
            model="Contatore acqua",
            serial_number=serial,
            configuration_url="https://sol.viacqua.it/CRM_20_Multi/Ingresso_Home.aspx",
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
