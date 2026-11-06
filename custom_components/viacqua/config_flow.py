"""Config flow for Viacqua."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ViacquaAuthError, ViacquaClient, ViacquaError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)


class ViacquaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Viacqua."""

    VERSION = 1

    async def _validate(self, username: str, password: str) -> tuple[dict[str, str], str | None]:
        """Try to log in. Returns (errors, title)."""
        session = async_create_clientsession(self.hass)
        client = ViacquaClient(username, password, session=session)
        try:
            await client.login()
            contracts = await client.get_contracts()
        except ViacquaAuthError:
            return {"base": "invalid_auth"}, None
        except (ViacquaError, TimeoutError, OSError):
            _LOGGER.exception("Cannot connect to Viacqua")
            return {"base": "cannot_connect"}, None
        finally:
            await session.close()
        if not contracts:
            return {"base": "no_contracts"}, None
        return {}, f"Viacqua {contracts[0].contract_number}"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            errors, title = await self._validate(username, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_create_entry(
                    title=title or "Viacqua",
                    data={CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, _ = await self._validate(entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )
