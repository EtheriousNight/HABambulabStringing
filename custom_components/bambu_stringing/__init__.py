"""Bambu Lab stringing and print failure detection via Mistral Vision.

Config flow based custom integration (spec section 5). One config entry per
printer; see SPEC.md for the overall architecture.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import (
    ACTION_PREFIX,
    ACTION_SUFFIX_IGNORE,
    ACTION_SUFFIX_PAUSE,
    DOMAIN,
    LOGGER,
    SERVICE_CHECK_NOW,
    SERVICE_MUTE_FOR_PRINT,
    SERVICE_RESET_DETECTION,
)
from . import dashboard
from . import version_check
from .runtime import PLATFORMS, PrinterRuntime

RuntimeStore = dict[str, PrinterRuntime]

_SERVICE_SCHEMA = cv.make_entity_service_schema({})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services and the notification action listener once."""
    _setup_store(hass)
    hass.services.async_register(
        DOMAIN, SERVICE_CHECK_NOW, _handle_check_now, schema=_SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_MUTE_FOR_PRINT, _handle_mute, schema=_SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESET_DETECTION, _handle_reset, schema=_SERVICE_SCHEMA
    )
    hass.bus.async_listen(
        "mobile_app_notification_action",
        lambda event: _handle_notification_action(hass, event),
    )
    await version_check.async_setup_version_check(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up one printer instance."""
    _setup_store(hass)
    runtime = PrinterRuntime(hass, entry)
    hass.data[DOMAIN]["runtimes"][entry.entry_id] = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await runtime.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(runtime.async_stop)
    hass.async_create_task(
        dashboard.async_setup_printer_view(hass, runtime)
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload one printer instance."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime: PrinterRuntime | None = hass.data[DOMAIN]["runtimes"].pop(
            entry.entry_id, None
        )
        if runtime is not None:
            await runtime.async_stop()
        await dashboard.async_remove_printer_view(hass, entry.entry_id)
    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Reload the entry when its options change (no HA restart needed)."""
    await hass.config_entries.async_reload(entry.entry_id)


# -- helpers --------------------------------------------------------------------


def _setup_store(hass: HomeAssistant) -> None:
    store = hass.data.setdefault(DOMAIN, {})
    store.setdefault("runtimes", {})


def _runtimes(hass: HomeAssistant) -> RuntimeStore:
    return hass.data[DOMAIN]["runtimes"]


def _entry_ids_for_call(hass: HomeAssistant, call: ServiceCall) -> list[str]:
    """Resolve targeted devices/entities to config entry ids."""
    runtimes = _runtimes(hass)
    found: list[str] = []

    for device_id in call.data.get(ATTR_DEVICE_ID, []) or []:
        registry = dr.async_get(hass)
        try:
            device = registry.async_get(device_id)
        except TypeError:
            device = registry.devices.get(device_id)
        if device is None:
            continue
        for domain, ident in device.identifiers:
            if domain == DOMAIN and ident in runtimes:
                found.append(ident)

    entity_registry = er.async_get(hass)
    for entity_id in call.data.get(ATTR_ENTITY_ID, []) or []:
        reg_entry = entity_registry.async_get(entity_id)
        if reg_entry is None or reg_entry.device_id is None:
            continue
        registry = dr.async_get(hass)
        try:
            device = registry.async_get(reg_entry.device_id)
        except TypeError:
            device = registry.devices.get(reg_entry.device_id)
        if device is None:
            continue
        for domain, ident in device.identifiers:
            if domain == DOMAIN and ident in runtimes:
                found.append(ident)

    return found


async def _handle_check_now(call: ServiceCall) -> None:
    hass = call.hass
    entry_ids = _entry_ids_for_call(hass, call)
    if not entry_ids:
        raise HomeAssistantError(
            "Kein Drucker der Stringing-Detection im Ziel gefunden"
        )
    for entry_id in entry_ids:
        _runtimes(hass)[entry_id].async_request_check_now()


async def _handle_mute(call: ServiceCall) -> None:
    hass = call.hass
    entry_ids = _entry_ids_for_call(hass, call)
    if not entry_ids:
        raise HomeAssistantError(
            "Kein Drucker der Stringing-Detection im Ziel gefunden"
        )
    for entry_id in entry_ids:
        _runtimes(hass)[entry_id].async_mute_for_print()


async def _handle_reset(call: ServiceCall) -> None:
    hass = call.hass
    entry_ids = _entry_ids_for_call(hass, call)
    if not entry_ids:
        raise HomeAssistantError(
            "Kein Drucker der Stringing-Detection im Ziel gefunden"
        )
    for entry_id in entry_ids:
        _runtimes(hass)[entry_id].reset_detection()


def _handle_notification_action(hass: HomeAssistant, event) -> None:
    """React to notification action buttons (Pause / Ignorieren)."""
    action = event.data.get("action", "")
    if not action.startswith(ACTION_PREFIX):
        return
    entry_id, _, suffix = action[len(ACTION_PREFIX):].rpartition("_")
    runtime = _runtimes(hass).get(entry_id)
    if runtime is None:
        LOGGER.debug("Notification action für unbekannte Instanz: %s", action)
        return
    if suffix == ACTION_SUFFIX_PAUSE:
        hass.async_create_task(runtime.async_pause_print())
    elif suffix == ACTION_SUFFIX_IGNORE:
        runtime.set_muted(True)
    else:
        LOGGER.debug("Unbekannte Notification action: %s", action)
