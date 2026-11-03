"""Config flow: only the IP address is needed, the serial is read from the device."""
from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import protocol as pr
from .client import async_probe
from .cloud import MODE_LOCAL, MODE_PASSTHROUGH
from .const import (
    CLOUD_UNIQUE_ID, CONF_ALLOW_PUMP_ACTIONS, CONF_CLOUD, CONF_CLOUD_MODE, CONF_SERIAL, CONF_UPSTREAM_IPS, DOMAIN,
)


class ReefFactoryLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ReefOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["device", "cloud"])

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Cloud replacement: serves devices that only talk to api.reeffactory.com (one entry)."""
        await self.async_set_unique_id(CLOUD_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(
                title="Cloud replacement", data={CONF_CLOUD: True},
                options={CONF_CLOUD_MODE: user_input[CONF_CLOUD_MODE], CONF_UPSTREAM_IPS: ""},
            )
        return self.async_show_form(
            step_id="cloud",
            data_schema=vol.Schema({
                vol.Required(CONF_CLOUD_MODE, default=MODE_PASSTHROUGH): vol.In({
                    MODE_PASSTHROUGH: "passthrough", MODE_LOCAL: "local"}),
            }),
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                info = await async_probe(async_get_clientsession(self.hass), host)
            except (TimeoutError, aiohttp.ClientError, ConnectionError, OSError):
                errors["base"] = "cannot_connect"
            else:
                serial = info["serial"]
                kind = info["device_type"]
                if kind is None:
                    errors["base"] = "unsupported_device"
                    placeholders["serial"] = serial
                else:
                    await self.async_set_unique_id(serial)
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                    return self.async_create_entry(
                        title=f"{pr.MODEL_NAME[kind]} {serial[-4:]}",
                        data={CONF_HOST: host, CONF_SERIAL: serial},
                    )
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
            description_placeholders=placeholders,
        )


class ReefOptionsFlow(OptionsFlow):
    """Device entries: pump actions off by default. Cloud entry: mode and cloud addresses."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_CLOUD):
            return await self.async_step_cloud(user_input)
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_ALLOW_PUMP_ACTIONS, False)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required(CONF_ALLOW_PUMP_ACTIONS, default=current): bool}),
        )

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="cloud",
            data_schema=vol.Schema({
                vol.Required(CONF_CLOUD_MODE, default=opts.get(CONF_CLOUD_MODE, MODE_PASSTHROUGH)): vol.In({
                    MODE_PASSTHROUGH: "passthrough", MODE_LOCAL: "local"}),
                vol.Optional(CONF_UPSTREAM_IPS, default=opts.get(CONF_UPSTREAM_IPS, "")): str,
            }),
        )
