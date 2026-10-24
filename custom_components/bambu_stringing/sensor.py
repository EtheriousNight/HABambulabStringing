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
    ATTR_BENCHMARK_MODELS,
    ATTR_BENCHMARK_RECOMMENDED,
    ATTR_BENCHMARK_THRESHOLDS,
    ATTR_BENCHMARK_TIMESTAMP,
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


class BenchmarkModelSensor(_PipelineSensor):
    """Zeigt das empfohlene Modell aus dem Benchmark mit Modell-Vergleich."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:trophy-award"

    def __init__(self, runtime: PrinterRuntime) -> None:
        super().__init__(runtime, key="benchmark_model", translation_key="benchmark_model")

    @property
    def native_value(self) -> str | None:
        """Name des empfohlenen Modells."""
        return self.data.get(ATTR_BENCHMARK_RECOMMENDED)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Modell-Vergleich mit Accuracy, Kosten, Latenz + Threshold-Empfehlungen."""
        models = self.data.get(ATTR_BENCHMARK_MODELS, [])
        timestamp = self.data.get(ATTR_BENCHMARK_TIMESTAMP)
        thresholds = self.data.get(ATTR_BENCHMARK_THRESHOLDS) or {}

        # Formatiere Modelle für bessere Lesbarkeit (inkl. Schwellwerte pro Modell)
        model_list = []
        for m in models:
            model_list.append({
                "model": m.get("model", "unknown"),
                "accuracy_pct": m.get("accuracy_pct", 0),
                "accuracy_corrected_pct": m.get("accuracy_corrected_pct", 0),
                "avg_latency_ms": m.get("avg_latency_ms", 0),
                "cost_per_scan_cents": m.get("cost_per_scan_cents", 0),
                "value_score": m.get("value_score", 0),
                "reliability_score": m.get("reliability_score", 0),
                "critical_defect_score": m.get("critical_defect_score", 0),
                "critical_bonus": m.get("critical_bonus", 0),
                "category_accuracy": m.get("category_accuracy", {}),
                "recommended_thresholds": m.get("recommended_thresholds", {}),
            })

        # Bestimme Gewinner pro Kategorie
        best_reliability = max(model_list, key=lambda m: m["reliability_score"])["model"] if model_list else None
        best_critical = max(model_list, key=lambda m: m["critical_defect_score"])["model"] if model_list else None

        return {
            "benchmark_timestamp": timestamp,
            "model_count": len(model_list),
            "models": model_list,
            "best_accuracy": max(model_list, key=lambda m: m["accuracy_pct"])["model"] if model_list else None,
            "best_value": max(model_list, key=lambda m: m["value_score"])["model"] if model_list else None,
            "best_reliability": best_reliability,
            "best_critical_defects": best_critical,
            "fastest": min(model_list, key=lambda m: m["avg_latency_ms"])["model"] if model_list else None,
            "cheapest": min(model_list, key=lambda m: m["cost_per_scan_cents"])["model"] if model_list else None,
            # Threshold-Empfehlungen des empfohlenen Modells
            "recommended_thresholds": {
                "stringing_threshold": thresholds.get("stringing_threshold", 55),
                "spaghetti_threshold": thresholds.get("spaghetti_threshold", 70),
                "warping_threshold": thresholds.get("warping_threshold", 60),
                "layer_shift_threshold": thresholds.get("layer_shift_threshold", 70),
                "min_confidence": thresholds.get("min_confidence", 0.6),
                "smoothing_alpha": thresholds.get("smoothing_alpha", 0.3),
                "stringing_streak": thresholds.get("stringing_streak", 3),
            },
            "threshold_hint": (
                f"Empfohlen: Stringing≥{thresholds.get('stringing_threshold', 55)}, "
                f"Spaghetti≥{thresholds.get('spaghetti_threshold', 70)}, "
                f"Warping≥{thresholds.get('warping_threshold', 60)}, "
                f"LayerShift≥{thresholds.get('layer_shift_threshold', 70)}"
            ),
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
            BenchmarkModelSensor(runtime),
        ]
    )
