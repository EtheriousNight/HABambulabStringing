"""Constants for the Bambu Lab stringing detection integration."""
from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "bambu_stringing"
LOGGER = logging.getLogger(__package__)

# Config entry data (set in config flow)
CONF_API_KEY: Final = "api_key"
CONF_MODEL: Final = "mistral_model"
CONF_CAMERA_ENTITY: Final = "camera_entity"
CONF_MJPEG_URL: Final = "mjpeg_url"
CONF_PRINT_STATE_ENTITY: Final = "print_state_entity"
CONF_NOTIFY_SERVICES: Final = "notify_services"
CONF_BAMBU_DEVICE_ID: Final = "bambu_device_id"
CONF_MANUAL_CONTEXT: Final = "manual_context"
CONF_NAME: Final = "name"

# Options (section 6 of the spec)
CONF_CHECK_INTERVAL: Final = "check_interval_sec"
CONF_STRINGING_THRESHOLD: Final = "stringing_threshold"
CONF_STRINGING_STREAK: Final = "stringing_streak"
CONF_SPAGHETTI_THRESHOLD: Final = "spaghetti_threshold"
CONF_WARPING_THRESHOLD: Final = "warping_threshold"
CONF_LAYER_SHIFT_THRESHOLD: Final = "layer_shift_threshold"
CONF_COOLDOWN_MIN: Final = "stringing_cooldown_min"
CONF_AUTO_PAUSE: Final = "auto_pause"
CONF_RETENTION_DAYS: Final = "snapshot_retention_days"
CONF_RUNNING_STATES: Final = "running_states"
CONF_DEEP_LINK: Final = "deep_link"
CONF_PAUSE_SERVICE: Final = "pause_service"
CONF_RESUME_SERVICE: Final = "resume_service"
CONF_STOP_SERVICE: Final = "stop_service"

DEFAULT_MODEL: Final = "zai-glm-5-3-flash"
DEFAULT_CHECK_INTERVAL: Final = 45
DEFAULT_STRINGING_THRESHOLD: Final = 45
DEFAULT_STRINGING_STREAK: Final = 3
DEFAULT_SPAGHETTI_THRESHOLD: Final = 87
DEFAULT_WARPING_THRESHOLD: Final = 75
DEFAULT_LAYER_SHIFT_THRESHOLD: Final = 40
DEFAULT_COOLDOWN_MIN: Final = 15
DEFAULT_AUTO_PAUSE: Final = False
DEFAULT_RETENTION_DAYS: Final = 14
DEFAULT_RUNNING_STATES: Final = "RUNNING,PAUSE"
DEFAULT_NOTIFY_SERVICES: Final = ""  # empty = auto-detect all companion apps
NOTIFY_TARGET_AUTO: Final = "auto"
DEFAULT_PAUSE_SERVICE: Final = "bambu_lab.pause_print"
DEFAULT_RESUME_SERVICE: Final = "bambu_lab.resume_print"
DEFAULT_STOP_SERVICE: Final = "bambu_lab.stop_print"
DEFAULT_DEEP_LINK_TEMPLATE: Final = "homeassistant://more-info/binary_sensor.{slug}_print_failure"

MIN_CHECK_INTERVAL: Final = 20
MAX_CHECK_INTERVAL: Final = 300
MIN_STRINGING_THRESHOLD: Final = 40
MAX_STRINGING_THRESHOLD: Final = 80
MIN_STRINGING_STREAK: Final = 1
MAX_STRINGING_STREAK: Final = 5
MIN_SPAGHETTI_THRESHOLD: Final = 50
MAX_SPAGHETTI_THRESHOLD: Final = 90
MIN_WARPING_THRESHOLD: Final = 40
MAX_WARPING_THRESHOLD: Final = 80
MIN_LAYER_SHIFT_THRESHOLD: Final = 30
MAX_LAYER_SHIFT_THRESHOLD: Final = 90
MIN_COOLDOWN_MIN: Final = 5
MAX_COOLDOWN_MIN: Final = 60
MIN_RETENTION_DAYS: Final = 1
MAX_RETENTION_DAYS: Final = 90

GATE_POLL_SECONDS: Final = 5.0

# Coordinator data keys
ATTR_STRINGING_SCORE: Final = "stringing_score"
ATTR_SPAGHETTI_SCORE: Final = "spaghetti_score"
ATTR_WARPING_SCORE: Final = "warping_score"
ATTR_LAYER_SHIFT_SCORE: Final = "layer_shift_score"
ATTR_OTHER_DEFECTS: Final = "other_defects"
ATTR_BED_ADHESION_FAILURE: Final = "bed_adhesion_failure"
ATTR_OBSERVATIONS: Final = "observations"
ATTR_STRINGING_DETECTED: Final = "stringing_detected"
ATTR_WARPING_DETECTED: Final = "warping_detected"
ATTR_LAYER_SHIFT_DETECTED: Final = "layer_shift_detected"
ATTR_PRINT_FAILURE: Final = "print_failure"
ATTR_MUTED: Final = "muted"
ATTR_API_CALLS: Final = "api_calls"
ATTR_API_FAILURES: Final = "api_failures"
ATTR_DISCARDED: Final = "discarded"
ATTR_GRAB_FAILURES: Final = "grab_failures"
ATTR_EVENTS: Final = "events"
ATTR_LAST_CHECK: Final = "last_check"
ATTR_PRINT_RUNNING: Final = "print_running"
ATTR_PRINT_ID: Final = "print_id"
ATTR_LAST_ERROR: Final = "last_error"
ATTR_CONFIDENCE: Final = "confidence"
ATTR_REASONING: Final = "reasoning"
ATTR_LOW_CONFIDENCE_FRAMES: Final = "low_confidence_frames"

# Services
SERVICE_CHECK_NOW: Final = "check_now"
SERVICE_MUTE_FOR_PRINT: Final = "mute_for_print"
SERVICE_RESET_DETECTION: Final = "reset_detection"

# Notification action identifiers (f"{ACTION_PREFIX}{entry_id}_{suffix}")
ACTION_PREFIX: Final = "bambu_stringing_"
ACTION_SUFFIX_PAUSE: Final = "pause"
ACTION_SUFFIX_IGNORE: Final = "ignore"

# Benchmark data (Model comparison from benchmark/run_benchmark.py)
BENCHMARK_DATA_FILE: Final = "benchmark_data.json"
ATTR_BENCHMARK_RECOMMENDED: Final = "benchmark_recommended_model"
ATTR_BENCHMARK_MODELS: Final = "benchmark_models"
ATTR_BENCHMARK_THRESHOLDS: Final = "benchmark_recommended_thresholds"
ATTR_BENCHMARK_TIMESTAMP: Final = "benchmark_timestamp"
ATTR_MODEL_ACCURACY: Final = "model_accuracy_pct"
ATTR_MODEL_LATENCY: Final = "model_avg_latency_ms"
ATTR_MODEL_COST_PER_SCAN: Final = "model_cost_per_scan_cents"
ATTR_MODEL_VALUE_SCORE: Final = "model_value_score"

# Kontext-Features (für erweiterte Prompt-Informationen, Prompt v3.0)
CONF_FILAMENT_TYPE: Final = "filament_type"
CONF_NOZZLE_TEMP: Final = "nozzle_temp"
CONF_BED_TEMP: Final = "bed_temp"
CONF_LAYER_HEIGHT: Final = "layer_height"
CONF_PRINT_SPEED: Final = "print_speed"

DEFAULT_FILAMENT_TYPE: Final = ""  # leer = nicht gesetzt
DEFAULT_NOZZLE_TEMP: Final = 0     # 0 = unbekannt
DEFAULT_BED_TEMP: Final = 0
DEFAULT_LAYER_HEIGHT: Final = 0.0
DEFAULT_PRINT_SPEED: Final = 0

# Preprocessing
CONF_PREPROCESS_ENABLED: Final = "preprocess_enabled"
DEFAULT_PREPROCESS_ENABLED: Final = True

# Decision Engine v3.0
CONF_MIN_CONFIDENCE: Final = "min_confidence"
CONF_SMOOTHING_ENABLED: Final = "smoothing_enabled"
CONF_SMOOTHING_ALPHA: Final = "smoothing_alpha"

DEFAULT_MIN_CONFIDENCE: Final = 0.8
DEFAULT_SMOOTHING_ENABLED: Final = True
DEFAULT_SMOOTHING_ALPHA: Final = 0.3

# Plausibility Rules (v3.2) — können Accuracy verschlechtern, daher AUS per default
CONF_PLAUSIBILITY_RULES_ENABLED: Final = "plausibility_rules_enabled"
DEFAULT_PLAUSIBILITY_RULES_ENABLED: Final = False

MIN_CONFIDENCE: Final = 0.0
MAX_CONFIDENCE: Final = 1.0
MIN_SMOOTHING_ALPHA: Final = 0.1
MAX_SMOOTHING_ALPHA: Final = 0.9

# Ensemble method (zweistufige Analyse)
CONF_ENSEMBLE_ENABLED: Final = "ensemble_enabled"
DEFAULT_ENSEMBLE_ENABLED: Final = False
CONF_ENSEMBLE_QUICK_MODEL: Final = "ensemble_quick_model"
CONF_ENSEMBLE_DETAILED_MODEL: Final = "ensemble_detailed_model"
DEFAULT_ENSEMBLE_QUICK_MODEL: Final = "mistral-small-latest"
DEFAULT_ENSEMBLE_DETAILED_MODEL: Final = "mistral-medium-latest"

# Critical Ensemble (Benchmark-optimiert, v3.1)
CONF_CRITICAL_ENSEMBLE_ENABLED: Final = "critical_ensemble_enabled"
DEFAULT_CRITICAL_ENSEMBLE_ENABLED: Final = False
CONF_CRITICAL_ENSEMBLE_QUICK_MODEL: Final = "critical_ensemble_quick_model"
CONF_CRITICAL_ENSEMBLE_DETAILED_MODEL: Final = "critical_ensemble_detailed_model"
DEFAULT_CRITICAL_ENSEMBLE_QUICK_MODEL: Final = "zai-glm-5-3-flash"
DEFAULT_CRITICAL_ENSEMBLE_DETAILED_MODEL: Final = "mistral-medium-latest"

# Filament types für Dropdown
FILAMENT_TYPES: Final = [
    "",           # Nicht gesetzt
    "PLA",
    "PETG",
    "ABS",
    "ASA",
    "TPU",
    "PC",
    "PA-CF",
    "Other",
]
