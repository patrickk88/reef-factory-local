"""Actions for Level keeper pump operations and Reef Flare programming.

Actions that run the pump (manual refill, calibration run, filling the hose)
only work when the option "Allow pump actions" is enabled for that device.
Stop actions are always allowed.
"""
from __future__ import annotations

import asyncio
import time

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from . import protocol as pr
from .const import CONF_ALLOW_PUMP_ACTIONS, CONF_CLOUD, DOMAIN, MAX_MANUAL_REFILL_ML

ATTR_DEVICE_ID = "device_id"
BASE = vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string})


_WRONG_DEVICE = {pr.DEVICE_LEVEL_KEEPER: "not_level_keeper", pr.DEVICE_FLARE: "not_flare",
                 pr.DEVICE_FEEDER: "not_feeder", pr.DEVICE_DOSING_PUMP: "not_dosing_pump"}


def _coordinator(hass: HomeAssistant, call: ServiceCall, pump: bool = False,
                 kind: str = pr.DEVICE_LEVEL_KEEPER):
    device = dr.async_get(hass).async_get(call.data[ATTR_DEVICE_ID])
    if device is not None:
        # HA >= 2026.x: one config entry per device (config_entries is deprecated)
        entry_ids = [device.config_entry_id] if getattr(device, "config_entry_id", None) else list(device.config_entries)
        for entry_id in entry_ids:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
                continue
            coordinator = entry.runtime_data
            if entry.data.get(CONF_CLOUD):  # cloud replacement: one entry, many devices
                serial = next((v for d, v in device.identifiers if d == DOMAIN), None)
                coordinator = coordinator.coordinators.get(serial)
                if coordinator is None:
                    continue
            if pr.device_type(coordinator.serial) != kind:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key=_WRONG_DEVICE[kind])
            if pump and not entry.options.get(CONF_ALLOW_PUMP_ACTIONS, False):
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="pump_actions_disabled")
            return coordinator
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_device")


async def _send(coordinator, *frames: bytes) -> None:
    try:
        for frame in frames:
            await coordinator.client.async_send(frame)
    except ConnectionError as err:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_connected") from err


def _invalid(reason: str) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_value",
                                  translation_placeholders={"reason": reason})


async def _wait_for(coordinator, predicate, timeout: float = 10.0) -> dict:
    """Wait until pushed data satisfies predicate (device answers mode/program changes)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = coordinator.data or {}
        if predicate(data):
            return data
        await asyncio.sleep(0.25)
    raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_answer")


def _program_index(data: dict, name: str | None) -> int:
    if name is None:
        return data.get("program_index", 0)
    names = data.get("programs") or []
    if name not in names:
        raise _invalid(f"unknown program {name!r}")
    return names.index(name)


def _points(raw) -> list[dict]:
    try:
        return pr.normalize_flare_points(raw)
    except (KeyError, TypeError, ValueError) as err:
        raise _invalid(str(err)) from err


def async_setup_services(hass: HomeAssistant) -> None:
    async def manual_refill(call: ServiceCall) -> None:
        c = _coordinator(hass, call, pump=True)
        await _send(c, pr.frame_lk_manual_refill_start(c.serial, call.data["amount_ml"]))

    async def manual_refill_stop(call: ServiceCall) -> None:
        c = _coordinator(hass, call)
        await _send(c, pr.frame_lk_manual_refill_stop(c.serial))

    async def calibration_start(call: ServiceCall) -> None:
        c = _coordinator(hass, call, pump=True)
        await _send(c, pr.frame_lk_calibration_time(c.serial, call.data["duration_s"]),
                    pr.frame_lk_calibration_start(c.serial))

    async def calibration_value(call: ServiceCall) -> None:
        c = _coordinator(hass, call)
        frames = [pr.frame_lk_calibration_value(c.serial, call.data["measured_ml"])]
        if reminder := call.data.get("reminder"):
            frames.append(pr.frame_lk_calibration_reminder(c.serial, reminder))
        await _send(c, *frames)

    async def calibration_stop(call: ServiceCall) -> None:
        c = _coordinator(hass, call)
        await _send(c, pr.frame_lk_calibration_stop(c.serial))

    async def fill_hose_start(call: ServiceCall) -> None:
        c = _coordinator(hass, call, pump=True)
        await _send(c, pr.frame_lk_circuit_start(c.serial))

    async def fill_hose_stop(call: ServiceCall) -> None:
        c = _coordinator(hass, call)
        await _send(c, pr.frame_lk_circuit_stop(c.serial))

    # --- Reef Flare -----------------------------------------------------------
    def _flare(call: ServiceCall):
        return _coordinator(hass, call, kind=pr.DEVICE_FLARE)

    async def flare_program_set(call: ServiceCall) -> None:
        c = _flare(call)
        data = c.data or {}
        if data.get("mode") != "program":
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="flare_not_program")
        index = _program_index(data, call.data.get("program"))
        points = _points(call.data["points"])
        if index != data.get("program_index"):
            # writing another program would first switch the light to it - only the active program
            # was confirmed on hardware, so select the program first (select entity), then write it
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="flare_not_active_program")
        intensity = call.data.get("intensity")
        if intensity is None:
            intensity = 100 if data.get("intensity") is None else data["intensity"]
        await _send(c, pr.frame_rf_precise_update(c.serial, index, data.get("program_time_raw") or 0,
                                                  points, intensity))

    async def flare_acclimation_start(call: ServiceCall) -> None:
        c = _flare(call)
        await _send(c, pr.frame_rf_acclimation(c.serial, call.data["days"], call.data["start_pct"],
                                               call.data["end_pct"]))

    async def flare_acclimation_stop(call: ServiceCall) -> None:
        c = _flare(call)
        await _send(c, pr.frame_rf_acclimation(c.serial))

    # --- Smart feeder (cloud replacement) --------------------------------------
    def _feeder(call: ServiceCall):
        return _coordinator(hass, call, kind=pr.DEVICE_FEEDER)

    async def feeder_feed(call: ServiceCall) -> None:
        c = _feeder(call)
        await _send(c, pr.frame_sf_feed(c.serial, call.data["rotations"], c.device.join_id))

    async def feeder_set_schedule(call: ServiceCall) -> None:
        c = _feeder(call)
        try:
            frame = pr.frame_sf_set_schedule(c.serial, call.data["entries"], c.device.join_id)
        except (KeyError, TypeError, ValueError) as err:
            raise _invalid(str(err)) from err
        await _send(c, frame)

    # --- Dosing pump Pro X4 (cloud replacement, opt-in pump actions of the cloud entry) ------------
    def _dosing(call: ServiceCall):
        return _coordinator(hass, call, pump=True, kind=pr.DEVICE_DOSING_PUMP)

    async def dosing_pump_dose(call: ServiceCall) -> None:
        c = _dosing(call)
        await _send(c, pr.frame_dp_manual_dose(c.serial, call.data["channel"], call.data["ml"], c.device.join_id))

    async def dosing_pump_set_schedule(call: ServiceCall) -> None:
        c = _dosing(call)
        try:
            frame = pr.frame_dp_set_schedule(c.serial, call.data["channel"], call.data["entries"], c.device.join_id)
        except (KeyError, TypeError, ValueError) as err:
            raise _invalid(str(err)) from err
        await _send(c, frame)

    reg = hass.services.async_register
    channel = vol.All(vol.Coerce(int), vol.Range(min=1, max=pr.DOSING_CHANNELS))
    reg(DOMAIN, "dosing_pump_dose", dosing_pump_dose, BASE.extend({
        vol.Required("channel"): channel,
        vol.Required("ml"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=500)),
    }))
    reg(DOMAIN, "dosing_pump_set_schedule", dosing_pump_set_schedule, BASE.extend({
        vol.Required("channel"): channel,
        vol.Required("entries"): vol.All(cv.ensure_list, [dict]),
    }))
    reg(DOMAIN, "feeder_feed", feeder_feed, BASE.extend(
        {vol.Optional("rotations", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=pr.FEEDER_MAX_ROTATIONS))}))
    reg(DOMAIN, "feeder_set_schedule", feeder_set_schedule, BASE.extend(
        {vol.Required("entries"): vol.All(cv.ensure_list, [dict])}))
    pct = vol.All(vol.Coerce(int), vol.Range(min=0, max=100))
    reg(DOMAIN, "flare_program_set", flare_program_set, BASE.extend({
        vol.Optional("program"): cv.string,
        vol.Required("points"): vol.All(cv.ensure_list, [dict]),
        vol.Optional("intensity"): pct,
    }))
    reg(DOMAIN, "flare_acclimation_start", flare_acclimation_start, BASE.extend({
        vol.Required("days"): vol.All(vol.Coerce(int), vol.Range(min=2, max=30)),
        vol.Required("start_pct"): pct, vol.Required("end_pct"): pct,
    }))
    reg(DOMAIN, "flare_acclimation_stop", flare_acclimation_stop, BASE)

    reg(DOMAIN, "manual_refill", manual_refill, BASE.extend(
        {vol.Required("amount_ml"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_MANUAL_REFILL_ML))}))
    reg(DOMAIN, "manual_refill_stop", manual_refill_stop, BASE)
    reg(DOMAIN, "calibration_start", calibration_start, BASE.extend(
        {vol.Optional("duration_s", default=10): vol.All(vol.Coerce(int), vol.Range(min=10, max=255))}))
    reg(DOMAIN, "calibration_value", calibration_value, BASE.extend({
        vol.Required("measured_ml"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100000)),
        vol.Optional("reminder"): vol.In(list(pr.LK_REMINDER)),
    }))
    reg(DOMAIN, "calibration_stop", calibration_stop, BASE)
    reg(DOMAIN, "fill_hose_start", fill_hose_start, BASE)
    reg(DOMAIN, "fill_hose_stop", fill_hose_stop, BASE)
