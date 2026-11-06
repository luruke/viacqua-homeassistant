"""The Viacqua (Vicenza water utility) integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import ViacquaError
from .const import ATTR_CONFIG_ENTRY_ID, ATTR_READING, DOMAIN, SERVICE_SUBMIT_READING
from .coordinator import ViacquaConfigEntry, ViacquaCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SUBMIT_READING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_READING): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services."""

    async def _submit_reading(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
        if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
        coordinator: ViacquaCoordinator = entry.runtime_data
        try:
            message = await coordinator.client.submit_self_reading(
                call.data[ATTR_READING], confirm=True
            )
        except ViacquaError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()
        return {"message": message}

    hass.services.async_register(
        DOMAIN,
        SERVICE_SUBMIT_READING,
        _submit_reading,
        schema=SUBMIT_READING_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ViacquaConfigEntry) -> bool:
    """Set up Viacqua from a config entry."""
    coordinator = ViacquaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ViacquaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
