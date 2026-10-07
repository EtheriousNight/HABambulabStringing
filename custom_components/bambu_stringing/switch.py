"""Mute switch: silence notifications and autopause for the current print."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTR_MUTED, DOMAIN
from .entity import BambuStringingEntity
from .runtime import PrinterRuntime


class MuteSwitch(BambuStringingEntity, SwitchEntity):
    _attr_icon = "mdi:bell-off"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="mute", translation_key="mute")

    @property
    def is_on(self) -> bool:
        return bool(self.data[ATTR_MUTED])

    async def async_turn_on(self, **kwargs) -> None:
        self.runtime.set_muted(True)

    async def async_turn_off(self, **kwargs) -> None:
        self.runtime.set_muted(False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PrinterRuntime = hass.data[DOMAIN]["runtimes"][entry.entry_id]
    async_add_entities([MuteSwitch(runtime)])
