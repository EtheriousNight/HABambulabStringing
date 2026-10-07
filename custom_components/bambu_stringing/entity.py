"""Shared entity base: device info and unique ids per printer instance."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DOMAIN
from .runtime import PrinterRuntime


class BambuStringingEntity(CoordinatorEntity):
    """Base entity bound to one printer runtime and its device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        runtime: PrinterRuntime,
        *,
        key: str,
        translation_key: str,
    ) -> None:
        super().__init__(runtime.coordinator)
        self.runtime = runtime
        entry: ConfigEntry = runtime.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = translation_key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME, entry.entry_id),
            via_device=runtime.via_device,
        )

    @property
    def data(self) -> dict[str, Any]:
        return self.coordinator.data
