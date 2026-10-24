"""Smoke test for the HA-facing modules with stubbed homeassistant APIs.

The real ``homeassistant`` package is not installable here; these stubs are
deliberately minimal and only verify that the integration modules import
cleanly and behave at a basic level (runtime wiring, entities, config flow).
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# homeassistant stubs (must exist before importing the integration)
# ---------------------------------------------------------------------------


def _module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def _callback(fn):
    fn.hass = None
    return fn


class HomeAssistantError(Exception):
    pass


class ServiceCall:
    def __init__(self, hass, data):
        self.hass = hass
        self.data = data


class _Bus:
    def async_listen(self, event_type, fn):
        pass


class _Services:
    def __init__(self):
        self.registered = {}
        self.services = {
            "notify": {
                "mobile_app_handy": {"name": "Handy"},
                "mobile_app_tablet": {"name": "Tablet"},
                "persistent_notification": {"name": "Persist"},
            }
        }

    def has_service(self, domain, service):
        return (domain, service) in self.registered

    def async_register(self, domain, service, handler, schema=None):
        self.registered[(domain, service)] = handler

    def async_services(self):
        return self.services


class _States:
    def __init__(self):
        self._states = {}

    def get(self, entity_id):
        return self._states.get(entity_id)

    def set(self, entity_id, state, attributes=None):
        self._states[entity_id] = types.SimpleNamespace(
            state=state, attributes=attributes or {}
        )


class HomeAssistant:
    def __init__(self, config_dir):
        self.config = types.SimpleNamespace(config_dir=config_dir)
        self.data = {}
        self.bus = _Bus()
        self.services = _Services()
        self.states = _States()

    def async_create_task(self, coro):
        if not hasattr(self, "_loop"):
            self._loop = asyncio.new_event_loop()
        task = self._loop.create_task(coro)
        self._loop.run_until_complete(task)
        return task


class ConfigEntry:
    def __init__(self, data=None, options=None, entry_id="abc123def"):
        self.data = data or {}
        self.options = options or {}
        self.entry_id = entry_id
        self._unload = []

    def async_on_unload(self, fn):
        self._unload.append(fn)

    def add_update_listener(self, fn):
        return lambda entry: None


class Platform:
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    SWITCH = "switch"


class EntityCategory:
    DIAGNOSTIC = "diagnostic"
    CONFIG = "config"


class DataUpdateCoordinator:
    def __init__(self, hass, logger, name=None, **kwargs):
        self.hass = hass
        self.name = name
        self.data = {}

    def __class_getitem__(cls, item):
        return cls

    async def _async_update_data(self):
        return self.data

    def async_set_updated_data(self, data):
        self.data = data
        self.last_update_success = True


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator


class DeviceInfo(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class _DeviceRegistry:
    def __init__(self):
        self.devices = {}

    def async_get(self, device_id):
        return self.devices.get(device_id)


def _device_registry_async_get(hass):
    return hass.data.setdefault("_dr", _DeviceRegistry())


class _EntityRegistry:
    def async_get(self, entity_id):
        return None


class _ClientSession:
    pass


class CameraImage:
    def __init__(self, content):
        self.content = content


def _camera_async_get_image(hass, entity_id, timeout=10):
    raise HomeAssistantError("no camera in smoke test")


class _ConfigFlowMeta(type):
    def __new__(mcs, name, bases, namespace, **kwargs):
        return super().__new__(mcs, name, bases, namespace)


class ConfigFlow(metaclass=_ConfigFlowMeta):
    def __init__(self):
        self.hass = None

    def async_show_form(self, **kwargs):
        return types.SimpleNamespace(**kwargs)

    def async_create_entry(self, **kwargs):
        return types.SimpleNamespace(**kwargs)


class OptionsFlow:
    def __init__(self):
        self.config_entry = None

    def async_show_form(self, **kwargs):
        return types.SimpleNamespace(**kwargs)

    def async_create_entry(self, **kwargs):
        return types.SimpleNamespace(**kwargs)


# -- voluptuous stub -----------------------------------------------------------


class _Schema:
    def __init__(self, schema):
        self.schema = schema


class Required:
    def __init__(self, key, default=None, description=None):
        self.key = key
        self.default = default
        self.description = description


class Optional(Required):
    pass


class All:
    def __init__(self, *validators):
        self.validators = validators

    def __call__(self, value):
        return value


class Range:
    def __init__(self, min=None, max=None):
        self.min = min
        self.max = max


def Coerce(type_):
    return lambda value: type_(value)


# -- install stubs -------------------------------------------------------------


def _install_stubs():
    ha = _module("homeassistant")
    _module("homeassistant.config_entries", ConfigEntry=ConfigEntry, ConfigFlow=ConfigFlow, OptionsFlow=OptionsFlow)
    _module(
        "homeassistant.const",
        Platform=Platform,
        EntityCategory=EntityCategory,
        ATTR_DEVICE_ID="device_id",
        ATTR_ENTITY_ID="entity_id",
        CONF_NAME="name",
    )
    _module(
        "homeassistant.core",
        HomeAssistant=HomeAssistant,
        ServiceCall=ServiceCall,
        callback=_callback,
    )
    _module("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
    _module(
        "homeassistant.helpers",
    )
    _module(
        "homeassistant.helpers.device_registry",
        async_get=_device_registry_async_get,
        DeviceInfo=DeviceInfo,
        DeviceEntry=None,
    )
    _module(
        "homeassistant.helpers.entity_registry",
        async_get=lambda hass: _EntityRegistry(),
        async_entries_for_device=lambda registry, device_id: [],
    )
    _module(
        "homeassistant.helpers.aiohttp_client",
        async_get_clientsession=lambda hass: _ClientSession(),
    )
    _module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=DataUpdateCoordinator,
        CoordinatorEntity=CoordinatorEntity,
    )
    _module(
        "homeassistant.helpers.config_validation",
        make_entity_service_schema=lambda data, extra=0: _Schema(data),
    )
    _module(
        "homeassistant.helpers.typing",
        ConfigType=dict,
    )
    _module(
        "homeassistant.helpers.entity_platform",
        AddEntitiesCallback=object,
    )
    _module("homeassistant.util", slugify=lambda s: s.lower().replace(" ", "_"))
    _module("homeassistant.components")
    _module(
        "homeassistant.components.camera",
        async_get_image=_camera_async_get_image,
    )

    class _SensorDeviceClass:
        DIAGNOSTIC = "diagnostic"
        TIMESTAMP = "timestamp"

    class _SensorStateClass:
        MEASUREMENT = "measurement"
        TOTAL_INCREASING = "total_increasing"

    class SensorEntity:
        pass

    _module(
        "homeassistant.components.sensor",
        SensorDeviceClass=_SensorDeviceClass,
        SensorStateClass=_SensorStateClass,
        SensorEntity=SensorEntity,
    )

    class _BinaryDeviceClass:
        PROBLEM = "problem"

    class BinarySensorEntity:
        pass

    _module(
        "homeassistant.components.binary_sensor",
        BinarySensorDeviceClass=_BinaryDeviceClass,
        BinarySensorEntity=BinarySensorEntity,
    )

    class ButtonEntity:
        pass

    _module("homeassistant.components.button", ButtonEntity=ButtonEntity)

    class SwitchEntity:
        pass

    _module("homeassistant.components.switch", SwitchEntity=SwitchEntity)

    # selectors
    class _Selector:
        def __init__(self, config=None):
            self.config = config

    class _TextSelectorType:
        TEXT = "text"
        PASSWORD = "password"

    for name in ("TextSelector", "EntitySelector", "DeviceSelector", "SelectSelector"):
        setattr(sys.modules["homeassistant.helpers"], name, _Selector)
    _module(
        "homeassistant.helpers.selector",
        TextSelector=_Selector,
        EntitySelector=_Selector,
        DeviceSelector=_Selector,
        SelectSelector=_Selector,
        TextSelectorType=_TextSelectorType,
        TextSelectorConfig=dict,
        EntitySelectorConfig=dict,
        DeviceSelectorConfig=dict,
        SelectSelectorConfig=dict,
    )

    _module(
        "voluptuous",
        Schema=_Schema,
        Required=Required,
        Optional=Optional,
        All=All,
        Range=Range,
        Coerce=Coerce,
    )


_install_stubs()

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ENTRY_DATA = {
    "name": "P1S Werkstatt",
    "api_key": "secret",
    "mistral_model": "pixtral-12b-latest",
    "camera_entity": "camera.p1s_chamber",
    "mjpeg_url": "",
    "print_state_entity": "sensor.p1s_print_status",
    "notify_services": "notify.mobile_app_handy",
    "bambu_device_id": "bambu-device-1",
    "manual_context": "PLA, 0.2 mm",
}


@pytest.fixture()
def hass(tmp_path):
    return HomeAssistant(str(tmp_path))


@pytest.fixture()
def entry():
    return ConfigEntry(data=dict(ENTRY_DATA))


@pytest.fixture()
def runtime(hass, entry, tmp_path):
    from custom_components.bambu_stringing.runtime import PrinterRuntime

    hass.data["bambu_stringing"] = {"runtimes": {}}
    # keep archive inside tmp_path
    rt = PrinterRuntime(hass, entry)
    return rt


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_runtime_constructs_with_defaults(runtime):
    from custom_components.bambu_stringing.const import (
        DEFAULT_LAYER_SHIFT_THRESHOLD,
        DEFAULT_SPAGHETTI_THRESHOLD,
        DEFAULT_STRINGING_STREAK,
        DEFAULT_STRINGING_THRESHOLD,
        DEFAULT_WARPING_THRESHOLD,
    )

    assert runtime.printer_name == "P1S Werkstatt"
    assert runtime.slug == "p1s_werkstatt"
    cfg = runtime._engine_config()
    # Gegen die Konstanten testen (nicht gegen fixe Werte): der Benchmark
    # (--apply-default) darf die DEFAULT_*-Werte in const.py überschreiben.
    assert cfg.stringing_threshold == DEFAULT_STRINGING_THRESHOLD
    assert cfg.stringing_streak == DEFAULT_STRINGING_STREAK
    assert cfg.spaghetti_threshold == DEFAULT_SPAGHETTI_THRESHOLD
    assert cfg.warping_threshold == DEFAULT_WARPING_THRESHOLD
    assert cfg.layer_shift_threshold == DEFAULT_LAYER_SHIFT_THRESHOLD
    assert cfg.stringing_cooldown_sec == 15 * 60
    assert runtime.deep_link == (
        "homeassistant://more-info/binary_sensor.p1s_werkstatt_print_failure"
    )
    assert runtime.image_path == "/local/snapshots/p1s_werkstatt/latest.jpg"


def test_benchmark_defaults_per_model(monkeypatch):
    """Benchmark-Schwellenwerte werden pro Modell als Fallback genutzt."""
    from custom_components.bambu_stringing import runtime
    from custom_components.bambu_stringing.const import (
        CONF_LAYER_SHIFT_THRESHOLD,
        CONF_MIN_CONFIDENCE,
        CONF_SMOOTHING_ALPHA,
        CONF_SPAGHETTI_THRESHOLD,
        CONF_STRINGING_STREAK,
        CONF_STRINGING_THRESHOLD,
        CONF_WARPING_THRESHOLD,
        DEFAULT_LAYER_SHIFT_THRESHOLD,
        DEFAULT_MIN_CONFIDENCE,
        DEFAULT_SMOOTHING_ALPHA,
        DEFAULT_SPAGHETTI_THRESHOLD,
        DEFAULT_STRINGING_STREAK,
        DEFAULT_STRINGING_THRESHOLD,
        DEFAULT_WARPING_THRESHOLD,
        MAX_STRINGING_THRESHOLD,
        MIN_STRINGING_THRESHOLD,
    )

    data = {
        "recommended_model": "model-a",
        "recommended_thresholds": {
            "stringing_threshold": 50,
            "spaghetti_threshold": 60,
            "warping_threshold": 55,
            "layer_shift_threshold": 65,
            "min_confidence": 0.7,
            "smoothing_alpha": 0.4,
            "stringing_streak": 2,
        },
        "models": [
            {
                "model": "model-a",
                "recommended_thresholds": {
                    "stringing_threshold": 10,  # unter MIN -> clamp
                    "spaghetti_threshold": 75,
                    "warping_threshold": 55,
                    "layer_shift_threshold": 65,
                    "min_confidence": 0.7,
                    "smoothing_alpha": 0.4,
                    "stringing_streak": 2,
                },
            },
            {
                "model": "model-b",
                "recommended_thresholds": {
                    "stringing_threshold": 0,  # unplausibel -> verwerfen
                },
            },
        ],
    }
    monkeypatch.setattr(runtime, "load_benchmark_data", lambda: data)

    # Modell mit gültigen Werten: übernommen, auf MIN/MAX geklemmt
    bdef = runtime.benchmark_defaults("model-a")
    assert bdef[CONF_STRINGING_THRESHOLD] == MIN_STRINGING_THRESHOLD
    assert bdef[CONF_SPAGHETTI_THRESHOLD] == 75
    assert bdef[CONF_WARPING_THRESHOLD] == 55
    assert bdef[CONF_LAYER_SHIFT_THRESHOLD] == 65
    assert bdef[CONF_MIN_CONFIDENCE] == 0.7
    assert bdef[CONF_SMOOTHING_ALPHA] == 0.4
    assert bdef[CONF_STRINGING_STREAK] == 2
    assert MIN_STRINGING_THRESHOLD <= bdef[CONF_STRINGING_THRESHOLD] <= MAX_STRINGING_THRESHOLD

    # Modell mit ungültigen Werten: fällt auf die globalen Empfehlungen zurück
    bdef_b = runtime.benchmark_defaults("model-b")
    assert bdef_b[CONF_STRINGING_THRESHOLD] == 50
    assert bdef_b[CONF_SPAGHETTI_THRESHOLD] == 60

    # Unbekanntes Modell: fällt auf die globalen Empfehlungen zurück
    bdef_u = runtime.benchmark_defaults("unbekannt-modell")
    assert bdef_u[CONF_STRINGING_THRESHOLD] == 50
    assert bdef_u[CONF_MIN_CONFIDENCE] == 0.7

    # Ganz ohne Benchmark-Daten: DEFAULT_*-Konstanten
    monkeypatch.setattr(runtime, "load_benchmark_data", lambda: {})
    bdef_empty = runtime.benchmark_defaults("model-a")
    assert bdef_empty[CONF_STRINGING_THRESHOLD] == DEFAULT_STRINGING_THRESHOLD
    assert bdef_empty[CONF_SPAGHETTI_THRESHOLD] == DEFAULT_SPAGHETTI_THRESHOLD
    assert bdef_empty[CONF_WARPING_THRESHOLD] == DEFAULT_WARPING_THRESHOLD
    assert bdef_empty[CONF_LAYER_SHIFT_THRESHOLD] == DEFAULT_LAYER_SHIFT_THRESHOLD
    assert bdef_empty[CONF_MIN_CONFIDENCE] == DEFAULT_MIN_CONFIDENCE
    assert bdef_empty[CONF_SMOOTHING_ALPHA] == DEFAULT_SMOOTHING_ALPHA
    assert bdef_empty[CONF_STRINGING_STREAK] == DEFAULT_STRINGING_STREAK


def test_benchmark_data_invalidate_garbage(monkeypatch):
    """Unvollständige/plausible-widrige Schwellwert-Sätze werden verworfen."""
    from custom_components.bambu_stringing import runtime

    # Kaputte Daten (wie sie die alte Analyse erzeugte): Thresholds mit 0
    data = {
        "recommended_model": "model-a",
        "recommended_thresholds": {
            "stringing_threshold": 0,
            "spaghetti_threshold": 0,
            "warping_threshold": 10,
            "layer_shift_threshold": 0,
            "min_confidence": 0.9,
        },
        "models": [],
    }
    monkeypatch.setattr(runtime, "load_benchmark_data", lambda: data)
    assert runtime.model_thresholds("model-a") == {}
    assert runtime.model_thresholds(None) == {}


def test_benchmark_sensor_exposes_per_model_thresholds(hass, entry, monkeypatch):
    """Benchmark-Sensor listet die Schwellenwerte pro Modell auf."""
    from custom_components.bambu_stringing import runtime as rt_mod
    from custom_components.bambu_stringing.const import ATTR_BENCHMARK_MODELS
    from custom_components.bambu_stringing.runtime import PrinterRuntime
    from custom_components.bambu_stringing.sensor import BenchmarkModelSensor

    data = {
        "recommended_model": "model-a",
        "recommended_reason": "Test",
        "recommended_thresholds": {
            "stringing_threshold": 50,
            "spaghetti_threshold": 60,
            "warping_threshold": 55,
            "layer_shift_threshold": 65,
            "min_confidence": 0.7,
            "smoothing_alpha": 0.4,
            "stringing_streak": 2,
        },
        "timestamp": "2026-10-24 10:00:00",
        "models": [
            {
                "model": "model-a",
                "accuracy_pct": 80.0,
                "avg_latency_ms": 1000.0,
                "cost_per_scan_cents": 0.1,
                "value_score": 80.0,
                "category_accuracy": {"clean": 100.0},
                "recommended_thresholds": {
                    "stringing_threshold": 45,
                    "spaghetti_threshold": 60,
                    "warping_threshold": 55,
                    "layer_shift_threshold": 65,
                    "min_confidence": 0.7,
                    "smoothing_alpha": 0.4,
                    "stringing_streak": 2,
                },
            },
        ],
    }
    monkeypatch.setattr(rt_mod, "load_benchmark_data", lambda: data)

    hass.data["bambu_stringing"] = {"runtimes": {}}
    rt = PrinterRuntime(hass, entry)
    sensor = BenchmarkModelSensor(rt)

    attrs = sensor.extra_state_attributes
    assert attrs["recommended_thresholds"]["stringing_threshold"] == 50
    assert attrs["models"][0]["recommended_thresholds"]["stringing_threshold"] == 45
    assert attrs["models"][0]["recommended_thresholds"]["min_confidence"] == 0.7


def test_gate_reads_gcode_state_attribute(runtime, hass):
    hass.states.set("sensor.p1s_print_status", "RUNNING", {"gcode_state": "RUNNING"})
    assert runtime._print_running() is True
    hass.states.set("sensor.p1s_print_status", "IDLE", {"gcode_state": "FINISH"})
    assert runtime._print_running() is False


def test_gate_without_entity_is_fail_closed(runtime, entry):
    """No print_state_entity configured -> gate returns False (fail-closed)."""
    entry.data["print_state_entity"] = ""
    assert runtime._print_running() is False


def test_gate_pause_state_is_running(runtime, hass):
    """PAUSE is in the default running_states (RUNNING,PAUSE)."""
    hass.states.set("sensor.p1s_print_status", "PAUSE", {"gcode_state": "PAUSE"})
    assert runtime._print_running() is True


def test_gate_idle_state_is_not_running(runtime, hass):
    """IDLE is not in the default running_states."""
    hass.states.set("sensor.p1s_print_status", "IDLE", {"gcode_state": "IDLE"})
    assert runtime._print_running() is False


def test_gate_lowercase_state_from_ha_bambulab(runtime, hass):
    """ha-bambulab print_status sensor returns lowercase states."""
    hass.states.set("sensor.p1s_print_status", "running")
    assert runtime._print_running() is True
    hass.states.set("sensor.p1s_print_status", "idle")
    assert runtime._print_running() is False
    hass.states.set("sensor.p1s_print_status", "pause")
    assert runtime._print_running() is True


def test_gate_unknown_entity_is_not_running(runtime, hass):
    """Entity that does not exist -> gate returns False."""
    assert runtime._print_running() is False


def test_validate_gate_entity_logs_error_without_entity(runtime, entry, caplog):
    """Startup validation logs an error when no entity is configured."""
    entry.data["print_state_entity"] = ""
    with caplog.at_level("ERROR"):
        runtime._validate_gate_entity()
    assert "Kein Druckstatus-Entity konfiguriert" in caplog.text


def test_validate_gate_entity_warns_for_non_sensor(runtime, hass, caplog):
    """Startup validation warns when the entity is not a sensor.*."""
    hass.states.set("binary_sensor.p1s_online", "on")
    runtime.entry.data["print_state_entity"] = "binary_sensor.p1s_online"
    with caplog.at_level("WARNING"):
        runtime._validate_gate_entity()
    assert "kein sensor.*" in caplog.text


def test_validate_gate_entity_warns_for_missing_entity(runtime, caplog):
    """Startup validation warns when the entity does not exist yet."""
    with caplog.at_level("WARNING"):
        runtime._validate_gate_entity()
    assert "existiert noch nicht" in caplog.text


def test_validate_gate_entity_ok_with_running_state(runtime, hass, caplog):
    """Startup validation logs info when entity exists and is ready."""
    hass.states.set("sensor.p1s_print_status", "IDLE", {"gcode_state": "IDLE"})
    with caplog.at_level("INFO"):
        runtime._validate_gate_entity()
    assert "ist bereit" in caplog.text


async def test_cycle_end_to_end(runtime, hass, tmp_path, monkeypatch):
    """Grab -> archive -> Mistral call -> decision -> entities, fully mocked."""
    frame = b"\xff\xd8fakejpeg\xff\xd9"

    async def fake_grab():
        return frame

    async def fake_post_json(url, *, headers, payload):
        assert headers["Authorization"] == "Bearer secret"
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"stringing_score": 30, "spaghetti_score": 2, '
                        '"warping_score": 5, "layer_shift_score": 1, '
                        '"bed_adhesion_failure": false, "observations": "OK.", '
                        '"other_defects": []}'
                    }
                }
            ]
        }

    monkeypatch.setattr(runtime, "_grab_frame", fake_grab)
    monkeypatch.setattr(runtime, "_post_json", fake_post_json)
    hass.states.set("sensor.p1s_print_status", "RUNNING", {"gcode_state": "RUNNING"})

    runtime._start_print()
    await runtime._cycle()

    data = runtime.coordinator.data
    assert data["stringing_score"] == 30
    assert data["spaghetti_score"] == 2
    assert data["warping_score"] == 5
    assert data["layer_shift_score"] == 1
    assert data["other_defects"] == ()
    assert data["api_calls"] == 1
    assert data["print_running"] is True
    assert not data["stringing_detected"]
    assert not data["print_failure"]

    archive_dir = Path(hass.config.config_dir) / "www" / "snapshots" / "p1s_werkstatt"
    assert (archive_dir / "latest.jpg").read_bytes() == frame
    assert list(archive_dir.glob("frame_*.jpg"))
    score_logs = list(archive_dir.glob("scores_*.jsonl"))
    assert len(score_logs) == 1
    assert '"stringing_score": 30' in score_logs[0].read_text()


def test_entities_expose_pipeline_data(runtime):
    from bs_core.mistral import AnalysisResult

    from custom_components.bambu_stringing.binary_sensor import (
        LayerShiftDetectedBinarySensor,
        PrintFailureBinarySensor,
        StringingDetectedBinarySensor,
        WarpingDetectedBinarySensor,
    )
    from custom_components.bambu_stringing.button import ResetButton
    from custom_components.bambu_stringing.sensor import (
        ApiCallsSensor,
        DetectedEventsSensor,
        LastCheckSensor,
        LayerShiftScoreSensor,
        SpaghettiScoreSensor,
        StringingScoreSensor,
        WarpingScoreSensor,
    )
    from custom_components.bambu_stringing.switch import MuteSwitch

    runtime._last_result = AnalysisResult(
        stringing_score=70,
        spaghetti_score=5,
        bed_adhesion_failure=False,
        observations="Starkes Stringing.",
        warping_score=62,
        layer_shift_score=8,
        other_defects=("Blobs am Turm", "Z-Scarring"),
    )
    runtime.api_calls = 5
    runtime.discarded = 1
    runtime._push()

    score = StringingScoreSensor(runtime)
    assert score.native_value == 70
    assert score.extra_state_attributes["other_defects"] == [
        "Blobs am Turm",
        "Z-Scarring",
    ]
    spaghetti = SpaghettiScoreSensor(runtime)
    assert spaghetti.extra_state_attributes["other_defects"] == [
        "Blobs am Turm",
        "Z-Scarring",
    ]
    warping = WarpingScoreSensor(runtime)
    assert warping.native_value == 62
    layer_shift = LayerShiftScoreSensor(runtime)
    assert layer_shift.native_value == 8
    api = ApiCallsSensor(runtime)
    events = DetectedEventsSensor(runtime)
    last_check = LastCheckSensor(runtime)
    failure = PrintFailureBinarySensor(runtime)
    stringing = StringingDetectedBinarySensor(runtime)
    warping_detected = WarpingDetectedBinarySensor(runtime)
    layer_shift_detected = LayerShiftDetectedBinarySensor(runtime)
    mute = MuteSwitch(runtime)
    reset = ResetButton(runtime)

    assert api.native_value == 5
    assert api.extra_state_attributes["discarded_frames"] == 1
    assert events.native_value == 0
    assert last_check.native_value is not None
    assert failure.is_on is False
    assert stringing.is_on is False
    assert warping_detected.is_on is False
    assert layer_shift_detected.is_on is False
    assert mute.is_on is False

    # mute switch reflects engine state
    runtime.set_muted(True)
    assert mute.is_on is True
    runtime.set_muted(False)
    assert mute.is_on is False

    # unique ids are entry scoped
    assert score._attr_unique_id.endswith("_stringing_score")
    assert warping._attr_unique_id.endswith("_warping_score")
    assert layer_shift._attr_unique_id.endswith("_layer_shift_score")
    assert failure._attr_unique_id.endswith("_print_failure")
    assert warping_detected._attr_unique_id.endswith("_warping_detected")
    assert layer_shift_detected._attr_unique_id.endswith("_layer_shift_detected")
    assert reset._attr_unique_id.endswith("_reset")


def test_reset_service_clears_latched_state(runtime, hass, entry):
    import custom_components.bambu_stringing as bs
    from bs_core.mistral import AnalysisResult

    asyncio.run(bs.async_setup(hass, {}))
    assert ("bambu_stringing", "reset_detection") in hass.services.registered
    assert ("bambu_stringing", "check_now") in hass.services.registered

    hass.data["bambu_stringing"]["runtimes"][entry.entry_id] = runtime
    # latch a failure + mute (mute must survive the reset)
    runtime.engine.process(
        AnalysisResult(
            stringing_score=90,
            spaghetti_score=90,
            bed_adhesion_failure=False,
            observations="Spaghetti!",
            warping_score=70,
            layer_shift_score=80,
        )
    )
    runtime.set_muted(True)
    assert runtime.engine.print_failure
    assert runtime.engine.layer_shift_detected

    # route the service call via our device (as HA would)
    device_registry = sys.modules["homeassistant.helpers.device_registry"].async_get(hass)
    device_registry.devices["dev-ours"] = types.SimpleNamespace(
        identifiers=[("bambu_stringing", entry.entry_id)]
    )
    call = ServiceCall(hass, {"device_id": ["dev-ours"]})
    asyncio.run(bs._handle_reset(call))

    assert not runtime.engine.print_failure
    assert not runtime.engine.layer_shift_detected
    assert not runtime.engine.stringing_detected
    assert runtime.engine.muted  # untouched by design
    assert hass.data["bambu_stringing"]["runtimes"][entry.entry_id].coordinator.data[
        "print_failure"
    ] is False


def test_notification_action_routing(runtime, hass, monkeypatch):
    import custom_components.bambu_stringing as bs

    hass.data["bambu_stringing"]["runtimes"][runtime.entry.entry_id] = runtime
    paused = []

    async def fake_pause():
        paused.append(True)

    monkeypatch.setattr(runtime, "async_pause_print", fake_pause)

    event = types.SimpleNamespace(
        data={"action": f"bambu_stringing_{runtime.entry.entry_id}_pause"}
    )
    bs._handle_notification_action(hass, event)
    assert paused

    event = types.SimpleNamespace(
        data={"action": f"bambu_stringing_{runtime.entry.entry_id}_ignore"}
    )
    bs._handle_notification_action(hass, event)
    assert runtime.engine.muted is True

    event = types.SimpleNamespace(data={"action": "other_domain_action"})
    bs._handle_notification_action(hass, event)  # ignored silently


def test_notify_auto_detects_companion_apps(runtime, hass, entry):
    # empty target -> all notify.mobile_app_* services of this HA instance
    entry.data["notify_services"] = ""
    assert runtime._notify_services() == [
        ("notify", "mobile_app_handy"),
        ("notify", "mobile_app_tablet"),
    ]
    # explicit target keeps working
    hass.services.registered[("notify", "mobile_app_handy")] = lambda call: None
    entry.data["notify_services"] = "notify.mobile_app_handy"
    assert runtime._notify_services() == [("notify", "mobile_app_handy")]


def test_config_flow_and_options_flow_import(runtime, hass, entry):
    from custom_components.bambu_stringing.config_flow import (
        BambuStringingConfigFlow,
        BambuStringingOptionsFlow,
    )

    flow = BambuStringingConfigFlow()
    flow.hass = hass
    assert flow.VERSION == 1

    user_form = asyncio.run(flow.async_step_user(None))
    assert user_form.step_id == "user"

    options = BambuStringingOptionsFlow()
    options.hass = hass
    options.config_entry = entry
    result = asyncio.run(options.async_step_init(None))
    assert result.step_id == "init"
    keys = [v.key for v in result.data_schema.schema]
    for expected in (
        "check_interval_sec",
        "stringing_threshold",
        "stringing_streak",
        "spaghetti_threshold",
        "warping_threshold",
        "layer_shift_threshold",
        "stringing_cooldown_min",
        "auto_pause",
        "api_key",
        "mistral_model",
        "snapshot_retention_days",
    ):
        assert expected in keys, keys


# ---------------------------------------------------------------------------
# dashboard generation
# ---------------------------------------------------------------------------


async def test_dashboard_view_generation(runtime, hass, entry, monkeypatch):
    """Create the sidebar dashboard and check the generated card structure."""
    from custom_components.bambu_stringing import dashboard as dash

    hass.data["bambu_stringing"]["runtimes"][entry.entry_id] = runtime

    # -- lovelace / frontend stubs (lazy imports inside dashboard.py)
    saved = {"config": None, "deleted": False, "panels_removed": []}
    created_items = []

    class _LovelaceStorage:
        mode = "storage"

        def __init__(self, hass, item=None):
            self.item = item

        async def async_save(self, config):
            saved["config"] = config

        async def async_delete(self):
            saved["deleted"] = True

    class _DashboardsCollection:
        def __init__(self, hass):
            self.items = [
                {
                    "id": "existing-id",
                    "url_path": "bambu-stringing",
                    "title": "3D-Druck",
                    "icon": "mdi:printer-3d",
                    "show_in_sidebar": True,
                    "require_admin": False,
                }
            ]

        async def async_load(self):
            return None

        def async_items(self):
            return self.items

        async def async_create_item(self, data):
            item = {"id": "new-id", **data}
            created_items.append(item)
            return item

        async def async_delete_item(self, item_id):
            saved["deleted_item"] = item_id

    lovelace_pkg = types.ModuleType("homeassistant.components.lovelace")
    lovelace_mod = types.ModuleType("homeassistant.components.lovelace.dashboard")
    lovelace_mod.DashboardsCollection = _DashboardsCollection
    lovelace_mod.LovelaceStorage = _LovelaceStorage
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace", lovelace_pkg)
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace.dashboard", lovelace_mod)

    frontend_mod = types.ModuleType("homeassistant.components.frontend")

    def _register_panel(hass, component_name, **kwargs):
        saved["panel"] = kwargs

    frontend_mod.async_register_built_in_panel = _register_panel

    def _remove_panel(hass, url_path):
        saved["panels_removed"].append(url_path)

    frontend_mod.async_remove_panel = _remove_panel
    monkeypatch.setitem(sys.modules, "homeassistant.components.frontend", frontend_mod)

    # -- lovelace data as set up by HA's own async_setup
    dash_store = _LovelaceStorage(hass)
    hass.data["lovelace"] = types.SimpleNamespace(
        dashboards={None: _LovelaceStorage(hass), "bambu-stringing": dash_store}
    )

    # -- entity registry stubs
    er_mod = sys.modules["homeassistant.helpers.entity_registry"]

    class _EntityReg:
        def async_get_entity_id(self, domain, platform, unique_id):
            key = unique_id.split("_", 1)[1] if "_" in unique_id else unique_id
            return f"{domain}.p1s_werkstatt_{key}"

    def _fake_async_get(hass):
        return _EntityReg()

    monkeypatch.setattr(er_mod, "async_get", _fake_async_get)

    bambu_entries = [
        types.SimpleNamespace(
            entity_id="sensor.p1s_print_progress", original_name="Print Progress"
        ),
        types.SimpleNamespace(
            entity_id="sensor.p1s_nozzle_temp", original_name="Düsentemperatur"
        ),
        types.SimpleNamespace(
            entity_id="sensor.p1s_remaining_time", original_name="Restzeit"
        ),
        types.SimpleNamespace(
            entity_id="image.p1s_cover_image", original_name="Cover Image"
        ),
    ]

    def _entries_for_device(registry, device_id, include_disabled_entities=False):
        assert device_id == "bambu-device-1"
        return bambu_entries

    monkeypatch.setattr(er_mod, "async_entries_for_device", _entries_for_device)

    await dash.async_setup_printer_view(hass, runtime)

    # existing dashboard entry reused, no new item created, panel untouched
    assert created_items == []
    assert "panel" not in saved

    views = saved["config"]["views"]
    assert len(views) == 1
    view = views[0]
    assert view["title"] == "P1S Werkstatt"
    assert view["type"] == "sections"
    assert view["path"] == "p1s_werkstatt"

    # printer stats live in the header as small badges, alarm badge first
    assert view["max_columns"] == 2
    badges = {b["name"]: b for b in view["badges"]}
    assert badges["Druckfehler"]["entity"] == "binary_sensor.p1s_werkstatt_print_failure"
    assert view["badges"][0]["name"] == "Druckfehler"
    assert badges["Druckfortschritt"]["entity"] == "sensor.p1s_print_progress"
    assert badges["Düsentemperatur"]["entity"] == "sensor.p1s_nozzle_temp"
    assert badges["Restzeit"]["entity"] == "sensor.p1s_remaining_time"

    # one section each: camera, history, information, actions
    headings = [
        c["heading"]
        for s in view["sections"]
        for c in s["cards"]
        if c.get("type") == "heading"
    ]
    assert headings == ["Kamera", "Score-Verlauf", "Informationen", "Aktionen"]

    def section_cards(heading):
        for s in view["sections"]:
            if any(c.get("heading") == heading for c in s["cards"]):
                return s["cards"]
        raise AssertionError(f"section {heading} not found")

    # camera: picture-entity (camera card removed from the frontend) at 8
    # columns, next to it the model preview (ha-bambulab cover image) at 4
    assert [
        c for c in section_cards("Kamera") if c.get("type") == "picture-entity"
    ] == [
        {
            "type": "picture-entity",
            "entity": "camera.p1s_chamber",
            "camera_image": "camera.p1s_chamber",
            "camera_view": "live",
            "grid_options": {"columns": 8, "rows": 6},
        },
        {
            "type": "picture-entity",
            "entity": "image.p1s_cover_image",
            "name": "Modell",
            "grid_options": {"columns": 4, "rows": 6},
        },
    ]

    # history graph with the 7 detection entities (aggregate is badge+tile)
    history_cards = [c for c in section_cards("Score-Verlauf") if c.get("type") == "history-graph"]
    assert len(history_cards) == 1
    assert history_cards[0]["grid_options"] == {"columns": "full", "rows": 6}
    assert history_cards[0]["entities"] == [
        "sensor.p1s_werkstatt_stringing_score",
        "sensor.p1s_werkstatt_spaghetti_score",
        "sensor.p1s_werkstatt_warping_score",
        "sensor.p1s_werkstatt_layer_shift_score",
        "binary_sensor.p1s_werkstatt_stringing_detected",
        "binary_sensor.p1s_werkstatt_warping_detected",
        "binary_sensor.p1s_werkstatt_layer_shift_detected",
    ]

    # glanceable score tiles below the graph
    score_tiles = [c for c in section_cards("Score-Verlauf") if c.get("type") == "tile"]
    assert score_tiles == [
        {"type": "tile", "entity": entity}
        for entity in [
            "sensor.p1s_werkstatt_stringing_score",
            "sensor.p1s_werkstatt_spaghetti_score",
            "sensor.p1s_werkstatt_warping_score",
            "sensor.p1s_werkstatt_layer_shift_score",
        ]
    ]

    # information section: binary sensor + diagnostics tiles, nothing else
    info_cards = section_cards("Informationen")
    info_tiles = {c.get("entity"): c for c in info_cards if c.get("type") == "tile"}
    assert set(info_tiles) == {
        "binary_sensor.p1s_werkstatt_print_failure",
        "binary_sensor.p1s_werkstatt_stringing_detected",
        "binary_sensor.p1s_werkstatt_warping_detected",
        "binary_sensor.p1s_werkstatt_layer_shift_detected",
        "sensor.p1s_werkstatt_api_calls",
        "sensor.p1s_werkstatt_events",
        "sensor.p1s_werkstatt_last_check",
    }
    assert not any(c.get("type") == "button" for c in info_cards)

    # action section: buttons incl. reset + mute switch
    action_cards = section_cards("Aktionen")
    buttons = {c.get("name"): c for c in action_cards if c.get("type") == "button"}
    assert buttons["Pause"]["entity"] == "button.p1s_werkstatt_pause"
    assert buttons["Zurücksetzen"]["entity"] == "button.p1s_werkstatt_reset"
    mute_tiles = [c for c in action_cards if c.get("type") == "tile"]
    assert mute_tiles == [
        {
            "type": "tile",
            "entity": "switch.p1s_werkstatt_mute",
            "name": "Stumm",
            "icon": "mdi:bell-off",
            "features": [{"type": "toggle"}],
        }
    ]

    # -- removal: view regenerated while printers remain, dashboard deleted at last
    await dash.async_remove_printer_view(hass, entry.entry_id)
    assert "deleted_item" not in saved  # runtime still registered -> keep dashboard
    assert len(saved["config"]["views"]) == 1

    hass.data["bambu_stringing"]["runtimes"].pop(entry.entry_id, None)
    await dash.async_remove_printer_view(hass, entry.entry_id)
    assert saved["deleted_item"] == "existing-id"
    assert saved["deleted"] is True  # .storage/lovelace.<id> removed
    assert saved["panels_removed"] == ["bambu-stringing"]


async def test_dashboard_camera_fallback_picture_card(runtime, hass, entry, monkeypatch):
    """Without a camera entity the view falls back to the latest snapshot."""
    from custom_components.bambu_stringing import dashboard as dash

    entry.data["camera_entity"] = ""
    hass.data["bambu_stringing"]["runtimes"][entry.entry_id] = runtime

    saved = {"config": None}

    class _LovelaceStorage:
        mode = "storage"

        def __init__(self, hass, item=None):
            self.item = item

        async def async_save(self, config):
            saved["config"] = config

        async def async_delete(self):
            pass

    class _DashboardsCollection:
        def __init__(self, hass):
            self.items = []

        async def async_load(self):
            return None

        def async_items(self):
            return self.items

        async def async_create_item(self, data):
            item = {
                "id": "new-id",
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "storage",
                **data,
            }
            self.items.append(item)
            created_items.append(item)
            return item

        async def async_delete_item(self, item_id):
            pass

    created_items = []

    lovelace_mod = types.ModuleType("homeassistant.components.lovelace.dashboard")
    lovelace_mod.DashboardsCollection = _DashboardsCollection
    lovelace_mod.LovelaceStorage = _LovelaceStorage
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace", types.ModuleType("homeassistant.components.lovelace"))
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace.dashboard", lovelace_mod)

    frontend_mod = types.ModuleType("homeassistant.components.frontend")
    frontend_mod.async_register_built_in_panel = (
        lambda hass, name, **kw: saved.setdefault("panel", kw)
    )
    frontend_mod.async_remove_panel = lambda hass, path: None
    monkeypatch.setitem(sys.modules, "homeassistant.components.frontend", frontend_mod)

    dash_store = _LovelaceStorage(hass)
    hass.data["lovelace"] = types.SimpleNamespace(
        dashboards={None: _LovelaceStorage(hass), "bambu-stringing": dash_store}
    )

    er_mod = sys.modules["homeassistant.helpers.entity_registry"]
    monkeypatch.setattr(
        er_mod,
        "async_get",
        lambda hass: types.SimpleNamespace(async_get_entity_id=lambda *a: None),
    )
    monkeypatch.setattr(
        er_mod, "async_entries_for_device", lambda *a, **k: []
    )

    await dash.async_setup_printer_view(hass, runtime)

    # dashboard entry freshly created and sidebar panel registered
    assert created_items[0]["url_path"] == "bambu-stringing"
    assert saved["panel"]["frontend_url_path"] == "bambu-stringing"
    assert saved["panel"]["sidebar_title"] == "3D-Druck"

    view = saved["config"]["views"][0]
    # no entities resolved -> camera section only, no badges
    assert "badges" not in view
    assert len(view["sections"]) == 1
    all_cards = [c for s in view["sections"] for c in s["cards"]]
    picture = [c for c in all_cards if c.get("type") == "picture"]
    assert picture == [
        {
            "type": "picture",
            "image_path": "/local/snapshots/p1s_werkstatt/latest.jpg",
            "name": "P1S Werkstatt",
            "grid_options": {"columns": "full", "rows": 6},
        }
    ]
    assert [c for c in all_cards if c.get("type") == "tile"] == []
    assert [c for c in all_cards if c.get("type") == "button"] == []
    assert [c for c in all_cards if c.get("type") == "history-graph"] == []


# ---------------------------------------------------------------------------
# version check / restart repair
# ---------------------------------------------------------------------------


async def test_version_check_raises_and_clears_restart_issue(hass, tmp_path, monkeypatch):
    """Loaded vs on-disk version mismatch -> fixable repair issue."""
    from datetime import timedelta

    from custom_components.bambu_stringing import version_check

    manifest = tmp_path / "custom_components" / "bambu_stringing" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"version": "0.5.0"}')

    hass.config.path = lambda *parts: tmp_path.joinpath(*parts)

    async def _exec(fn, *args):
        return fn(*args)

    hass.async_add_executor_job = _exec
    hass.data["bambu_stringing"] = {"runtimes": {}}

    created = []
    deleted = []

    issues_mod = types.ModuleType("homeassistant.issues")
    issues_mod.IssueSeverity = types.SimpleNamespace(WARNING="warning")
    issues_mod.async_create_issue = lambda *a, **k: created.append((a, k))
    issues_mod.async_delete_issue = lambda *a, **k: deleted.append((a, k))
    monkeypatch.setitem(sys.modules, "homeassistant.issues", issues_mod)

    loader_mod = types.ModuleType("homeassistant.loader")
    loader_mod.async_get_integration = (
        lambda hass, domain: types.SimpleNamespace(version="0.4.0")
    )
    monkeypatch.setitem(sys.modules, "homeassistant.loader", loader_mod)

    tracked = []

    event_mod = types.ModuleType("homeassistant.helpers.event")
    event_mod.async_track_time_interval = (
        lambda hass, cb, interval: tracked.append(interval) or (lambda: None)
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.event", event_mod)

    await version_check.async_setup_version_check(hass)

    # mismatch -> one fixable issue carrying both versions, hourly re-check
    assert len(created) == 1
    args, kwargs = created[0]
    assert args[1:] == ("bambu_stringing", "restart_required")
    assert kwargs["is_fixable"] is True
    assert kwargs["severity"] == "warning"
    assert kwargs["translation_placeholders"] == {
        "loaded_version": "0.4.0",
        "disk_version": "0.5.0",
    }
    assert tracked == [timedelta(hours=1)]
    assert deleted == []

    # versions match again -> issue deleted, nothing new created
    manifest.write_text('{"version": "0.4.0"}')
    await version_check.async_check_version(hass)
    assert len(created) == 1
    assert [d[0][1:] for d in deleted] == [("bambu_stringing", "restart_required")]


async def test_restart_fix_flow_triggers_restart(hass, monkeypatch):
    """The restart-required fix flow calls homeassistant.restart on submit."""
    repairs_mod = types.ModuleType("homeassistant.components.repairs")

    class RepairsFlow:
        def __init__(self):
            self.hass = None

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

    repairs_mod.RepairsFlow = RepairsFlow
    monkeypatch.setitem(sys.modules, "homeassistant.components.repairs", repairs_mod)

    def_mod = types.ModuleType("homeassistant.data_entry_flow")
    def_mod.FlowResult = dict
    monkeypatch.setitem(sys.modules, "homeassistant.data_entry_flow", def_mod)
    setattr(sys.modules["homeassistant"], "data_entry_flow", def_mod)

    from custom_components.bambu_stringing import repairs

    calls = []

    async def _async_call(domain, service, blocking=False, **kwargs):
        calls.append((domain, service, blocking))

    hass.services.async_call = _async_call

    fix_flow = await repairs.async_create_fix_flow(hass, "restart_required", None)
    assert isinstance(fix_flow, repairs.RestartRequiredFixFlow)
    fix_flow.hass = hass

    form = await fix_flow.async_step_init(None)
    assert form["type"] == "form"
    assert form["step_id"] == "init"
    assert calls == []

    result = await fix_flow.async_step_init({})
    assert result["type"] == "create_entry"
    assert calls == [("homeassistant", "restart", False)]
