"""Diagnostics for Viacqua (personal data redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import ViacquaConfigEntry

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    "holder",
    "customer_code",
    "pdr",
    "pde_code",
    "source_pde",
    "meter_serial",
    "Codice Nominativo",
    "Nominativo spedizione",
    "Indirizzo spedizione",
    "Indirizzo Fornitura",
    "Email Invio",
    "Domiciliazione",
    "PDR",
    "Indirizzo Immobile",
    "Foglio",
    "Particella",
    "SubAlterno",
    "Codice Catastale",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ViacquaConfigEntry
) -> dict[str, Any]:
    data = entry.runtime_data.data
    return async_redact_data(
        {
            "entry": dict(entry.data),
            "contract": data.contract.as_dict(),
            "contract_detail": data.contract_detail.as_dict(),
            "readings": [r.as_dict() for r in data.readings],
            "invoices": [i.as_dict() for i in data.invoices],
            "self_reading": data.self_reading.as_dict() if data.self_reading else None,
        },
        TO_REDACT,
    )
