"""Binary sensors: stringing detected and print failure (spaghetti)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_LAYER_SHIFT_DETECTED,
    ATTR_PRINT_FAILURE,
    ATTR_STRINGING_DETECTED,
    ATTR_WARPING_DETECTED,
    DOMAIN,
)
from .entity import BambuStringingEntity
from .runtime import PrinterRuntime


class PrintFailureBinarySensor(BambuStringingEntity, BinarySensorEntity):
    """On when the spaghetti threshold was exceeded during this print."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="print_failure", translation_key="print_failure")

    @property
    def is_on(self) -> bool:
        return bool(self.data[ATTR_PRINT_FAILURE])


class StringingDetectedBinarySensor(BambuStringingEntity, BinarySensorEntity):
    """On when the stringing streak condition is satisfied (with hysteresis)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(
            runtime, key="stringing_detected", translation_key="stringing_detected"
        )

    @property
    def is_on(self) -> bool:
        return bool(self.data[ATTR_STRINGING_DETECTED])


class WarpingDetectedBinarySensor(BambuStringingEntity, BinarySensorEntity):
    """On when the warping streak condition is satisfied (with hysteresis)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(
            runtime, key="warping_detected", translation_key="warping_detected"
        )

    @property
    def is_on(self) -> bool:
        return bool(self.data[ATTR_WARPING_DETECTED])


class LayerShiftDetectedBinarySensor(BambuStringingEntity, BinarySensorEntity):
    """On when the layer shift threshold was exceeded during this print."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(
            runtime, key="layer_shift_detected", translation_key="layer_shift_detected"
        )

    @property
    def is_on(self) -> bool:
        return bool(self.data[ATTR_LAYER_SHIFT_DETECTED])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PrinterRuntime = hass.data[DOMAIN]["runtimes"][entry.entry_id]
    async_add_entities(
        [
            PrintFailureBinarySensor(runtime),
            StringingDetectedBinarySensor(runtime),
            WarpingDetectedBinarySensor(runtime),
            LayerShiftDetectedBinarySensor(runtime),
        ]
    )
