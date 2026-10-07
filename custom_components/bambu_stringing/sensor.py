"""Score and diagnostic sensors for one printer."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    ATTR_API_CALLS,
    ATTR_API_FAILURES,
    ATTR_DISCARDED,
    ATTR_EVENTS,
    ATTR_GRAB_FAILURES,
    ATTR_LAST_CHECK,
    ATTR_LAST_ERROR,
    ATTR_LAYER_SHIFT_SCORE,
    ATTR_OBSERVATIONS,
    ATTR_OTHER_DEFECTS,
    ATTR_PRINT_ID,
    ATTR_PRINT_RUNNING,
    ATTR_SPAGHETTI_SCORE,
    ATTR_STRINGING_SCORE,
    ATTR_WARPING_SCORE,
)
from .entity import BambuStringingEntity
from .runtime import PrinterRuntime


class _PipelineSensor(BambuStringingEntity, SensorEntity):
    """Base for all sensors of the pipeline."""


class StringingScoreSensor(_PipelineSensor):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:printer-3d-nozzle"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="stringing_score", translation_key="stringing_score")

    @property
    def native_value(self) -> int | None:
        return self.data[ATTR_STRINGING_SCORE]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "observations": self.data[ATTR_OBSERVATIONS],
            "other_defects": list(self.data[ATTR_OTHER_DEFECTS]),
        }


class SpaghettiScoreSensor(_PipelineSensor):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:printer-3d-alert"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="spaghetti_score", translation_key="spaghetti_score")

    @property
    def native_value(self) -> int | None:
        return self.data[ATTR_SPAGHETTI_SCORE]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "observations": self.data[ATTR_OBSERVATIONS],
            "other_defects": list(self.data[ATTR_OTHER_DEFECTS]),
        }


class WarpingScoreSensor(_PipelineSensor):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:printer-3d-nozzle"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="warping_score", translation_key="warping_score")

    @property
    def native_value(self) -> int | None:
        return self.data[ATTR_WARPING_SCORE]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "observations": self.data[ATTR_OBSERVATIONS],
            "other_defects": list(self.data[ATTR_OTHER_DEFECTS]),
        }


class LayerShiftScoreSensor(_PipelineSensor):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:layers"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(
            runtime, key="layer_shift_score", translation_key="layer_shift_score"
        )

    @property
    def native_value(self) -> int | None:
        return self.data[ATTR_LAYER_SHIFT_SCORE]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "observations": self.data[ATTR_OBSERVATIONS],
            "other_defects": list(self.data[ATTR_OTHER_DEFECTS]),
        }


class ApiCallsSensor(_PipelineSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:api"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="api_calls", translation_key="api_calls")

    @property
    def native_value(self) -> int:
        return self.data[ATTR_API_CALLS]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "api_failures": self.data[ATTR_API_FAILURES],
            "discarded_frames": self.data[ATTR_DISCARDED],
            "grab_failures": self.data[ATTR_GRAB_FAILURES],
            "last_error": self.data[ATTR_LAST_ERROR],
        }


class DetectedEventsSensor(_PipelineSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:alert-decagram"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="events", translation_key="events")

    @property
    def native_value(self) -> int:
        return self.data[ATTR_EVENTS]


class LastCheckSensor(_PipelineSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="last_check", translation_key="last_check")

    @property
    def native_value(self) -> str | None:
        return self.data[ATTR_LAST_CHECK]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "print_running": self.data[ATTR_PRINT_RUNNING],
            "print_id": self.data[ATTR_PRINT_ID],
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: PrinterRuntime = hass.data[DOMAIN]["runtimes"][entry.entry_id]
    async_add_entities(
        [
            StringingScoreSensor(runtime),
            SpaghettiScoreSensor(runtime),
            WarpingScoreSensor(runtime),
            LayerShiftScoreSensor(runtime),
            ApiCallsSensor(runtime),
            DetectedEventsSensor(runtime),
            LastCheckSensor(runtime),
        ]
    )
