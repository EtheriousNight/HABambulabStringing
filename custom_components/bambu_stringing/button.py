"""Device page action buttons: pause, resume, stop and check-now."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import BambuStringingEntity
from .runtime import PrinterRuntime


class _RuntimeButton(BambuStringingEntity, ButtonEntity):
    async def async_press(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class PauseButton(_RuntimeButton):
    _attr_icon = "mdi:pause"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="pause", translation_key="pause")

    async def async_press(self) -> None:
        await self.runtime.async_pause_print()


class ResumeButton(_RuntimeButton):
    _attr_icon = "mdi:play"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="resume", translation_key="resume")

    async def async_press(self) -> None:
        await self.runtime.async_resume_print()


class StopButton(_RuntimeButton):
    _attr_icon = "mdi:stop"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="stop", translation_key="stop")

    async def async_press(self) -> None:
        await self.runtime.async_stop_print()


class CheckNowButton(_RuntimeButton):
    _attr_icon = "mdi:eye-check"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="check_now", translation_key="check_now")

    async def async_press(self) -> None:
        self.runtime.async_request_check_now()


class ResetButton(_RuntimeButton):
    _attr_icon = "mdi:restart"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="reset", translation_key="reset")

    async def async_press(self) -> None:
        self.runtime.reset_detection()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PrinterRuntime = hass.data[DOMAIN]["runtimes"][entry.entry_id]
    async_add_entities(
        [
            PauseButton(runtime),
            ResumeButton(runtime),
            StopButton(runtime),
            CheckNowButton(runtime),
            ResetButton(runtime),
        ]
    )
